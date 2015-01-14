# openstack_dashboard.local.dashboards.project_nci.vlconfig.forms
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

import json
import logging
#import pdb ## DEBUG
import uuid

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import forms
from horizon import messages

from openstack_dashboard import api

from .constants import *


LOG = logging.getLogger(__name__)


class VLConfigForm(forms.SelfHandlingForm):
    repo_path = forms.RegexField(
        label=_("Puppet Repository Path"),
        required=True,
        regex=REPO_PATH_REGEX,
        help_text=_("Path component of the Puppet configuration repository URL."))

    repo_branch = forms.RegexField(
        label=_("Default Puppet Repository Branch"),
        required=True,
        regex=REPO_BRANCH_REGEX,
        help_text=_("The default branch to checkout from the Puppet configuration repository.  This value can be overridden in the launch instance dialog."))

    repo_key_public = forms.CharField(
        widget=forms.Textarea(attrs={"readonly": True}),
        label=_("Public Deployment Key"),
        required=False,
        help_text=_("SSH key with read-only access to the Puppet configuration repository."))

    repo_key_create = forms.BooleanField(
        label=_("Generate Deployment Key Pair"),
        required=False,
        initial=False,
        help_text=_("Generates a new SSH key pair for deploying the Puppet repository."))

    def __init__(self, request, *args, **kwargs):
        super(VLConfigForm, self).__init__(request, *args, **kwargs)
        self.saved_params = {}

        obj = None
        try:
            LOG.debug("Checking if project configuration exists")
            if api.swift.swift_object_exists(request, NCI_PVT_CONTAINER, PROJECT_CONFIG_PATH):
                LOG.debug("Loading project configuration")
                obj = api.swift.swift_get_object(request, NCI_PVT_CONTAINER, PROJECT_CONFIG_PATH)
        except Exception:
            # NB: Can't use "self.api_error()" here since form not yet validated.
            exceptions.handle(request)
            msg = _("Failed to load configuration data.")
            self.set_warning(msg)
            return

        try:
            if obj and obj.data:
                LOG.debug("Parsing project configuration")
                self.saved_params = json.loads(obj.data)
        except Exception as e:
            # NB: Can't use "self.api_error()" here since form not yet validated.
            LOG.exception("Error parsing project configuration: %s" % e)
            msg = _("Configuration data is corrupt and cannot be loaded.")
            self.set_warning(msg)
            return

        if not self.saved_params.get("repo_key_private"):
            self.fields["repo_key_create"].initial = True

        if not self.saved_params:
            if self.request.method == "GET":
                msg = _("No existing project configuration found.")
                self.set_warning(msg)
                self.fields["repo_path"].initial = "p/%s/puppet.git" % request.user.project_name
                self.fields["repo_branch"].initial = "master"
            return

        for k, v in self.saved_params.iteritems():
            if k in self.fields:
                self.fields[k].initial = v

    def handle(self, request, data):
        new_params = self.saved_params.copy()
        new_params.update([(k, v) for k, v in data.iteritems() if not k.startswith("repo_key_")])

        if data.get("repo_key_create", False):
            LOG.debug("Generating new repo key pair")
            tmp_key_name = "deploy-%s" % uuid.uuid4().hex
            try:
                # Use the Nova API to generate a new key pair and then delete
                # it since we only need the ciphertext.
                key = api.nova.keypair_create(request, tmp_key_name)
                api.nova.keypair_delete(request, key.id)
            except Exception:
                exceptions.handle(request)
                msg = _("Failed to generate key pair.")
                self.api_error(msg)
                return False

            new_params["repo_key_private"] = key.private_key

            # Strip any comments off the end.
            new_params["repo_key_public"] = " ".join(key.public_key.split(" ")[:2])

        if new_params != self.saved_params:
            obj_data = json.dumps(new_params)
            try:
                LOG.debug("Saving project configuration")

                # Make sure the container exists first.
                if not api.swift.swift_container_exists(request, NCI_PVT_CONTAINER):
                    api.swift.swift_create_container(request, NCI_PVT_CONTAINER)

                msg = "**WARNING**  Don't delete, rename or modify this container or any objects herein."
                api.swift.swift_api(request).put_object(NCI_PVT_CONTAINER,
                    NCI_PVT_README_NAME,
                    msg,
                    content_type="text/plain")

                api.swift.swift_api(request).put_object(NCI_PVT_CONTAINER,
                    PROJECT_CONFIG_PATH,
                    obj_data,
                    content_type="application/json")
            except Exception:
                exceptions.handle(request)
                msg = _("Failed to save configuration.")
                self.api_error(msg)
                return False

            self.saved_params = new_params
            messages.success(request, _("Configuration saved."))

        return True


# vim:ts=4 et sw=4 sts=4:

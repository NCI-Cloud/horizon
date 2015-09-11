# openstack_dashboard.local.dashboards.project_nci.vlconfig.forms
#
# Copyright (c) 2015, NCI, Australian National University.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#

import datetime
import json
import logging
#import pdb ## DEBUG
import sys
import uuid

from django.utils.translation import ugettext_lazy as _

from horizon import exceptions
from horizon import forms
from horizon import messages

from openstack_dashboard import api

from openstack_dashboard.local.nci import crypto as ncicrypto
from openstack_dashboard.local.nci.constants import *


LOG = logging.getLogger(__name__)


class VLConfigForm(forms.SelfHandlingForm):
    puppet_env = forms.RegexField(
        label=_("Default Puppet Environment"),
        required=True,
        regex=REPO_BRANCH_REGEX,
        help_text=_("Default Puppet configuration environment (or branch name).  This value can be overridden in the launch instance dialog."))

    repo_path = forms.RegexField(
        label=_("Puppet Repository Path"),
        required=True,
        regex=REPO_PATH_REGEX,
        help_text=_("Path component of the Puppet configuration repository URL."))

    repo_key_public = forms.CharField(
        widget=forms.Textarea(attrs={"readonly": True}),
        label=_("Public Deployment Key"),
        required=False)

    repo_key_fp = forms.CharField(
        widget=forms.TextInput(attrs={"readonly": True}),
        label=_("Deployment Key Fingerprint"),
        required=False)

    repo_key_create = forms.BooleanField(
        label=_("Generate New Deployment Key"),
        required=False,
        initial=True,
        help_text=_("Generates a new SSH key for deploying the Puppet configuration repository."))

    revision = forms.CharField(
        widget=forms.HiddenInput(),
        required=False)

    def __init__(self, request, *args, **kwargs):
        super(VLConfigForm, self).__init__(request, *args, **kwargs)
        self.saved_params = {}
        self.stash = ncicrypto.CryptoStash(request)

        obj = None
        try:
            LOG.debug("Checking if project configuration exists")
            container = nci_private_container_name(request)
            if api.swift.swift_object_exists(request, container, VL_PROJECT_CONFIG_OBJ):
                LOG.debug("Loading project configuration")
                obj = api.swift.swift_get_object(request, container, VL_PROJECT_CONFIG_OBJ)
        except:
            exceptions.handle(request)
            # NB: Can't use "self.api_error()" here since form not yet validated.
            msg = _("Failed to load configuration data.")
            self.set_warning(msg)
            return

        try:
            if obj and obj.data:
                LOG.debug("Parsing project configuration")
                self.saved_params = json.loads(obj.data)
        except ValueError as e:
            LOG.exception("Error parsing project configuration: {0}".format(e))
            messages.error(request, str(e))
            # NB: Can't use "self.api_error()" here since form not yet validated.
            msg = _("Configuration data is corrupt and cannot be loaded.")
            self.set_warning(msg)
            return

        if not self.saved_params:
            if request.method == "GET":
                msg = _("No existing project configuration found.")
                self.set_warning(msg)
                self.fields["puppet_env"].initial = "production"
                self.fields["repo_path"].initial = "p/{0}/puppet.git".format(request.user.project_name)
            return

        for k, v in self.saved_params.iteritems():
            if (k in self.fields) and not k.startswith("repo_key"):
                self.fields[k].initial = v

        partial_load = False
        if self.saved_params.get("stash"):
            try:
                self.stash.init_params(self.saved_params["stash"])
            except:
                exceptions.handle(request)
                partial_load = True
            else:
                if self.saved_params.get("repo_key"):
                    self.fields["repo_key_create"].initial = False

                    if request.method == "GET":
                        try:
                            key = self.stash.load_private_key(self.saved_params["repo_key"])
                            self.fields["repo_key_public"].initial = key.ssh_publickey()
                            self.fields["repo_key_fp"].initial = key.ssh_fingerprint()
                        except:
                            exceptions.handle(request)
                            partial_load = True

        if partial_load:
            # NB: Can't use "self.api_error()" here since form not yet validated.
            msg = _("The project configuration was only partially loaded.")
            self.set_warning(msg)

    def clean(self):
        data = super(VLConfigForm, self).clean()

        # Don't allow the form data to be saved if the revision stored in the
        # form by the GET request doesn't match what we've just loaded while
        # processing the POST request.
        if data.get("revision", "") != self.saved_params.get("revision", ""):
            if self.saved_params.get("revision"):
                msg = _("Saved configuration has changed since form was loaded.")
            else:
                msg = _("Failed to retrieve existing configuration for update.")
            raise forms.ValidationError(msg)

        return data

    def handle(self, request, data):
        new_params = self.saved_params.copy()
        if "repo_branch" in new_params:
            del new_params["repo_branch"]

        new_params.update([(k, v) for k, v in data.iteritems() if not k.startswith("repo_key")])

        try:
            # Make sure the container exists first.
            container = nci_private_container_name(request)
            if not api.swift.swift_container_exists(request, container):
                api.swift.swift_create_container(request, container)

            if not api.swift.swift_object_exists(request, container, "README"):
                msg = "**WARNING**  Don't delete, rename or modify this container or any objects herein."
                api.swift.swift_api(request).put_object(container,
                    "README",
                    msg,
                    content_type="text/plain")

            # And check that a temporary URL key is defined as we'll need it
            # when launching new instances.
            if not ncicrypto.swift_get_temp_url_key(request):
                LOG.debug("Generating temp URL secret key")
                ncicrypto.swift_create_temp_url_key(request)
                messages.success(request, _("Temporary URL key generated successfully."))
        except:
            exceptions.handle(request)
            msg = _("Failed to save configuration.")
            self.api_error(msg)
            return False

        if not self.stash.initialised:
            LOG.debug("Configuring crypto stash")
            try:
                self.stash.init_params()
                new_params["stash"] = self.stash.params
            except:
                exceptions.handle(request)
                msg = _("Failed to setup crypto stash.")
                self.api_error(msg)
                return False

        new_key = None
        if data.get("repo_key_create", False):
            LOG.debug("Generating new deployment key")
            try:
                new_key = self.stash.create_private_key()
                new_params["repo_key"] = new_key.metadata()
            except:
                exceptions.handle(request)
                msg = _("Failed to generate deployment key.")
                self.api_error(msg)
                return False

        if new_params != self.saved_params:
            new_params["revision"] = datetime.datetime.utcnow().isoformat()
            obj_data = json.dumps(new_params)
            try:
                try:
                    if self.saved_params.get("revision"):
                        backup_name = "{0}_{1}".format(VL_PROJECT_CONFIG_OBJ,
                            self.saved_params["revision"])
                        if not api.swift.swift_object_exists(request, container, backup_name):
                            LOG.debug("Backing up current project configuration")
                            api.swift.swift_copy_object(request,
                                container,
                                VL_PROJECT_CONFIG_OBJ,
                                container,
                                backup_name)

                    LOG.debug("Saving project configuration")
                    api.swift.swift_api(request).put_object(container,
                        VL_PROJECT_CONFIG_OBJ,
                        obj_data,
                        content_type="application/json")
                except:
                    # Python 2 doesn't have exception chaining so we have to
                    # save the original context to re-raise it below.
                    saved_ex = sys.exc_info()
                    try:
                        if new_key:
                            LOG.debug("Rolling back SSH key generation")
                            self.stash.delete(new_key)
                    except:
                        exceptions.handle(request)
                        msg = _("Failed to rollback new deployment key.")
                        messages.warning(request, msg)

                    raise saved_ex[0], saved_ex[1], saved_ex[2]
            except:
                exceptions.handle(request)
                msg = _("Failed to save configuration.")
                self.api_error(msg)
                return False

            self.saved_params = new_params
            messages.success(request, _("Configuration saved."))

        return True


# vim:ts=4 et sw=4 sts=4:

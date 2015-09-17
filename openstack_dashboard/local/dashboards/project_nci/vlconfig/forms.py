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
import re
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

SPECIAL_FIELDS_REGEX = r"(repo_key|eyaml)"


class VLConfigForm(forms.SelfHandlingForm):
    puppet_action = forms.ChoiceField(
        label=_("Default Puppet Action"),
        required=True,
        choices=[("auto", _("Automatic"))] + PUPPET_ACTION_CHOICES,
        help_text=_("Default Puppet command to execute.  This value can be overridden in the launch instance dialog."))

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
        label=_("Create New Deployment Key"),
        required=False,
        initial=True,
        help_text=_("Generates a new SSH key for deploying the Puppet configuration repository."))

    eyaml_key_fp = forms.CharField(
        widget=forms.TextInput(attrs={"readonly": True}),
        label=_("Hiera eyaml Key Fingerprint"),
        required=False)

    eyaml_key_upload = forms.FileField(
        label=_("Import Hiera eyaml Key"),
        required=False)

    eyaml_cert_fp = forms.CharField(
        widget=forms.TextInput(attrs={"readonly": True}),
        label=_("Hiera eyaml Certificate Fingerprint"),
        required=False)

    eyaml_cert_upload = forms.FileField(
        label=_("Import Hiera eyaml Certificate"),
        required=False)

    eyaml_update = forms.ChoiceField(
        label=_("Modify Hiera eyaml Certificate/Key Pair"),
        required=False,
        choices=[
            ("", _("No Change")),
            ("create", _("Create New")),
            ("import", _("Import")),
        ],
        initial="create",
        help_text=_("Create or import a certificate/key pair for encrypting data in Hiera."))

    revision = forms.CharField(
        widget=forms.HiddenInput(),
        required=False)

    def __init__(self, request, *args, **kwargs):
        super(VLConfigForm, self).__init__(request, *args, **kwargs)
        self.saved_params = {}
        self.cfg_timestamp = None
        self.stash = ncicrypto.CryptoStash(request)

        obj = None
        try:
            LOG.debug("Checking if project configuration exists")
            container = nci_private_container_name(request)
            config_obj_name = nci_vl_project_config_name()
            if api.swift.swift_object_exists(request, container, config_obj_name):
                LOG.debug("Loading project configuration")
                obj = api.swift.swift_get_object(request, container, config_obj_name)
                self.cfg_timestamp = obj.timestamp
                if self.cfg_timestamp is None:
                    # Workaround bug in Ceph which doesn't return the "X-Timestamp"
                    # header.  This appears to be fixed in Ceph 0.87.1 (Giant).
                    #   http://tracker.ceph.com/issues/8911
                    #   https://github.com/ceph/ceph/commit/8c573c8826096d90dc7dfb9fd0126b9983bc15eb
                    metadata = api.swift.swift_api(request).head_object(container, config_obj_name)
                    try:
                        lastmod = metadata["last-modified"]
                        # https://github.com/ceph/ceph/blob/v0.80.6/src/rgw/rgw_rest.cc#L325
                        dt = datetime.datetime.strptime(lastmod, "%a, %d %b %Y %H:%M:%S %Z")
                        assert dt.utcoffset() is None
                        self.cfg_timestamp = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    except Exception as e:
                        LOG.exception("Error getting project config timestamp: {0}".format(e))
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
                self.fields["puppet_action"].initial = "auto"
                self.fields["puppet_env"].initial = "production"
                self.fields["repo_path"].initial = "p/{0}/puppet.git".format(request.user.project_name)
            return

        for k, v in self.saved_params.iteritems():
            if (k in self.fields) and not re.match(SPECIAL_FIELDS_REGEX, k):
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

                if self.saved_params.get("eyaml_key"):
                    self.fields["eyaml_update"].initial = ""

                    if request.method == "GET":
                        try:
                            key = self.stash.load_private_key(self.saved_params["eyaml_key"])
                            self.fields["eyaml_key_fp"].initial = key.fingerprint()
                        except:
                            exceptions.handle(request)
                            partial_load = True

                if self.saved_params.get("eyaml_cert"):
                    self.fields["eyaml_update"].initial = ""

                    if request.method == "GET":
                        try:
                            cert = self.stash.load_x509_cert(self.saved_params["eyaml_cert"])
                            self.fields["eyaml_cert_fp"].initial = cert.fingerprint()
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

        if data.get("puppet_action", "none") != "none":
            if not (data.get("repo_key_create", False) or self.saved_params.get("repo_key")):
                msg = _("The selected Puppet action requires a deployment key.")
                self._errors["puppet_action"] = self.error_class([msg])
            elif not (data.get("eyaml_update") or (self.saved_params.get("eyaml_key") and self.saved_params.get("eyaml_cert"))):
                msg = _("The selected Puppet action requires a Hiera eyaml certificate/key pair.")
                self._errors["puppet_action"] = self.error_class([msg])

        if data.get("eyaml_update", "") == "import":
            if not data.get("eyaml_key_upload"):
                msg = _("No private key specified to import.")
                self._errors["eyaml_key_upload"] = self.error_class([msg])

            if not data.get("eyaml_cert_upload"):
                msg = _("No certificate specified to import.")
                self._errors["eyaml_cert_upload"] = self.error_class([msg])

        return data

    def handle(self, request, data):
        new_params = self.saved_params.copy()
        if "repo_branch" in new_params:
            del new_params["repo_branch"]

        new_params.update([(k, v) for k, v in data.iteritems() if not re.match(SPECIAL_FIELDS_REGEX, k)])

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

        new_repo_key = None
        new_eyaml_key = None
        new_eyaml_cert = None
        try:
            if data.get("repo_key_create", False):
                LOG.debug("Generating new deployment key")
                try:
                    new_repo_key = self.stash.create_private_key()
                    new_params["repo_key"] = new_repo_key.metadata()
                except:
                    exceptions.handle(request)
                    msg = _("Failed to generate deployment key.")
                    self.api_error(msg)
                    return False

            eyaml_update = data.get("eyaml_update", "")
            if eyaml_update:
                try:
                    if eyaml_update == "create":
                        LOG.debug("Generating new eyaml key")
                        new_eyaml_key = self.stash.create_private_key()
                    elif eyaml_update == "import":
                        LOG.debug("Importing eyaml key")
                        new_eyaml_key = self.stash.import_private_key(data.get("eyaml_key_upload"))

                    assert new_eyaml_key
                    new_params["eyaml_key"] = new_eyaml_key.metadata()
                except:
                    exceptions.handle(request)
                    msg = _("Failed to update Hiera eyaml key.")
                    self.api_error(msg)
                    return False

                try:
                    if eyaml_update == "create":
                        LOG.debug("Generating new eyaml certificate")
                        new_eyaml_cert = self.stash.create_x509_cert(new_eyaml_key,
                            "hiera-eyaml-{0}".format(request.user.project_name),
                            100 * 365)
                    elif eyaml_update == "import":
                        LOG.debug("Importing eyaml certificate")
                        new_eyaml_cert = self.stash.import_x509_cert(data.get("eyaml_cert_upload"))

                    assert new_eyaml_cert
                    new_params["eyaml_cert"] = new_eyaml_cert.metadata()
                except:
                    exceptions.handle(request)
                    msg = _("Failed to update Hiera eyaml certificate.")
                    self.api_error(msg)
                    return False

                try:
                    if not new_eyaml_cert.verify_key_pair(new_eyaml_key):
                        msg = _("Hiera eyaml certificate was not signed with the given key.")
                        self.api_error(msg)
                        return False
                except:
                    exceptions.handle(request)
                    msg = _("Failed to verify Hiera eyaml certificate/key pair.")
                    self.api_error(msg)
                    return False

            if new_params != self.saved_params:
                new_params["revision"] = datetime.datetime.utcnow().isoformat()
                obj_data = json.dumps(new_params)
                try:
                    config_obj_name = nci_vl_project_config_name()
                    if self.cfg_timestamp:
                        backup_name = "{0}_{1}".format(config_obj_name,
                            self.cfg_timestamp)
                        if not api.swift.swift_object_exists(request, container, backup_name):
                            LOG.debug("Backing up current project configuration")
                            api.swift.swift_copy_object(request,
                                container,
                                config_obj_name,
                                container,
                                backup_name)
                    elif api.swift.swift_object_exists(request, container, config_obj_name):
                        msg = _("Couldn't backup previous configuration.  No timestamp available.")
                        messages.warning(request, msg)

                    LOG.debug("Saving project configuration")
                    api.swift.swift_api(request).put_object(container,
                        config_obj_name,
                        obj_data,
                        content_type="application/json")
                except:
                    exceptions.handle(request)
                    msg = _("Failed to save configuration.")
                    self.api_error(msg)
                    return False

                new_repo_key = None
                new_eyaml_key = None
                new_eyaml_cert = None
                self.saved_params = new_params
                messages.success(request, _("Configuration saved."))
        finally:
            try:
                if new_repo_key:
                    LOG.debug("Rolling back deployment key generation")
                    self.stash.delete(new_repo_key)
            except Exception as e:
                LOG.exception("Error deleting orphaned deployment key: {0}".format(e))

            try:
                if new_eyaml_key:
                    LOG.debug("Rolling back eyaml key generation")
                    self.stash.delete(new_eyaml_key)
            except Exception as e:
                LOG.exception("Error deleting orphaned eyaml key: {0}".format(e))

            try:
                if new_eyaml_cert:
                    LOG.debug("Rolling back eyaml certificate generation")
                    self.stash.delete(new_eyaml_cert)
            except Exception as e:
                LOG.exception("Error deleting orphaned eyaml certificate: {0}".format(e))

        return True


# vim:ts=4 et sw=4 sts=4:

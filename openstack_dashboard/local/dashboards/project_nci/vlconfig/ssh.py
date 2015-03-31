# openstack_dashboard.local.dashboards.project_nci.vlconfig.ssh
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

import binascii
import logging
import os.path
#import pdb ## DEBUG

from paramiko.rsakey import RSAKey
from paramiko.ssh_exception import SSHException
from StringIO import StringIO

from django.conf import settings

from openstack_dashboard import api

from .constants import *


LOG = logging.getLogger(__name__)


class SSHKey(object):
    def __init__(self, key, request, ref=None):
        self._key = key
        self._project_name = request.user.project_name
        self._ref = ref

    def get_private(self, password=None):
        """Returns the private key in PEM format."""
        buf = StringIO()
        self._key.write_private_key(buf, password)
        return buf.getvalue()

    def get_public(self):
        """Returns the public key in OpenSSH format."""
        return "%s %s %s" % (
            self._key.get_name(),
            self._key.get_base64(),
            self._project_name
        )

    def get_fingerprint(self, sep=":"):
        return sep.join([binascii.hexlify(x) for x in self._key.get_fingerprint()])

    def get_ref(self):
        """Returns the key store reference for this key."""
        return self._ref


class SSHKeyStore(object):
    def __init__(self, request):
        self._request = request

    def generate(self):
        """Generates a new SSH key and saves it in the key store."""
        key = SSHKey(RSAKey.generate(3072), self._request)

        # TODO: Switch to using Barbican for key storage instead when it's
        # released.
        path = "ssh-key/%s" % key.get_fingerprint("")
        container = nci_private_container_name(self._request)
        api.swift.swift_api(self._request).put_object(container,
            path,
            key.get_private(self.__secret()),
            content_type="text/plain")

        key._ref = path
        return key

    def load(self, ref):
        """Loads an existing key from the key store."""
        obj = api.swift.swift_get_object(self._request,
            nci_private_container_name(self._request),
            ref)
        raw_key = RSAKey.from_private_key(StringIO(obj.data), self.__secret())
        return SSHKey(raw_key, self._request, ref)

    def delete(self, ref):
        """Deletes the given key from the key store."""
        assert ref.startswith("ssh-key/")
        container = nci_private_container_name(self._request)
        api.swift.swift_delete_object(self._request, container, ref)

    @staticmethod
    def __secret():
        if hasattr(settings, "NCI_SSH_KEY_STORE_SECRET_PATH"):
            path = settings.NCI_SSH_KEY_STORE_SECRET_PATH
        else:
            path = "/etc/openstack-dashboard"
            if not os.path.isdir(path):
                path = settings.LOCAL_PATH

            path = os.path.join(path, ".ssh_key_store_secret")

        try:
            with open(path) as fh:
                secret = fh.readline().strip()
                if not secret:
                    raise ValueError("Secret is empty")
                return secret
        except (IOError, ValueError) as e:
            LOG.exception("Error loading key store secret: %s" % e)
            raise SSHException("SSH key store configuration fault.  Please report to help desk.")


# vim:ts=4 et sw=4 sts=4:

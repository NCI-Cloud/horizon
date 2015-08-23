# openstack_dashboard.local.nci.crypto
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

import base64
import binascii
import Crypto.PublicKey.RSA
import Crypto.Random
import hashlib
import hmac
import logging
import os.path
import paramiko.rsakey
#import pdb ## DEBUG
import time
import uuid
import urllib
import urlparse

from StringIO import StringIO

from django.conf import settings

from openstack_dashboard import api

from .constants import *
from .exceptions import CryptoError


LOG = logging.getLogger(__name__)

TEMP_URL_KEY_METADATA_HDR = "X-Account-Meta-Temp-URL-Key"


class PrivateKey(object):
    def __init__(self, rsa, request, ref):
        self._rsa = rsa
        self._request = request
        self._ref = ref

    def export_private(self):
        """Exports the encrypted private key."""
        pw = self.get_passphrase()
        try:
            return self._rsa.exportKey("PEM", pw)
        except Exception as e:
            LOG.exception("Error exporting private key (ref %s): %s" % (self._ref, e))
            raise CryptoError("Failed to export private key with ref: %s" % self._ref)

    def export_public(self, format="PEM"):
        """Exports the public key component in the requested format."""
        assert format in ("PEM", "OpenSSH")
        try:
            out = self._rsa.publickey().exportKey(format)
        except Exception as e:
            LOG.exception("Error exporting public key (ref %s): %s" % (self._ref, e))
            raise CryptoError("Failed to export public key with ref: %s" % self._ref)

        if format == "OpenSSH":
            out += " " + self._request.user.project_name

        return out

    def get_fingerprint(self, sep=":"):
        """Returns the SSH fingerprint of the key."""
        try:
            pem = self._rsa.exportKey("PEM")
            fp = paramiko.rsakey.RSAKey(file_obj=StringIO(pem)).get_fingerprint()
        except Exception as e:
            LOG.exception("Error generating SSH key fingerprint (ref %s): %s" % (self._ref, e))
            raise CryptoError("Failed to get fingerprint for key with ref: %s" % self._ref)

        return sep.join([binascii.hexlify(x) for x in fp])

    def get_ref(self, public=False):
        """Returns the key store reference for this key."""
        assert self._ref
        if public:
            endpoint = urlparse.urlsplit(api.base.url_for(self._request, "object-store"))
            path = "/".join([
                endpoint.path,
                urllib.quote(nci_private_container_name(self._request)),
                urllib.quote(self._ref),
            ])
            return urlparse.urlunsplit(list(endpoint[:2]) + [path, "", ""])
        else:
            return self._ref

    def generate_temp_url(self):
        """Generates a signed temporary URL for the stored key object."""
        secret = swift_get_temp_url_key(self._request)
        if not secret:
            raise CryptoError("Temporary URL key not configured in object store")

        # The signature needs to include the full path to the object as
        # requested by the client.
        public_url = urlparse.urlsplit(self.get_ref(True))
        sig_path = public_url.path
        if sig_path.startswith("/swift/"):
            # Ceph uses a URI prefix to distinguish between S3 and Swift API
            # calls so we need to remove this otherwise the calculated
            # signature will be wrong.
            # https://github.com/ceph/ceph/blob/v0.80.7/src/rgw/rgw_swift.cc#L578
            sig_path = sig_path[6:]

        expires = int(time.time()) + 3600
        data = "\n".join(["GET", str(expires), sig_path])
        LOG.debug("Temporary URL data for signature: %s" % repr(data))

        sig = hmac.new(secret.encode(), data.encode(), hashlib.sha1).hexdigest()
        params = urllib.urlencode({
            "temp_url_sig": sig,
            "temp_url_expires": expires,
        })
        return urlparse.urlunsplit(list(public_url[:3]) + [params, ""])

    def get_passphrase(self):
        """Returns the passphrase used to encrypt the private key."""
        assert self._ref

        if hasattr(settings, "NCI_PRIVATE_KEY_STORE_SECRET_PATH"):
            path = settings.NCI_PRIVATE_KEY_STORE_SECRET_PATH
        else:
            path = "/etc/openstack-dashboard"
            if not os.path.isdir(path):
                path = settings.LOCAL_PATH

            path = os.path.join(path, ".pvt_key_store_secret")

        try:
            with open(path) as fh:
                ks_secret = fh.readline().strip()
                if not ks_secret:
                    raise ValueError("Secret is empty")
        except (IOError, ValueError) as e:
            LOG.exception("Error loading key store secret: %s" % e)
            raise CryptoError("Private key store internal fault")

        h = hashlib.sha256(ks_secret)
        h.update(self._request.user.project_id)
        h.update(self._ref)
        return base64.b64encode(h.digest())

    def cloud_config_dict(self):
        """Dictionary for referencing key in user-data for a VM instance."""
        return {
            "url": self.generate_temp_url(),
            "pw": self.get_passphrase(),
        }


# TODO: Use Barbican for storing keys instead of Swift.  However, the
# following blueprint will need to be implemented first so that we can
# retrieve keys from inside the VM.
#   https://blueprints.launchpad.net/nova/+spec/instance-users
class PrivateKeyStore(object):
    def __init__(self, request):
        self._request = request

    def generate(self):
        """Generates a new private key and saves it in the key store."""
        try:
            rsa = Crypto.PublicKey.RSA.generate(3072)
        except Exception as e:
            LOG.exception("Error generating new RSA key: %s" % e)
            raise CryptoError("Failed to generate new private key")

        # Try and avoid overwriting an existing key in case we happen to get a
        # duplicate UUID (should be very rare).  Swift API doesn't have an
        # atomic "create unique" function so there is a race condition here
        # but risk is low.
        container = nci_private_container_name(self._request)
        ref = "keystore/%s" % uuid.uuid4()
        if api.swift.swift_object_exists(self._request, container, ref):
            ref = "keystore/%s" % uuid.uuid4()
            if api.swift.swift_object_exists(self._request, container, ref):
                raise CryptoError("Unable to generate unique key reference")

        key = PrivateKey(rsa, self._request, ref)
        api.swift.swift_api(self._request).put_object(container,
            ref,
            key.export_private(),
            content_type="text/plain")
        return key

    def load(self, ref):
        """Loads an existing key from the key store."""
        obj = api.swift.swift_get_object(self._request,
            nci_private_container_name(self._request),
            ref)

        key = PrivateKey(None, self._request, ref)
        pw = key.get_passphrase()
        try:
            key._rsa = Crypto.PublicKey.RSA.importKey(obj.data, pw)
        except Exception as e:
            LOG.exception("Error importing RSA key: %s" % e)
            raise CryptoError("Failed to import private key with ref: %s" % ref)

        return key

    def delete(self, ref):
        """Deletes the given key from the key store."""
        assert ref.startswith("keystore/")
        container = nci_private_container_name(self._request)
        api.swift.swift_delete_object(self._request, container, ref)


def swift_create_temp_url_key(request):
    """Assigns a secret key for generating temporary URLs to the object store."""
    try:
        secret = base64.b64encode(Crypto.Random.get_random_bytes(32))
    except Exception as e:
        LOG.exception("Error generating temp URL key: %s" % e)
        raise CryptoError("Failed to generate temporary URL key")

    headers = { TEMP_URL_KEY_METADATA_HDR: secret }
    api.swift.swift_api(request).post_account(headers)

    # Workaround for Ceph bug #10668 which doesn't include the key in the
    # returned metadata even though a value is assigned.
    # http://tracker.ceph.com/issues/10668
    # https://github.com/ceph/ceph/commit/80570e7b6c000f45d81ac3d05240b1f5c85ce125
    metadata = api.swift.swift_api(request).head_account()
    if TEMP_URL_KEY_METADATA_HDR.lower() not in metadata:
        container = nci_private_container_name(request)
        api.swift.swift_api(request).put_object(container,
            "temp-url-key",
            secret,
            content_type="text/plain")


def swift_get_temp_url_key(request):
    """Retrieves the secret key for generating temporary URLs to the object store."""
    secret = None
    metadata = api.swift.swift_api(request).head_account()
    if TEMP_URL_KEY_METADATA_HDR.lower() in metadata:
        secret = metadata[TEMP_URL_KEY_METADATA_HDR.lower()]
    else:
        # See above notes on Ceph workaround.
        container = nci_private_container_name(request)
        if api.swift.swift_object_exists(request, container, "temp-url-key"):
            obj = api.swift.swift_get_object(request, container, "temp-url-key")
            secret = obj.data

    return secret


# vim:ts=4 et sw=4 sts=4:

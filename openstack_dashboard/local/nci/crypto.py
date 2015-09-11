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
import hashlib
import hmac
import logging
import os
import os.path
import paramiko.rsakey
#import pdb ## DEBUG
import six
import subprocess
import time
import uuid
import urllib
import urlparse

from StringIO import StringIO

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, Encoding, load_pem_private_key, NoEncryption, PrivateFormat
    USE_NEW_CRYPTO_LIB=True
except:
    from OpenSSL import crypto
    USE_NEW_CRYPTO_LIB=False

from django.conf import settings

from openstack_dashboard import api

from .constants import *
from .exceptions import CryptoError


LOG = logging.getLogger(__name__)

TEMP_URL_KEY_METADATA_HDR = "X-Account-Meta-Temp-URL-Key"


class CryptoStashItem(object):
    def __init__(self, stash, metadata):
        self._stash = stash

        if metadata is None:
            # Avoid overwriting an existing object in case we happen to get a
            # duplicate UUID (should be very rare).  Swift API doesn't have an
            # atomic "create unique" function so there is a race condition here
            # but risk should be low.
            container = nci_private_container_name(self._request)
            ref = "{0}/{1}".format(self._stash._base_ref, uuid.uuid4())
            if api.swift.swift_object_exists(self._request, container, ref):
                ref = "{0}/{1}".format(self._stash._base_ref, uuid.uuid4())
                if api.swift.swift_object_exists(self._request, container, ref):
                    raise CryptoError("Unable to generate unique stash item reference")
        else:
            ref = metadata.get("ref")
            if not ref:
                raise CryptoError("Incomplete metadata for crypto stash item")

        self._ref = ref

    @property
    def _request(self):
        return self._stash._request

    @property
    def ref(self):
        """Returns the stash reference for this item."""
        assert self._ref
        return self._ref

    @property
    def public_ref(self):
        """Returns the full public URL stash reference for this item."""
        endpoint = urlparse.urlsplit(api.base.url_for(self._request, "object-store"))
        path = "/".join([
            endpoint.path,
            urllib.quote(nci_private_container_name(self._request)),
            urllib.quote(self.ref),
        ])
        return urlparse.urlunsplit(list(endpoint[:2]) + [path, "", ""])

    def metadata(self):
        """Returns a dictionary of the item's metadata for storage."""
        return {
            "version": 1,
            "ref": self.ref,
        }

    def generate_temp_url(self):
        """Generates a signed temporary URL for this item."""
        secret = swift_get_temp_url_key(self._request)
        if not secret:
            raise CryptoError("Temporary URL key not configured in object storage")

        # The signature needs to include the full path to the object as
        # requested by the client.
        public_url = urlparse.urlsplit(self.public_ref)
        sig_path = public_url.path
        if sig_path.startswith("/swift/"):
            # Ceph uses a URI prefix to distinguish between S3 and Swift API
            # calls so we need to remove this otherwise the calculated
            # signature will be wrong.
            # https://github.com/ceph/ceph/blob/v0.80.7/src/rgw/rgw_swift.cc#L578
            sig_path = sig_path[6:]

        expires = int(time.time()) + 3600
        data = "\n".join(["GET", str(expires), sig_path])
        LOG.debug("Temporary URL data for signature: {0}".format(repr(data)))

        sig = hmac.new(secret.encode(), data.encode(), hashlib.sha1).hexdigest()
        params = urllib.urlencode({
            "temp_url_sig": sig,
            "temp_url_expires": expires,
        })
        return urlparse.urlunsplit(list(public_url[:3]) + [params, ""])

    def cloud_config_dict(self):
        """Dictionary for referencing item in user-data for a VM instance."""
        return {
            "url": self.generate_temp_url(),
        }


class CryptoStashItemWithPwd(CryptoStashItem):
    def __init__(self, stash, metadata):
        super(CryptoStashItemWithPwd, self).__init__(stash, metadata)

    @property
    def password(self):
        s1key = self._stash._s1key
        assert len(s1key) >= hashlib.sha256().digest_size

        # Second stage of HKDF simplified since we only need one round to
        # reach a key length equal to the digest size.
        h = hmac.new(s1key, digestmod=hashlib.sha256)
        h.update(self.ref)
        h.update(six.int2byte(1))
        k = h.digest()

        return base64.b64encode(k)

    def cloud_config_dict(self):
        d = super(CryptoStashItemWithPwd, self).cloud_config_dict()
        d["pw"] = self.password
        return d


class PrivateKey(CryptoStashItemWithPwd):
    def __init__(self, rsa_obj, stash, metadata):
        super(PrivateKey, self).__init__(stash, metadata)
        self._rsa_obj = rsa_obj
        self._ssh_key_cache = None

    def export(self):
        """Exports the private key in encrypted PEM format."""
        pw = self.password

        try:
            if USE_NEW_CRYPTO_LIB:
                return self._rsa_obj.private_bytes(Encoding.PEM,
                    PrivateFormat.PKCS8,
                    BestAvailableEncryption(pw))
            else:
                return crypto.dump_privatekey(crypto.FILETYPE_PEM,
                    self._rsa_obj,
                    "aes-256-cbc",
                    pw)
        except Exception as e:
            LOG.exception("Error exporting private key (ref {0}): {1}".format(self.ref, e))
            raise CryptoError("Failed to export private key with ref: {0}".format(self.ref))

    @property
    def _ssh_key(self):
        if self._ssh_key_cache is None:
            if USE_NEW_CRYPTO_LIB:
                pem = self._rsa_obj.private_bytes(Encoding.PEM,
                    PrivateFormat.TraditionalOpenSSL,
                    NoEncryption())
            else:
                pem = crypto.dump_privatekey(crypto.FILETYPE_PEM, self._rsa_obj)
                if "BEGIN RSA PRIVATE KEY" not in pem:
                    # Convert from PKCS#8 into "traditional" RSA format.
                    # There isn't a way to do this via the PyOpenSSL API.
                    args = (
                        "/usr/bin/openssl",
                        "rsa",
                        "-inform",
                        "PEM",
                        "-outform",
                        "PEM",
                    )
                    proc = subprocess.Popen(args,
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
                    pem, err = proc.communicate(pem)
                    rc = proc.poll()
                    if rc:
                        if err:
                            LOG.error("Subprocess error output: {0}".format(err.strip()))
                        raise subprocess.CalledProcessError(rc, args[0])

            self._ssh_key_cache = paramiko.rsakey.RSAKey(file_obj=StringIO(pem))

        return self._ssh_key_cache

    def ssh_publickey(self):
        """Exports the public key component in OpenSSH format."""
        try:
            return "{0} {1} {2}".format(
                self._ssh_key.get_name(),
                self._ssh_key.get_base64(),
                self._request.user.project_name,
            )
        except Exception as e:
            LOG.exception("Error exporting public SSH key (ref {0}): {1}".format(self.ref, e))
            raise CryptoError("Failed to export public SSH key with ref: {0}".format(self.ref))

    def ssh_fingerprint(self):
        """Returns the SSH fingerprint of the key."""
        try:
            fp = self._ssh_key.get_fingerprint()
        except Exception as e:
            LOG.exception("Error generating SSH key fingerprint (ref {0}): {1}".format(self.ref, e))
            raise CryptoError("Failed to get SSH fingerprint for key with ref: {0}".format(self.ref))

        return ":".join([binascii.hexlify(x) for x in fp])


# TODO: Use Barbican for storage instead of Swift.  However, the following
# blueprint will need to be implemented first so that we can retrieve
# items via cloud-init in the VM without needing a full user token.
#   https://blueprints.launchpad.net/nova/+spec/instance-users
class CryptoStash(object):
    def __init__(self, request, params=None):
        self._request = request
        self._base_ref = "stash"
        self._params = {}
        self._s1key_cache = None

        if params is not None:
            self.init_params(params)

    @property
    def _s1key(self):
        if self._s1key_cache is None:
            if "salt" not in self.params:
                raise CryptoError("Crypto stash parameters incomplete")

            try:
                salt = base64.b64decode(self.params.get("salt"))
                if len(salt) < 32:
                    raise ValueError("Salt is too short")
            except Exception as e:
                LOG.exception("Error decoding crypto stash salt: {0}".format(e))
                raise CryptoError("Crypto stash internal fault")

            if hasattr(settings, "NCI_CRYPTO_STASH_SECRET_PATH"):
                path = settings.NCI_CRYPTO_STASH_SECRET_PATH
            else:
                path = "/etc/openstack-dashboard"
                if not os.path.isdir(path):
                    path = settings.LOCAL_PATH

                path = os.path.join(path, ".crypto_stash")

            try:
                with open(path) as fh:
                    master = fh.readline().strip()
                    if not master:
                        raise ValueError("Master secret is empty")

                    master = base64.b64decode(master)
                    if len(master) < 32:
                        raise ValueError("Master secret is too short")
            except Exception as e:
                LOG.exception("Error loading crypto stash master secret: {0}".format(e))
                raise CryptoError("Crypto stash internal fault")

            # This is the first stage of HKDF:
            #   https://tools.ietf.org/html/rfc5869
            # NB: It's assumed that the master key was generated from a
            # cryptographically strong random source.
            h = hmac.new(salt, digestmod=hashlib.sha256)
            h.update(master)
            self._s1key_cache = h.digest()

        return self._s1key_cache

    def init_params(self, params=None):
        """Creates new or loads existing stash parameters."""
        if params is not None:
            if not isinstance(params, dict):
                raise CryptoError("Invalid crypto stash parameters type")
            elif params.get("version", 0) != 1:
                raise CryptoError("Unsupported crypto stash format")
            self._params = params
        else:
            self._params = {
                "version": 1,
                "salt": base64.b64encode(os.urandom(32)),
            }

        self._s1key_cache = None

    @property
    def initialised(self):
        return bool(self._params)

    @property
    def params(self):
        """Returns current stash parameters."""
        if not self._params:
            raise CryptoError("Crypto stash parameters not set")
        return self._params

    def create_private_key(self):
        """Generates a new private key and saves it in the stash."""
        try:
            if USE_NEW_CRYPTO_LIB:
                rsa_obj = rsa.generate_private_key(65537,
                    3072,
                    default_backend())
            else:
                rsa_obj = crypto.PKey()
                rsa_obj.generate_key(crypto.TYPE_RSA, 3072)
        except Exception as e:
            LOG.exception("Error generating new RSA key: {0}".format(e))
            raise CryptoError("Failed to generate new private key")

        key = PrivateKey(rsa_obj, self, None)
        container = nci_private_container_name(self._request)
        api.swift.swift_api(self._request).put_object(container,
            key.ref,
            key.export(),
            content_type="text/plain")
        return key

    def load_private_key(self, metadata):
        """Loads an existing private key from the stash."""
        if not isinstance(metadata, dict):
            raise CryptoError("Metadata missing or invalid type when loading private key")
        key = PrivateKey(None, self, metadata)
        obj = api.swift.swift_get_object(self._request,
            nci_private_container_name(self._request),
            key.ref)

        pw = key.password
        try:
            if USE_NEW_CRYPTO_LIB:
                LOG.debug("Using new cryptography library")
                key._rsa_obj = load_pem_private_key(obj.data,
                    pw,
                    default_backend())
            else:
                LOG.debug("Using old cryptography library")
                key._rsa_obj = crypto.load_privatekey(crypto.FILETYPE_PEM,
                    obj.data,
                    pw)
        except Exception as e:
            LOG.exception("Error loading RSA key: {0}".format(e))
            raise CryptoError("Failed to load private key with ref: {0}".format(key.ref))

        return key

    def delete(self, obj):
        """Deletes the given item from the stash."""
        assert isinstance(obj, CryptoStashItem)
        container = nci_private_container_name(self._request)
        api.swift.swift_delete_object(self._request,
            container,
            obj.ref)


def swift_create_temp_url_key(request):
    """Assigns a secret key for generating temporary Swift URLs."""
    try:
        secret = base64.b64encode(os.urandom(32))
    except Exception as e:
        LOG.exception("Error generating temp URL key: {0}".format(e))
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
    """Retrieves the secret key for generating temporary Swift URLs."""
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

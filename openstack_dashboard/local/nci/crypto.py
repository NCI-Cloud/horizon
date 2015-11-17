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
import datetime
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
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, Encoding, load_pem_private_key, NoEncryption, PrivateFormat
    from cryptography.x509.oid import NameOID
    USE_NEW_CRYPTO_LIB=True
except:
    from OpenSSL import crypto
    from Crypto.PublicKey import RSA as pycrypto_RSA
    USE_NEW_CRYPTO_LIB=False

from django.conf import settings

from openstack_dashboard import api

from .constants import *
from .exceptions import CryptoError


LOG = logging.getLogger(__name__)

TEMP_URL_KEY_METADATA_HDR = "X-Account-Meta-Temp-URL-Key"


class CryptoStashItem(object):
    def __init__(self, impl, stash, metadata):
        self._impl = impl
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
    def __init__(self, impl, stash, metadata):
        super(CryptoStashItemWithPwd, self).__init__(impl, stash, metadata)

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
    def __init__(self, impl, stash, metadata):
        super(PrivateKey, self).__init__(impl, stash, metadata)
        self._cache = {}

    def export(self):
        """Exports the private key in encrypted PEM format."""
        pw = self.password

        try:
            if USE_NEW_CRYPTO_LIB:
                return self._impl.private_bytes(Encoding.PEM,
                    PrivateFormat.PKCS8,
                    BestAvailableEncryption(pw))
            else:
                return crypto.dump_privatekey(crypto.FILETYPE_PEM,
                    self._impl,
                    "aes-256-cbc",
                    pw)
        except Exception as e:
            LOG.exception("Error exporting private key (ref {0}): {1}".format(self.ref, e))
            raise CryptoError("Failed to export private key with ref: {0}".format(self.ref))

    def fingerprint(self):
        """Returns the fingerprint of the PKCS#8 DER key."""
        try:
            if USE_NEW_CRYPTO_LIB:
                der = self._impl.private_bytes(Encoding.DER,
                    PrivateFormat.PKCS8,
                    NoEncryption())
            else:
                pem = crypto.dump_privatekey(crypto.FILETYPE_PEM, self._impl)
                # Convert from PEM encoding to PKCS#8 DER.
                # There isn't a way to do this via the PyOpenSSL API so we
                # have to use PyCrypto instead.
                der = pycrypto_RSA.importKey(pem).exportKey('DER', pkcs=8)
        except Exception as e:
            LOG.exception("Error generating key fingerprint (ref {0}): {1}".format(self.ref, e))
            raise CryptoError("Failed to get fingerprint for key with ref: {0}".format(self.ref))

        fp = hashlib.sha1(der).digest()
        return ":".join([binascii.hexlify(x) for x in fp])

    @property
    def _ssh_key(self):
        if "ssh_key" not in self._cache:
            if USE_NEW_CRYPTO_LIB:
                pem = self._impl.private_bytes(Encoding.PEM,
                    PrivateFormat.TraditionalOpenSSL,
                    NoEncryption())
            else:
                pem = crypto.dump_privatekey(crypto.FILETYPE_PEM, self._impl)
                if "BEGIN RSA PRIVATE KEY" not in pem:
                    # Convert from PKCS#8 into "traditional" RSA format.
                    # There isn't a way to do this via the PyOpenSSL API so we
                    # have to use PyCrypto instead.
                    pem = pycrypto_RSA.importKey(pem).exportKey('PEM', pkcs=1)

            self._cache["ssh_key"] = paramiko.rsakey.RSAKey(file_obj=StringIO(pem))

        return self._cache["ssh_key"]

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


class Certificate(CryptoStashItem):
    def __init__(self, impl, stash, metadata):
        super(Certificate, self).__init__(impl, stash, metadata)

    def export(self):
        """Exports the certificate in PEM format."""
        try:
            if USE_NEW_CRYPTO_LIB:
                return self._impl.public_bytes(Encoding.PEM)
            else:
                return crypto.dump_certificate(crypto.FILETYPE_PEM, self._impl)
        except Exception as e:
            LOG.exception("Error exporting certificate (ref {0}): {1}".format(self.ref, e))
            raise CryptoError("Failed to export certificate with ref: {0}".format(self.ref))

    def fingerprint(self):
        """Returns the fingerprint of the certificate."""
        try:
            if USE_NEW_CRYPTO_LIB:
                fp = self._impl.fingerprint(hashes.SHA1())
                return ":".join([binascii.hexlify(x) for x in fp])
            else:
                return self._impl.digest("sha1").lower()
        except Exception as e:
            LOG.exception("Error generating certificate fingerprint (ref {0}): {1}".format(self.ref, e))
            raise CryptoError("Failed to get fingerprint for certificate with ref: {0}".format(self.ref))

    def verify_key_pair(self, key):
        """Verifies that the certificate is paired with the given private key."""
        assert isinstance(key, PrivateKey)
        test_data = base64.b64decode("Ag5Ns98mgdLxiq3pyuNecMCXGUcYopmPNyc6GsJ6wd0=")

        try:
            if USE_NEW_CRYPTO_LIB:
                pad = padding.PSS(padding.MGF1(hashes.SHA256()),
                    padding.PSS.MAX_LENGTH)
                signer = key._impl.signer(pad, hashes.SHA256())
                signer.update(test_data)
                sig = signer.finalize()

                verifier = self._impl.public_key().verifier(sig,
                    pad,
                    hashes.SHA256())
                verifier.update(test_data)

                try:
                    verifier.verify()
                except InvalidSignature:
                    return False
            else:
                sig = crypto.sign(key._impl, test_data, "sha256")

                try:
                    crypto.verify(self._impl, sig, test_data, "sha256")
                except:
                    return False
        except Exception as e:
            LOG.exception("Error verifying certificate/key pair (cert {0}; key {1}): {2}".format(self.ref, key.ref, e))
            raise CryptoError("Failed to verify certificate \"{0}\" and key \"{1}\"".format(self.ref, key.ref))

        return True

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

    def _save_to_stash(self, item_cls, key_impl):
        item = item_cls(key_impl, self, None)
        container = nci_private_container_name(self._request)
        api.swift.swift_api(self._request).put_object(container,
            item.ref,
            item.export(),
            content_type="text/plain")
        return item

    def create_private_key(self):
        """Generates a new private key and saves it in the stash."""
        try:
            if USE_NEW_CRYPTO_LIB:
                key_impl = rsa.generate_private_key(65537,
                    3072,
                    default_backend())
            else:
                key_impl = crypto.PKey()
                key_impl.generate_key(crypto.TYPE_RSA, 3072)
        except Exception as e:
            LOG.exception("Error generating new RSA key: {0}".format(e))
            raise CryptoError("Failed to generate new private key")

        return self._save_to_stash(PrivateKey, key_impl)

    def import_private_key(self, upload):
        """Imports an unencrypted private key into the stash."""
        if (upload.size < 0) or (upload.size > 262144):
            raise CryptoError("Uploaded file too large - expected a private key")

        try:
            if USE_NEW_CRYPTO_LIB:
                key_impl = load_pem_private_key(upload.read(),
                    None,
                    default_backend())
                key_size = key_impl.key_size
            else:
                key_impl = crypto.load_privatekey(crypto.FILETYPE_PEM,
                    upload.read())
                key_size = key_impl.bits()
        except Exception as e:
            LOG.exception("Error importing RSA key: {0}".format(e))
            raise CryptoError("Import failed - expected a PEM encoded unencrypted private key")

        if key_size < 3072:
            raise CryptoError("Import failed - key must be 3072 bits or larger")

        return self._save_to_stash(PrivateKey, key_impl)

    def load_private_key(self, metadata):
        """Loads an existing private key from the stash."""
        if not isinstance(metadata, dict):
            raise CryptoError("Metadata missing or invalid type when loading private key")
        key = PrivateKey(None, self, metadata)
        swift_obj = api.swift.swift_get_object(self._request,
            nci_private_container_name(self._request),
            key.ref,
            resp_chunk_size=None)

        pw = key.password
        try:
            if USE_NEW_CRYPTO_LIB:
                LOG.debug("Using new cryptography library")
                key._impl = load_pem_private_key(swift_obj.data,
                    pw,
                    default_backend())
            else:
                LOG.debug("Using old cryptography library")
                key._impl = crypto.load_privatekey(crypto.FILETYPE_PEM,
                    swift_obj.data,
                    pw)
        except Exception as e:
            LOG.exception("Error loading RSA key: {0}".format(e))
            raise CryptoError("Failed to load private key with ref: {0}".format(key.ref))

        return key

    def create_x509_cert(self, key, subject_cn, valid_days):
        """Returns a new self-signed X.509 certificate in PEM format."""
        assert isinstance(key, PrivateKey)
        now = datetime.datetime.utcnow()
        nvb = now + datetime.timedelta(days=-1)
        nva = now + datetime.timedelta(days=valid_days)

        try:
            if USE_NEW_CRYPTO_LIB:
                builder = x509.CertificateBuilder()
                builder = builder.serial_number(int(uuid.uuid4()))
                builder = builder.not_valid_before(nvb)
                builder = builder.not_valid_after(nva)

                pub_key_impl = key._impl.public_key()
                builder = builder.public_key(pub_key_impl)

                cn = x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME,
                        subject_cn if isinstance(subject_cn, six.text_type) else six.u(subject_cn)),
                ])
                builder = builder.subject_name(cn)
                builder = builder.issuer_name(cn)

                builder = builder.add_extension(
                    x509.BasicConstraints(ca=True, path_length=0),
                    True)
                builder = builder.add_extension(
                    x509.SubjectKeyIdentifier.from_public_key(pub_key_impl),
                    False)
                builder = builder.add_extension(
                    x509.AuthorityKeyIdentifier.from_issuer_public_key(pub_key_impl),
                    False)

                cert_impl = builder.sign(key._impl,
                    hashes.SHA256(),
                    default_backend())
            else:
                cert_impl = crypto.X509()
                cert_impl.set_version(2)
                cert_impl.set_serial_number(int(uuid.uuid4()))
                cert_impl.set_notBefore(nvb.strftime("%Y%m%d%H%M%SZ"))
                cert_impl.set_notAfter(nva.strftime("%Y%m%d%H%M%SZ"))
                cert_impl.set_pubkey(key._impl)

                subject = cert_impl.get_subject()
                subject.CN = subject_cn
                cert_impl.set_issuer(subject)

                cert_impl.add_extensions([
                    crypto.X509Extension(b"basicConstraints",
                        True,
                        b"CA:TRUE, pathlen:0"),
                    crypto.X509Extension(b"subjectKeyIdentifier",
                        False,
                        b"hash",
                        subject=cert_impl),
                ])

                # This has to be done after the above since it can't extract
                # the subject key from the certificate until it's assigned.
                cert_impl.add_extensions([
                    crypto.X509Extension(b"authorityKeyIdentifier",
                        False,
                        b"keyid:always",
                        issuer=cert_impl),
                ])

                cert_impl.sign(key._impl, "sha256")
        except Exception as e:
            LOG.exception("Error creating X.509 certificate: {0}".format(e))
            raise CryptoError("Failed to create X.509 certificate")

        return self._save_to_stash(Certificate, cert_impl)

    def import_x509_cert(self, upload):
        """Imports a certificate into the stash."""
        if (upload.size < 0) or (upload.size > 262144):
            raise CryptoError("Uploaded file too large - expected an X.509 certificate")

        try:
            if USE_NEW_CRYPTO_LIB:
                cert_impl = x509.load_pem_x509_certificate(upload.read(),
                    default_backend())
            else:
                cert_impl = crypto.load_certificate(crypto.FILETYPE_PEM,
                    upload.read())
        except Exception as e:
            LOG.exception("Error importing X.509 certificate: {0}".format(e))
            raise CryptoError("Import failed - expected a PEM encoded X.509 certificate")

        return self._save_to_stash(Certificate, cert_impl)

    def load_x509_cert(self, metadata):
        """Loads an existing certificate from the stash."""
        if not isinstance(metadata, dict):
            raise CryptoError("Metadata missing or invalid type when loading certificate")
        cert = Certificate(None, self, metadata)
        swift_obj = api.swift.swift_get_object(self._request,
            nci_private_container_name(self._request),
            cert.ref,
            resp_chunk_size=None)

        try:
            if USE_NEW_CRYPTO_LIB:
                cert._impl = x509.load_pem_x509_certificate(swift_obj.data,
                    default_backend())
            else:
                cert._impl = crypto.load_certificate(crypto.FILETYPE_PEM,
                    swift_obj.data)
        except Exception as e:
            LOG.exception("Error loading X.509 certificate: {0}".format(e))
            raise CryptoError("Failed to load X.509 certificate with ref: {0}".format(cert.ref))

        return cert

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
    container = nci_private_container_name(request)
    metadata = api.swift.swift_api(request).head_account()
    if TEMP_URL_KEY_METADATA_HDR.lower() in metadata:
        secret = metadata[TEMP_URL_KEY_METADATA_HDR.lower()]

        try:
            if api.swift.swift_object_exists(request, container, "temp-url-key"):
                api.swift.swift_delete_object(request,
                    container,
                    "temp-url-key")
        except:
            pass
    else:
        # See above notes on Ceph workaround.
        if api.swift.swift_object_exists(request, container, "temp-url-key"):
            swift_obj = api.swift.swift_get_object(request,
                container,
                "temp-url-key",
                resp_chunk_size=None)
            secret = swift_obj.data

    return secret


# vim:ts=4 et sw=4 sts=4:

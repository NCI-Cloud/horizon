# Defaults for the NCI Partner Cloud dashboard.  These can be overridden in
# the "local_settings.py" file.

SESSION_TIMEOUT = 86400

# Protect CSRF/session cookies from cross-site scripting.
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True

# Hook for replacing built-in dashboard panels.
HORIZON_CONFIG["customization_module"] = "openstack_dashboard.local.nci.customisation"

# Add the "local" directory to the "INSTALLED_APPS" path so that we can
# publish static files from there.
# NB: This doesn't apply to static files served via Apache.
# TODO: Change logo using new theme support instead?
# TODO: Investigate "AUTO_DISCOVER_STATIC_FILES" in Liberty or later.
ADD_INSTALLED_APPS = [
    'openstack_dashboard.local',
]

# Maximum number of vNICs to attach when launching a VM.
NCI_VM_NETWORK_INTF_LIMIT = 4

# Whether to permit two or more vNICs to be connected to the same network.
# In the Icehouse release, Nova rejects all such requests with a
# "NetworkDuplicated" exception.  But starting in Juno there is a new
# configuration option which can enable it (default is off):
#   https://github.com/openstack/nova/commit/322cc9336fe6f6fe9b3f0da33c6b26a3e5ea9b0c
# And from Liberty onwards, the option will be removed and it will
# be enabled by default:
#   https://github.com/openstack/nova/commit/4306d9190f49e7fadf88669d18effedabc880d3b
NCI_DUPLICATE_VM_NETWORK_INTF = False

# Role that grants users the ability to attach a VM to the external network.
NCI_EXTERNAL_NET_PERM = "openstack.roles.nci_external_net"

# Per-tenant fixed public IP address allocations.  The default of an empty
# dictionary means that all tenants will use the global IP allocation pool.
NCI_FIXED_PUBLIC_IPS = {}

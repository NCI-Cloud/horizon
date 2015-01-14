# Defaults for the NCI Partner Cloud dashboard.  These can be overridden in
# the "local_settings.py" file.

SESSION_TIMEOUT = 86400

# Hook for replacing built-in dashboard panels.
HORIZON_CONFIG["customization_module"] = "openstack_dashboard.local.nci.customisation"

# Role that grants users the ability to attach a VM to the external network.
NCI_EXTERNAL_NET_PERM = "openstack.roles.nci_external_net"

# Per-tenant fixed public IP address allocations.  The default of an empty
# dictionary means that all tenants will use the global IP allocation pool.
NCI_FIXED_PUBLIC_IPS = {}

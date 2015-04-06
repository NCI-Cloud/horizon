# TODO: Due to the presence of "_10_project.py" in this directory, we also
# require this file to ensure that the "project" and "admin" dashboards
# maintain the same display order with respect to each other.  This issue
# appears to be fixed in Juno:
#   https://bugs.launchpad.net/horizon/+bug/1342999
# UPDATE: We now need this file anyway but keeping the above comment for now.
DASHBOARD = 'admin'

# See also: _10_project.py
ADD_INSTALLED_APPS = [
    'openstack_dashboard.local.dashboards.admin_nci',
    'openstack_dashboard.dashboards.admin',
]

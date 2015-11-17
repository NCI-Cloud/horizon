DASHBOARD = 'project'

# Add our modified project dashboard to the "INSTALLED_APPS" path.
# Django doco says that the final component of each path has to be unique,
# however it doesn't seem to bother Horizon.  But just to be on the safe
# side we've named the module "project_nci", although the slug will
# still be "project".
ADD_INSTALLED_APPS = [
    'openstack_dashboard.local.dashboards.project_nci',
    'openstack_dashboard.dashboards.project',
]

from openstack_dashboard.local.nci.exceptions import CryptoError
ADD_EXCEPTIONS = {
    'recoverable': (CryptoError,),
}

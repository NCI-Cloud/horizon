DASHBOARD = 'project'

# Add our modified project dashboard to the "INSTALLED_APPS" path.
# Django doco says that the final component of each path has to be unique,
# however it doesn't seem to bother Horizon.  But just to be on the safe
# side we've named the module "project_nci", although the slug will
# still be "project".
#
# Also, add the "local" directory so that we can publish static files
# from there; eg. for overriding the logo images shipped with Horizon.
# This is really a global setting rather than related just to the project
# dashboard but we can't augment the "INSTALLED_APPS" path in
# "local_settings.py"; it can only be completely redefined there.
# Hence, it's just easier done here.
# NB: This doesn't apply to static files served via Apache.
ADD_INSTALLED_APPS = [
    'openstack_dashboard.local.dashboards.project_nci',
    'openstack_dashboard.dashboards.project',
    'openstack_dashboard.local',
]

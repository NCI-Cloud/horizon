# openstack_dashboard.local.dashboards.project_nci.access_and_security.tabs
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

from openstack_dashboard.dashboards.project.access_and_security import tabs as base_mod

# Hide the security groups tab.
base_mod.SecurityGroupsTab.allowed = lambda *x: False


# vim:ts=4 et sw=4 sts=4:

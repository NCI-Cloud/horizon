# openstack_dashboard.local.dashboards.project_nci.access_and_security.views
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

from openstack_dashboard.dashboards.project.access_and_security import views as base_mod


class NCIIndexView(base_mod.IndexView):
    tab_group_class = base_mod.IndexView.AccessAndSecurityTabs
    tab_group_class.tabs = [x for x in tab_group_class.tabs if x.slug != "security_groups_tab"]


# vim:ts=4 et sw=4 sts=4:

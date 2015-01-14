# openstack_dashboard.local.dashboards.project_nci.instances.views
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

from openstack_dashboard.dashboards.project.instances import views as base_mod

from . import workflows


class NCILaunchInstanceView(base_mod.LaunchInstanceView):
    workflow_class = workflows.NCILaunchInstance


# vim:ts=4 et sw=4 sts=4:

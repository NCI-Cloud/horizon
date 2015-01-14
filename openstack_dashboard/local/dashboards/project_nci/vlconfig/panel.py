# openstack_dashboard.local.dashboards.project_nci.vlconfig.panel
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

from django.utils.translation import ugettext_lazy as _

import horizon

from openstack_dashboard.dashboards.project import dashboard


class VLConfig(horizon.Panel):
    name = _("Configuration")
    slug = "vlconfig"


dashboard.Project.register(VLConfig)

# vim:ts=4 et sw=4 sts=4:

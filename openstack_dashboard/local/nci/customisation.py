# openstack_dashboard.local.nci.customisation
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
# You might assume that it ought to be possible to replace the built-in
# panels with customised versions using the "Pluggable Settings" mechanism by
# first removing the existing panel and then adding the custom panel class.
# Unfortunately this doesn't work in practice due to the limitations
# described below.
#
# In "horizon.Site._process_panel_configuration()", when a panel is removed
# it is only removed from the dashboard's class registry.  Any corresponding
# panel group in the "panels" attribute is *not* updated.  In contrast,
# when a panel is added then in addition to the registry being updated,
# the slug is appended to the corresponding panel group, or else the panel
# class is added directly to the "panels" attribute if no group is specified.
# This has the following effects:
#
# (i) Adding the new panel to the same group fails because this results in
# duplicate slugs in the group which in turn causes a "KeyError" when
# removing classes from a temporary copy of the class registry in
# "horizon.Dashboard.get_panel_groups()".
#
# (ii) Adding the new panel without a group succeeds at first, but later on
# an error occurs in "horizon.Dashboard._autodiscover()" when it tries to
# wrap the panel class in a panel group but that fails as the constructor
# expects an iterable type.
#
# So to work around this, we are using the older customisation mechanism
# instead to programatically replace the panels.  This also has an added
# benefit of maintaining the relative order of panels in each dashboard.
#
# Another possible option could be to symlink "dashboard.py" into the
# custom directory tree but that would also then require symlinking
# every unmodified panel as well since the code always looks for them
# relative to that file.
# https://github.com/openstack/horizon/blob/stable/kilo/horizon/base.py#L563
#

import logging
#import pdb ## DEBUG

from django.utils.importlib import import_module

import horizon


LOG = logging.getLogger(__name__)


def replace_panels(dash_slug, panels):
    dash = horizon.get_dashboard(dash_slug)
    for slug, mod_path in panels:
        if not dash.unregister(dash.get_panel(slug).__class__):
            LOG.error("Failed to unregister panel: %s" % slug)
        else:
            # When the panel module is imported it registers its panel class
            # with the dashboard.
            import_module(mod_path)


identity_panels = [
    ("projects", "openstack_dashboard.local.dashboards.identity_nci.projects.panel"),
    ("users", "openstack_dashboard.local.dashboards.identity_nci.users.panel"),
]

replace_panels("identity", identity_panels)


project_panels = [
    ("access_and_security", "openstack_dashboard.local.dashboards.project_nci.access_and_security.panel"),
    ("containers", "openstack_dashboard.local.dashboards.project_nci.containers.panel"),
    ("instances", "openstack_dashboard.local.dashboards.project_nci.instances.panel"),
]

replace_panels("project", project_panels)


# vim:ts=4 et sw=4 sts=4:

# openstack_dashboard.local.nci.customisation
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#
# In theory, it ought to be possible to replace the built-in panels with
# customised versions using the "Pluggable Settings" mechanism by first
# removing the existing panel and then adding the custom panel class.
# Unfortunately this doesn't work in practice because of some serious
# bugs as described below.
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
# A cursory look at the Juno code suggests that both these issues are
# still present.
#
# So to work around this, we are using this older customisation mechanism
# instead to programatically replace the panels.  This does have an added
# benefit of maintaining the order or panels in the dashboard.
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


project_panels = [
    ("access_and_security", "openstack_dashboard.local.dashboards.project_nci.access_and_security.panel"),
    ("containers", "openstack_dashboard.local.dashboards.project_nci.containers.panel"),
    ("instances", "openstack_dashboard.local.dashboards.project_nci.instances.panel"),
]

replace_panels("project", project_panels)


# vim:ts=4 et sw=4 sts=4:

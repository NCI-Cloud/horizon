# openstack_dashboard.local.dashboards.project_nci.containers.urls
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

from django.conf.urls import patterns
from django.conf.urls import url

from openstack_dashboard.dashboards.project.containers.urls import urlpatterns as orig_urlpatterns

from . import views


VIEW_MOD = "openstack_dashboard.local.dashboards.project_nci.containers.views"

urlpatterns = []
for x in orig_urlpatterns:
    if getattr(x, "name", "") == "index":
        x = patterns(VIEW_MOD, url(x.regex.pattern, views.NCIContainerView.as_view(), name=x.name))[0]

    urlpatterns.append(x)


# vim:ts=4 et sw=4 sts=4:

# openstack_dashboard.local.dashboards.project_nci.access_and_security.urls
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

from django.conf.urls import patterns
from django.conf.urls import url

from openstack_dashboard.dashboards.project.access_and_security.urls import urlpatterns as orig_urlpatterns

from . import tabs


urlpatterns = []
for x in orig_urlpatterns:
    if getattr(x, "namespace", "") == "security_groups":
        continue

    urlpatterns.append(x)


# vim:ts=4 et sw=4 sts=4:

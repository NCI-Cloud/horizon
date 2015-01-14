# openstack_dashboard.local.dashboards.project_nci.vlconfig.urls
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
#

from django.conf.urls import patterns
from django.conf.urls import url

from .views import IndexView


urlpatterns = patterns("",
    url(r"^$", IndexView.as_view(), name="index"),
)

# vim:ts=4 et sw=4 sts=4:

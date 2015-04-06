# openstack_dashboard.local.dashboards.admin_nci.projects.urls
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

from django.conf.urls import patterns
from django.conf.urls import url

from openstack_dashboard.dashboards.admin.projects.urls import urlpatterns as orig_urlpatterns

from . import views


VIEW_MOD = "openstack_dashboard.local.dashboards.admin_nci.projects.views"

urlpatterns = []
for x in orig_urlpatterns:
    if getattr(x, "name", "") == "create":
        x = patterns(VIEW_MOD, url(x.regex.pattern, views.NCICreateProjectView.as_view(), name=x.name))[0]
    elif getattr(x, "name", "") == "update":
        x = patterns(VIEW_MOD, url(x.regex.pattern, views.NCIUpdateProjectView.as_view(), name=x.name))[0]

    urlpatterns.append(x)


# vim:ts=4 et sw=4 sts=4:

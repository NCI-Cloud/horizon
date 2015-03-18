# openstack_dashboard.local.dashboards.project_nci.vlconfig.views
#
# Copyright (c) 2014, NCI, Australian National University.
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

from django.core.urlresolvers import reverse_lazy

from horizon import forms

from .constants import VLCONFIG_INDEX_URL
from .forms import VLConfigForm


class IndexView(forms.ModalFormView):
    form_class = VLConfigForm
    template_name = "project/vlconfig/index.html"
    success_url = reverse_lazy(VLCONFIG_INDEX_URL)


# vim:ts=4 et sw=4 sts=4:

# openstack_dashboard.local.dashboards.project_nci.vlconfig.views
#
# Copyright (c) 2014, NCI, Australian National University.
# All Rights Reserved.
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

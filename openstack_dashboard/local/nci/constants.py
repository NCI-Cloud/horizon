# openstack_dashboard.local.nci.constants
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

import os

from django.conf import settings
from django.utils.translation import ugettext_lazy as _


__all__ = (
    "REPO_PATH_REGEX",
    "REPO_BRANCH_REGEX",
    "PUPPET_ACTION_CHOICES",
    "NCI_PVT_CONTAINER_PREFIX",
    "nci_private_container_name",
    "nci_vl_project_config_name",
)


REPO_PATH_REGEX = r"^[a-zA-Z][-a-zA-Z0-9_./]*\.git$"
REPO_BRANCH_REGEX = r"^[a-zA-Z][-a-zA-Z0-9_./]*$"

PUPPET_ACTION_CHOICES = [
    ("apply", _("Apply")),
    ("r10k-deploy", _("R10k Deploy")),
    ("none", _("None")),
]

NCI_PVT_CONTAINER_PREFIX = "nci-private-"


def nci_private_container_name(request):
    return NCI_PVT_CONTAINER_PREFIX + request.user.project_id


def nci_vl_project_config_name():
    if hasattr(settings, "NCI_VL_PROJECT_CFG_SUFFIX"):
        suffix = settings.NCI_VL_PROJECT_CFG_SUFFIX
    else:
        suffix = os.uname()[1].split(".")[0]
        assert suffix

    if suffix:
        return "project-config-{0}".format(suffix)
    else:
        return "project-config"


# vim:ts=4 et sw=4 sts=4:

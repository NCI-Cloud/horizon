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

from django.utils.translation import ugettext_lazy as _


REPO_PATH_REGEX = r"^[a-zA-Z][-a-zA-Z0-9_./]*\.git$"
REPO_BRANCH_REGEX = r"^[a-zA-Z][-a-zA-Z0-9_./]*$"

PUPPET_ACTION_CHOICES = [
    ("apply", _("Apply")),
    ("r10k-deploy", _("R10k Deploy")),
    ("none", _("None")),
]

# Swift paths
NCI_PVT_CONTAINER_PREFIX = "nci-private-"
VL_PROJECT_CONFIG_OBJ = "project-config"


def nci_private_container_name(request):
    return NCI_PVT_CONTAINER_PREFIX + request.user.project_id


# vim:ts=4 et sw=4 sts=4:

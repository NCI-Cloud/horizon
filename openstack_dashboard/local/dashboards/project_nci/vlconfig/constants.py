# openstack_dashboard.local.dashboards.project_nci.vlconfig.constants
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

VLCONFIG_INDEX_URL = "horizon:project:vlconfig:index"

REPO_PATH_REGEX = r"^[a-zA-Z][-a-zA-Z0-9_./]*\.git$"
REPO_BRANCH_REGEX = r"^[a-zA-Z][-a-zA-Z0-9_./]*$"

# Swift paths
NCI_PVT_CONTAINER_PREFIX = "nci-private-"
NCI_PVT_README_NAME = "README"
PROJECT_CONFIG_PATH = "project-config"


def nci_private_container_name(request):
    return NCI_PVT_CONTAINER_PREFIX + request.user.project_id


# vim:ts=4 et sw=4 sts=4:

# openstack_dashboard.local.dashboards.project_nci.containers.views
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

from openstack_dashboard.dashboards.project.containers import views as base_mod

from openstack_dashboard.local.dashboards.project_nci.vlconfig.constants import NCI_PVT_CONTAINER


class NCIContainerView(base_mod.ContainerView):
    def get_containers_data(self):
        containers = super(NCIContainerView, self).get_containers_data()
        if self.request.user.is_superuser:
            return containers
        else:
            # Hide the private NCI configuration container to help prevent
            # accidental deletion etc.
            return [x for x in containers if x.name != NCI_PVT_CONTAINER]


# vim:ts=4 et sw=4 sts=4:

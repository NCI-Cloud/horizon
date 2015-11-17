# openstack_dashboard.local.dashboards.identity_nci.users.views
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

from openstack_dashboard.dashboards.identity.users import views as base_mod


class NCIIndexView(base_mod.IndexView):
    def get_data(self):
        # Keystone users have UUIDs so this effectively filters out
        # any LDAP users.
        users = super(NCIIndexView, self).get_data()
        return [u for u in users if len(u.id) >= 32]


# vim:ts=4 et sw=4 sts=4:

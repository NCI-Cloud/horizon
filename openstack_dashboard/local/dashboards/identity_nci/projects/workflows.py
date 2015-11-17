# openstack_dashboard.local.dashboards.identity_nci.projects.workflows
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

#import pdb ## DEBUG

from openstack_dashboard.dashboards.identity.projects import workflows as base_mod


BASIC_MEMBERSHIP_TEMPLATE = "identity/projects/../projects_nci/_workflow_step_update_members_basic.html"


class NCICreateProject(base_mod.CreateProject):
    def __init__(self, request=None, context_seed=None, entry_point=None, *args, **kwargs):
        super(NCICreateProject, self).__init__(request=request,
            context_seed=context_seed,
            entry_point=entry_point,
            *args,
            **kwargs)

        members_step = self.get_step(base_mod.UpdateProjectMembersAction.slug)
        members_step.template_name = BASIC_MEMBERSHIP_TEMPLATE

        groups_step = self.get_step(base_mod.UpdateProjectGroupsAction.slug)
        if groups_step:
            groups_step.template_name = BASIC_MEMBERSHIP_TEMPLATE


class NCIUpdateProject(base_mod.UpdateProject):
    def __init__(self, request=None, context_seed=None, entry_point=None, *args, **kwargs):
        super(NCIUpdateProject, self).__init__(request=request,
            context_seed=context_seed,
            entry_point=entry_point,
            *args,
            **kwargs)

        members_step = self.get_step(base_mod.UpdateProjectMembersAction.slug)
        members_step.template_name = BASIC_MEMBERSHIP_TEMPLATE

        groups_step = self.get_step(base_mod.UpdateProjectGroupsAction.slug)
        if groups_step:
            groups_step.template_name = BASIC_MEMBERSHIP_TEMPLATE


# vim:ts=4 et sw=4 sts=4:

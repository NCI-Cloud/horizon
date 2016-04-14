# openstack_dashboard.local.dashboards.admin_nci.pupha.tabs
#
# Copyright (c) 2016, NCI, Australian National University.
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

import types
import itertools

from .constants import short_name, PROJECTS_TEMPLATE_NAME, SUMMARY_TEMPLATE_NAME
from . import tables

from horizon import tabs
from horizon import messages

from openstack_dashboard import api
from openstack_dashboard.openstack.common import log as logging

from django.utils.translation import ugettext_lazy as _

# surely there is a cleaner way to do this...?
from novaclient.exceptions import NotFound as NotFoundNova
from keystoneclient.openstack.common.apiclient.exceptions import NotFound as NotFoundKeystone

LOG = logging.getLogger(__name__)

# TODO this should probably be in views.py or maybe even models.py
class HostAggregate(object):
    """
    Has attributes:
      aggregate   --  object from api.nova.aggregate_details_list
      hypervisors --  list of objects with attributes including
                        instances -- list of objects with attributes including
                                       project
                                       flavor
    """
    def __init__(self, aggregate, hypervisors=None):
        self.aggregate = aggregate
        self.hypervisors = [] if hypervisors == None else hypervisors

class ProjectUsage(object):
    """
    TODO document
    """
    def __init__(self, project, vcpus, memory_mb):
        self.id        = project.id # TODO filter breaks without this, but not sure where it's actually required...
        self.project   = project
        self.vcpus     = vcpus
        self.memory_mb = memory_mb

    def __str__(self):
        return 'ProjectUsage(pid={pid}, vcpus={vcpus}, memory_mb={mmb})'.format(pid=self.project.id, vcpus=self.vcpus, mmb=self.memory_mb)
    def __repr__(self):
        return self.__str__()

class ProjectsTab(tabs.TableTab):
    """
    Displays per-project summary of resource usage within each host aggregate.

    If there is ever a host aggregate with name "context" or "aggregate", this
    will break. This is because TableTab makes calls to "get_{}_data".
    """
    name = _("Projects") # rendered as text in html
    slug = "projects" # url slug and id attribute (=> unique)
    template_name = PROJECTS_TEMPLATE_NAME

    @staticmethod
    def table_factory(aggregate):
        class AggregateProjectUsageTable(tables.ProjectUsageTable):
            class Meta(tables.ProjectUsageTable.Meta):
                name = verbose_name = aggregate.name
        return AggregateProjectUsageTable

    def __init__(self, tab_group, request):
        # load host aggregate data, so we can set up tables for tabs.TableTab.__init__
        aggregates = api.nova.aggregate_details_list(request)
        self.host_aggregates = [HostAggregate(aggregate=a) for a in aggregates]

        # define table_classes, which get used in TableTab.__init__
        ProjectsTab.table_classes = [ProjectsTab.table_factory(agg) for agg in aggregates]

        # set up get_{{ table_name }}_data methods, which get called by TableTab
        for ha in self.host_aggregates:
            # types.MethodType is used to bind the function to this object;
            # dummy "agg=agg" parameter is used to force capture of agg
            setattr(self, 'get_{}_data'.format(ha.aggregate.name), types.MethodType(lambda slf, ha=ha: self.get_aggregate_data(ha), self))

        # remaining initialisation can proceed now that tables are set up
        super(ProjectsTab, self).__init__(tab_group, request)

    def get_aggregate_data(self, host_aggregate):
        """
        Retrieve data for the specified HostAggregate, in a format that can be
        understood by an object from table_factory.

        This must be called after (or from within) get_context_data, otherwise
        the necessary data will not have been loaded.
        """
        # find instances running in this host aggregate
        instances = list(itertools.chain(*(h.instances for h in host_aggregate.hypervisors)))

        # find projects with instances running in this host aggregate
        projects = set([i.project for i in instances])

        # sum usage per project, and sort from most vcpus to fewest
        return sorted([ProjectUsage(
            project   = p, 
            vcpus     = sum(i.flavor.vcpus for i in instances if i.project == p),
            memory_mb = sum(i.flavor.ram   for i in instances if i.project == p)
        ) for p in projects], key=lambda pu:pu.vcpus, reverse=True)

    def get_context_data(self, request, **kwargs):
        """
        Get lots of nova/keystone data and return dict with keys:
            tables  -- list of DataTable objects to be rendered in this tab
            X_table -- individual DataTable objects, for X in aggregate names

        The overall process is to load all necessary data first, populating the
        list self.host_aggregates of HostAggregate objects, then to call
        super.get_context_data, which in turn makes calls back to get_{}_data
        for each table in the tab, and then finally to fill the return value.
        Documenting this because it feels a little weird calling the parent's
        function halfway through the child's function.
        """

        # TODO this should probably actually be done in IndexView (views.py)
        hypervisors  = api.nova.hypervisor_list(request)
        instances, _ = api.nova.server_list(request, all_tenants=True)
        projects, _  = api.keystone.tenant_list(request)
        flavors      = api.nova.flavor_list(request)

        # define these dicts to make it easier to look up objects
        flavor_d     = {f.id : f for f in flavors}
        project_d    = {p.id : p for p in projects}
        hypervisor_d = {short_name(getattr(h, h.NAME_ATTR)) : h for h in hypervisors}

        # check if any instances are missing necessary data, and if so, skip them
        hypervisor_instances = {} # otherwise, add them to this (short_name => [instance])
        for i in instances:
            # make sure we can tell which hypervisor is running this instance; if not, ignore it
            try:
                host = short_name(i.host_server)
                if host not in hypervisor_d:
                    messages.error(request, 'Instance {} has unknown host, so was ignored.'.format(i.id))
                    continue
            except AttributeError:
                messages.error(request, 'Instance {} is missing host, so was ignored.'.format(i.id))
                continue

            # api.nova.flavor_list (which wraps novaclient.flavors.list) does not get all flavors,
            # so if we have a reference to one that hasn't been retrieved, try looking it up specifically
            # (wrap this rather trivially in a try block to make the error less cryptic)
            if i.flavor['id'] not in flavor_d:
                try:
                    LOG.debug('Extra lookup for flavor "{}"'.format(i.flavor['id']))
                    flavor_d[i.flavor['id']] = api.nova.flavor_get(request, i.flavor['id'])
                except NotFoundNova:
                    messages.error(request, 'Instance {} has unknown flavor, so was ignored.'.format(i.id))
                    continue

            # maybe the same thing could happen for projects (haven't actually experienced this one though)
            if i.tenant_id not in project_d:
                try:
                    LOG.debug('Extra lookup for project "{}"'.format(i.tenant_id))
                    project_d[i.tenant_id] = api.keystone.tenant_get(request, i.tenant_id)
                except NotFoundKeystone:
                    messages.error(request, 'Instance {} has unknown project, so was ignored.'.format(i.id))
                    continue

            # expose related objects, so that no further lookups are required
            i.flavor  = flavor_d[i.flavor['id']]
            i.project = project_d[i.tenant_id]

            # all the necessary information is present, so populate the dict
            if host not in hypervisor_instances:
                hypervisor_instances[host] = []
            hypervisor_instances[host].append(i)

        # assign hypervisors to host aggregates
        for h in hypervisors:
            h.instances = hypervisor_instances[short_name(getattr(h, h.NAME_ATTR))]
            for ha in self.host_aggregates:
                if h.service['host'] in ha.aggregate.hosts:
                    ha.hypervisors.append(h)

        # parent sets "{{ table_name }}_table" keys corresponding to items in table_classes
        context = super(ProjectsTab, self).get_context_data(request, **kwargs)
        
        # now reorganise that a bit so that the template can iterate dynamically
        context['tables'] = [context['{}_table'.format(ha.aggregate.name)] for ha in self.host_aggregates]
        return context

class SummaryTab(tabs.TableTab):
    table_classes = (tables.SummaryTable,)
    name = _("Summary")
    slug = "summary"
    template_name = SUMMARY_TEMPLATE_NAME

    def get_summary_data(self):
        return [] # TODO implement

class TabGroup(tabs.TabGroup):
    tabs = (SummaryTab, ProjectsTab)
    slug = "pupha" # this is url slug, used with ..
    sticky = True # .. this to store tab state across requests

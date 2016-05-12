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

from .constants import TABLES_TEMPLATE_NAME, SUMMARY_TEMPLATE_NAME
from . import tables

from horizon import tabs

from django.utils.translation import ugettext_lazy as _

class DictObject(object):
    """Would have thought that this would be built-in somehow...."""
    def __init__(self, *args, **kwargs):
        self.__dict__.update(kwargs)

class ProjectsTab(tabs.TableTab):
    """
    Displays per-project summary of resource usage within each host aggregate.

    If there is ever a host aggregate with name "context" or "aggregate", this
    will break. This is because TableTab makes calls to "get_{}_data".
    """
    name = _('Projects') # rendered as text in html
    slug = 'projects' # url slug and id attribute (=> unique)
    template_name = TABLES_TEMPLATE_NAME

    @staticmethod
    def table_factory(aggregate):
        class AggregateProjectUsageTable(tables.ProjectUsageTable):
            class Meta(tables.ProjectUsageTable.Meta):
                name = verbose_name = aggregate.name
        return AggregateProjectUsageTable

    def __init__(self, tab_group, request):
        try:
            # make sure host aggregates are exposed
            self.host_aggregates = tab_group.host_aggregates
        except AttributeError:
            # raise the exception with slightly better description
            raise AttributeError('{} must be part of a tab group that exposes host aggregates'.format(self.__class__.__name__))

        # define table_classes, which get used in TableTab.__init__
        self.table_classes = [ProjectsTab.table_factory(a.aggregate) for a in self.host_aggregates]

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
        return sorted([DictObject(
            id        = p.id,
            project   = p,
            vcpus     = sum(i.flavor.vcpus for i in instances if i.project == p),
            memory_mb = sum(i.flavor.ram   for i in instances if i.project == p)
        ) for p in projects], key=lambda pu:pu.vcpus, reverse=True)

    def get_context_data(self, request, **kwargs):
        # parent sets "{{ table_name }}_table" keys corresponding to items in table_classes
        # (this call causes calls back to get_{}_data for each table in the Tab)
        context = super(ProjectsTab, self).get_context_data(request, **kwargs)

        # reorganise that a bit so that the template can iterate dynamically
        context['tables'] = [context['{}_table'.format(ha.aggregate.name)] for ha in self.host_aggregates]
        return context


class SummaryTab(tabs.TableTab):
    """
    Displays resource usage (physical count, overcommit value, used, remaining)
    for vcpus and memory for each host aggregate.

    It's a bit ugly.
    """
    table_classes = (tables.SummaryTable,)
    name = _('Summary')
    slug = 'summary'
    template_name = SUMMARY_TEMPLATE_NAME

    def __init__(self, tab_group, request):
        try:
            self.host_aggregates = tab_group.host_aggregates
        except AttributeError:
            raise AttributeError('{} must be part of a tab group that exposes host aggregates'.format(self.__class__.__name__))
        super(SummaryTab, self).__init__(tab_group, request)

    def get_summary_data(self):
        return [DictObject(
            id             = a.aggregate.id,
            name           = a.aggregate.name,
            vcpus          = sum(h.vcpus for h in a.hypervisors),
            memory_mb      = sum(h.memory_mb for h in a.hypervisors),
            vcpus_used     = sum(h.vcpus_used for h in a.hypervisors),
            memory_mb_used = sum(h.memory_mb_used for h in a.hypervisors),
            vcpu_o         = a.overcommit['cpu'], # these keys are hard-coded
            memory_mb_o    = a.overcommit['ram'], # to match nova.conf
        ) for a in self.host_aggregates]


class HypervisorsTab(tabs.TableTab):
    """
    Lists hypervisors within each host aggregate, and instances and resource
    usage on each hypervisor.

    This shares code with ProjectsTab, so should probably be refactored.

    If there is ever a hypervisor with name "context" or "aggregate", this
    will break (see ProjectsTab).
    """
    name = _('Hypervisors')
    slug = 'hypervisors'
    template_name = TABLES_TEMPLATE_NAME

    @staticmethod
    def table_factory(aggregate):
        class HypervisorTable(tables.HypervisorTable):
            class Meta(tables.HypervisorTable.Meta):
                name = verbose_name = aggregate.name
        return HypervisorTable

    def __init__(self, tab_group, request):
        """
        This is copy+paste from ProjectsTab... DRY!
        """
        try:
            # make sure host aggregates are exposed
            self.host_aggregates = tab_group.host_aggregates
        except AttributeError:
            # raise the exception with slightly better description
            raise AttributeError('{} must be part of a tab group that exposes host aggregates'.format(self.__class__.__name__))

        # define table_classes, which get used in TableTab.__init__
        HypervisorsTab.table_classes = [HypervisorsTab.table_factory(a.aggregate) for a in self.host_aggregates]

        # set up get_{{ table_name }}_data methods, which get called by TableTab
        for ha in self.host_aggregates:
            # types.MethodType is used to bind the function to this object;
            # dummy "agg=agg" parameter is used to force capture of agg
            setattr(self, 'get_{}_data'.format(ha.aggregate.name), types.MethodType(lambda slf, ha=ha: self.get_aggregate_data(ha), self))

        # remaining initialisation can proceed now that tables are set up
        super(HypervisorsTab, self).__init__(tab_group, request)

    def get_aggregate_data(self, host_aggregate):
        """
        Retrieve data for the specified HostAggregate, in a format that can be
        understood by an object from table_factory.

        This must be called after (or from within) get_context_data, otherwise
        the necessary data will not have been loaded.
        """
        # decorate hypervisors with some extra information
        # (need to do this in a context where host_aggregate is defined;
        # i.e. it cannot be done in the Table code.)
        for h in host_aggregate.hypervisors:
            h._meta = DictObject()

            # calculate resource usage, accounting for overcommit
            hypervisor_attr = {'cpu':'vcpus', 'ram':'memory_mb', 'disk':'local_gb'} # mapping host_aggregate.overcommit keys => hypervisor object attributes
            h._meta.usages = {k:float(getattr(h, r+'_used'))/(getattr(h, r)*host_aggregate.overcommit[k]) for (k, r) in hypervisor_attr.items()}
            h._meta.usage = max(h._meta.usages.values())
            h._meta.overcommit = host_aggregate.overcommit

        return host_aggregate.hypervisors #sorted(xs, key=lambda pu:pu.vcpus, reverse=True)

    def get_context_data(self, request, **kwargs):
        # parent sets "{{ table_name }}_table" keys corresponding to items in table_classes
        # (this call causes calls back to get_{}_data for each table in the Tab)
        context = super(HypervisorsTab, self).get_context_data(request, **kwargs)

        # reorganise that a bit so that the template can iterate dynamically
        context['tables'] = [context['{}_table'.format(ha.aggregate.name)] for ha in self.host_aggregates]
        return context


class TabGroup(tabs.TabGroup):
    tabs = (SummaryTab, ProjectsTab, HypervisorsTab)
    slug = "pupha" # this is url slug, used with ..
    sticky = True # .. this to store tab state across requests
    def __init__(self, request, **kwargs):
        if 'host_aggregates' in kwargs:
            self.host_aggregates = kwargs['host_aggregates']
        super(TabGroup, self).__init__(request, **kwargs)

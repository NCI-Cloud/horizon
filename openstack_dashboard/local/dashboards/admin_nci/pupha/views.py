# openstack_dashboard.local.dashboards.admin_nci.pupha.views
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

import re

from openstack_dashboard import api
from openstack_dashboard.openstack.common import log as logging

from horizon import tabs
from horizon import messages

from .tabs import TabGroup, DictObject
from . import constants
from .constants import short_name # separate import because it feels weird having short_name live in constants, so that may change..

# surely there is a cleaner way to do this...?
from novaclient.exceptions import NotFound as NotFoundNova
from keystoneclient.openstack.common.apiclient.exceptions import NotFound as NotFoundKeystone

from django.conf import settings

LOG = logging.getLogger(__name__)

def get_overcommit_ratios():
    """Return {cpu,ram,disk}_allocation_ratio values from django settings.
    Return 1.0 for any missing allocation ratios.
    """
    setting = 'NCI_NOVA_COMMIT_RATIOS'
    resources = ['cpu', 'ram', 'disk'] # hard-coded strings to match names in nova.conf
    ratios = getattr(settings, setting, {})
    for r in resources:
        if r not in ratios:
            LOG.debug('Missing {} overcommit ratio in {}; assuming value of 1.'.format(r, setting))
            ratios[r] = 1.
    return ratios

class HostAggregate(object):
    """
    Has attributes:
      aggregate   --  object from api.nova.aggregate_details_list
      overcommit  --  dict with keys matching "{}_allocation_ratio" in nova.conf
                      (see comment in get_overcommit_ratios)
      hypervisors --  list of objects with attributes including
                        instances -- list of objects with attributes including
                                       project
                                       flavor
    """
    def __init__(self, aggregate, hypervisors=None):
        self.aggregate = aggregate
        self.hypervisors = [] if hypervisors == None else hypervisors

class IndexView(tabs.TabbedTableView):
    tab_group_class = TabGroup
    template_name = constants.TEMPLATE_NAME
    page_title = constants.TITLE

    def get_tabs(self, request, **kwargs):
        """
        Pass host aggregate data to the TabGroup on construction, as an
        attribute "host_aggregates" in kwargs, which is a list of HostAggregate
        objects.

        This is useful because it avoids re-fetching the same data for each Tab
        in the TabGroup (which would take some time -- there's no caching).

        This is a slightly hacky solution, because if the way that TabView
        instantiates its TabGroup changes such that it's no longer done in
        get_tabs, this code will need to be updated accordingly. This seemed
        like this least hacky way of doing it, though.
        (TabView.get_tabs performs the initialisation of the TabGroup.)
        """
        aggregates   = api.nova.aggregate_details_list(request)
        hypervisors  = api.nova.hypervisor_list(request)
        instances, _ = api.nova.server_list(request, all_tenants=True)
        projects, _  = api.keystone.tenant_list(request)
        flavors      = api.nova.flavor_list(request)

        # define these dicts to make it easier to look up objects
        flavor_d     = {f.id : f for f in flavors}
        project_d    = {p.id : p for p in projects}
        hypervisor_d = {short_name(getattr(h, h.NAME_ATTR)) : h for h in hypervisors}

        # (only) this list ends up being shared with the TabGroup
        host_aggregates = [HostAggregate(aggregate=a) for a in aggregates]

        # if there are no aggregates, invent a HostAggregate to hold everything
        # (this is hacky but that's okay because nobody should actually want to
        # use this panel if running a cloud with no host aggregates.. this code
        # exists just so the dashboard doesn't break in that odd non-use case.)
        if not host_aggregates:
            host_aggregates = [HostAggregate(aggregate=DictObject(
                id       = 0,
                name     = '(none)',
                hosts    = [h.service['host'] for h in hypervisors],
                metadata = {}
            ))]

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
            h.instances = hypervisor_instances.get(short_name(getattr(h, h.NAME_ATTR)), [])
            for ha in host_aggregates:
                if h.service['host'] in ha.aggregate.hosts:
                    ha.hypervisors.append(h)

        # get overcommit values and allocated/available resource counts
        oc = get_overcommit_ratios()
        p = re.compile(r'^(?P<resource>cpu|ram|disk)_allocation_ratio$')
        for h in host_aggregates:
            h.overcommit = {k:oc[k] for k in oc} # copy default overcommit values
            for k in h.aggregate.metadata:
                m = p.match(k)
                if m:
                    try:
                        h.overcommit[m.group('resource')] = float(h.aggregate.metadata[k])
                    except ValueError:
                        LOG.debug('Could not parse host aggregate "{key}" metadata value "{value}" as float.'.format(key=k, value=h.aggregate.metadata[k]))
                        continue

        return super(IndexView, self).get_tabs(request, host_aggregates=host_aggregates, **kwargs)

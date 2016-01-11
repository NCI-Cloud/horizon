# openstack_dashboard.local.dashboards.admin_nci.hvlist.views
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

from horizon import views, messages
from openstack_dashboard import api
from iso8601 import parse_date
from colorsys import hsv_to_rgb
import re

from openstack_dashboard.openstack.common import log as logging
LOG = logging.getLogger(__name__)

short_name_p = re.compile(r'^tc(?P<n>\d+)$')
def short_name(hostname):
    m = short_name_p.match(hostname)
    if m:
        return m.group('n')
    return hostname

def binary_prefix_scale(b):
    """Return (prefix, scale) so that (b) B = (b*scale) (prefix)B."""
    binary = ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei']
    scale = 1
    for p in binary:
        if b < 1024:
            return (p, scale)
        scale /= 1024.
        b /= 1024.
    return (p, scale)

def usage_string(now, tot):
    """Return something like "0.5 / 1.0 kB" from now,tot=512,1024."""
    prefix, scale = binary_prefix_scale(tot)
    now *= scale
    tot *= scale

    def pretty(n):
        """Normally it is fine to round display values to nearest int,
        but for positive values < 1 it is helpful to show that they are nonzero."""
        if n >= 1: return '{:.0f}'.format(n)
        if n > 0: return '{:.1f}'.format(n)
        return '0'
    return '{n} / {t} {p}B'.format(n=pretty(now), t=pretty(tot), p=prefix)

class IndexView(views.APIView):
    template_name = 'admin/hvlist/index.html'

    def get_data(self, request, context, *args, **kwargs):
        # the template wants to display resource usage as percentages, so scale by 100%
        resbar_width = 100

        # grab all the data
        aggregates = api.nova.aggregate_details_list(request)
        hypervisors = api.nova.hypervisor_list(request)
        instances, _ = api.nova.server_list(request, all_tenants=True)
        projects, _ = api.keystone.tenant_list(request)
        flavs = api.nova.flavor_list(request)

        # reorganise some
        host_aggregates = [{'name':a.name, 'hypervisors':[]} for a in aggregates]
        projects = {p.id : p for p in projects}
        flavs = {f.id : f for f in flavs}
        hypervisor_instances = {} # OS-EXT-SRV-ATTR:host : [instance]
        for i in instances:
            # make sure we can tell which hypervisor is running this instance; if not, ignore it
            try:
                host = getattr(i, 'OS-EXT-SRV-ATTR:host')
            except AttributeError:
                messages.error(request, 'could not get OS-EXT-SRV-ATTR:host attribute of instance '+str(i.id)+' ('+str(i.name)+'); it will be ignored')
                continue

            # api.nova.flavor_list (which wraps novaclient.flavors.list) does not get all flavors,
            # so if we have a reference to one that hasn't been retrieved, try looking it up specifically
            # (wrap this rather trivially in a try block to make the error less cryptic)
            if i.flavor['id'] not in flavs:
                try:
                    flavs[i.flavor['id']] = api.nova.flavor_get(request, i.flavor['id'])
                    LOG.debug('Extra lookup for flavor "'+str(i.flavor['id'])+'"')
                except NotFound as e:
                    messages.error(request, 'Instance '+i.id+' has unknown flavor, so will be ignored.')
                    continue

            # maybe the same thing could happen for projects (haven't actually experienced this one though)
            if i.tenant_id not in projects:
                try:
                    projects[i.tenant_id] = api.keystone.tenant_get(request, i.tenant_id)
                    LOG.debug('Extra lookup for project "'+str(i.tenant_id)+'"')
                except NotFound as e:
                    messages.error(request, 'Instance '+i.id+' has unknown project, so will be ignored.')
                    continue

            # extract flavor data
            flav = flavs[i.flavor['id']]
            try:
                ephemeral = getattr(flav, 'OS-FLV-EXT-DATA:ephemeral')
            except AttributeError:
                messages.error(request, 'could not get OS-FLV-EXT-DATA:ephemeral attribute of flavor '+str(flav.id)+' ('+str(flav.name)+'); associated instance will be ignored')
                continue

            # everything's sane, so set some fields for the template to use
            def format_bytes(b): # formatter for bytes
                p, s = binary_prefix_scale(b)
                return '{scaled:.0f} {prefix}B'.format(scaled=b*s, prefix=p)
            i.project = projects[i.tenant_id]
            i.created = parse_date(i.created)
            i.flavor_name = flav.name
            i.flavor_vcpus = float(flav.vcpus)
            i.flavor_memory_bytes = float(flav.ram) * 1024**2
            i.flavor_disk_bytes = (float(flav.disk) + float(ephemeral)) * 1024**3
            i.flavor_description = '{vcpus} / {memory} / {disk}'.format(
                vcpus  = flav.vcpus,
                memory = format_bytes(i.flavor_memory_bytes),
                disk   = format_bytes(i.flavor_disk_bytes)
            )

            # keep a running list of which instances belong to which hypervisors
            if host not in hypervisor_instances: hypervisor_instances[host] = []
            hypervisor_instances[host].append(i)

        for h in hypervisors:
            h.host = h.service['host']
            h.short_name = short_name(h.host)
            h.servers = hypervisor_instances[h.host] if h.host in hypervisor_instances else []

            # figure out which host aggregate contains this host
            for (ha, agg) in zip(host_aggregates, aggregates):
                if h.host in agg.hosts:
                    ha['hypervisors'].append(h)

            # convert number of vcpus used (n)ow, and (t)otal available, to float for arithmetic later on
            ncpu, tcpu = float(h.vcpus_used),     float(h.vcpus)
            nmem, tmem = float(h.memory_mb_used)*1024**2, float(h.memory_mb)*1024**2
            ndis, tdis = float(h.local_gb_used)*1024**3,  float(h.local_gb)*1024**3
            lcpu, lmem, ldis = ncpu/tcpu, nmem/tmem, ndis/tdis

            if h.state == 'up':
                # colour based on load of most-utilised resource
                load = max(lcpu, lmem, ldis)
                hue0, hue1 = 1/3., 0 # green, red hard-coded because that's how i roll
                hue = hue0 + min(load,1)*(hue1-hue0) # lerp
                r, g, b = hsv_to_rgb(hue, 0.85, 0.9)
                r, g, b = ('0123456789abcdef'[int(15*x+0.5)] for x in (r,g,b))
                h.color = '#{0}{1}{2}'.format(r, g, b)
            else:
                h.color = '#999'
            h.cpuu, h.memu, h.disku = [resbar_width * x for x in [lcpu, lmem, ldis]]
            h.cpuf, h.memf, h.diskf = [resbar_width - x for x in [h.cpuu, h.memu, h.disku]]

            # summary for flavor: round values to int and use binary prefixes
            # also set statussymbol
            status_symbols = { # see http://docs.openstack.org/developer/nova/v2/2.0_server_concepts.html
                'ACTIVE'    :  '',
                'SHUTOFF'   :  '&darr;',
                'ERROR'     :  '&#x2715;', # this is a big cross X
            }
            for s in h.servers:
                mem_prefix,  mem_scale  = binary_prefix_scale(tmem*1024**2)
                disk_prefix, disk_scale = binary_prefix_scale(tdis*1024**3)
                s.statussymbol = status_symbols[s.status] if s.status in status_symbols else '?'
                s.cpuu  = resbar_width * s.flavor_vcpus / tcpu
                s.memu  = resbar_width * s.flavor_memory_bytes / tmem
                s.disku = resbar_width * s.flavor_disk_bytes / tdis
            # count resources used by host but not allocated to any instance
            h.cpuu  = resbar_width * (ncpu - sum(s.flavor_vcpus for s in h.servers))/tcpu
            h.memu  = resbar_width * (nmem - sum(s.flavor_memory_bytes for s in h.servers))/tmem
            h.disku = resbar_width * (ndis - sum(s.flavor_disk_bytes for s in h.servers))/tdis

            # usage strings for cpu/mem/disk
            h.cpu_usage  = '{n} / {t}'.format(n=h.vcpus_used, t=h.vcpus)
            h.mem_usage  = usage_string(nmem, h.memory_mb*1024**2)
            h.disk_usage = usage_string(ndis, h.local_gb*1024**3)

            # are resources overcommitted?
            h.cpu_overcommit  = 'overcommitted' if ncpu > tcpu else ''
            h.mem_overcommit  = 'overcommitted' if nmem > tmem else ''
            h.disk_overcommit = 'overcommitted' if ndis > tdis else ''

        # sort lists of hypervisors in host aggregates
        for ha in host_aggregates:
            ha['hypervisors'] = sorted(ha['hypervisors'], lambda hyp: hyp.short_name)

        context['host_aggregates'] = host_aggregates
        context['used_count'] = sum(1 for h in hypervisors if h.servers)
        context['server_count'] = sum(len(h.servers) for h in hypervisors)
        return context

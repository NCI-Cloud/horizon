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

from horizon import views
from openstack_dashboard import api
from iso8601 import parse_date
from colorsys import hsv_to_rgb
import re

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
        if n > 1: return '{:.0f}'.format(n)
        if n > 0: return '{:.1f}'.format(n)
        return '0'
    return '{n} / {t} {p}B'.format(n=pretty(now), t=pretty(tot), p=prefix)

class IndexView(views.APIView):
    template_name = 'admin/hvlist/index.html'

    def get_data(self, request, context, *args, **kwargs):
        # grab all the data
        hypervisors = api.nova.hypervisor_list(request)
        instances, _ = api.nova.server_list(request, all_tenants=True)
        projects, _ = api.keystone.tenant_list(request)
        flavs = api.nova.flavor_list(request)

        # reorganise some
        projects = {p.id : p for p in projects}
        flavs = {f.id : f for f in flavs}
        hypervisor_instances = {} # OS-EXT-SRV-ATTR:host : [instance]
        for i in instances:
            host = getattr(i, 'OS-EXT-SRV-ATTR:host')
            if host not in hypervisor_instances: hypervisor_instances[host] = []
            i.flav = flavs[i.flavor['id']]
            i.project = projects[i.tenant_id]
            i.created = parse_date(i.created)
            hypervisor_instances[host].append(i)

        resbar_width = 8 # em
        for h in hypervisors:
            h.host = getattr(h, h.NAME_ATTR)
            h.short_name = short_name(h.host)
            h.servers = hypervisor_instances[h.host] if h.host in hypervisor_instances else []

            ncpu, tcpu = float(h.vcpus_used),     float(h.vcpus)
            nmem, tmem = float(h.memory_mb_used), float(h.memory_mb)
            ndis, tdis = float(h.local_gb_used),  float(h.local_gb)
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
                s.flav.description = '{cpu}/{mem}/{disk}'.format(
                    cpu  = s.flav.vcpus,
                    mem  = int(s.flav.ram*1024**2*mem_scale+0.5),
                    disk = int(s.flav.disk*1024**3*disk_scale+0.5),
                )
                s.statussymbol = status_symbols[s.status] if s.status in status_symbols else '?'
                s.cpuu  = resbar_width * float(s.flav.vcpus) / tcpu
                s.memu  = resbar_width * float(s.flav.ram) / tmem
                s.disku = resbar_width * float(s.flav.disk) / tdis
            # count resources used by host but not allocated to any instance
            h.cpuu  = resbar_width * (ncpu - sum(s.flav.vcpus for s in h.servers))/tcpu
            h.memu  = resbar_width * (nmem - sum(s.flav.ram for s in h.servers))/tmem
            h.disku = resbar_width * (ndis - sum(s.flav.disk for s in h.servers))/tdis

            # usage strings for cpu/mem/disk
            h.cpu_usage  = '{n} / {t}'.format(n=h.vcpus_used, t=h.vcpus)
            h.mem_usage  = usage_string(h.memory_mb_used*1024**2, h.memory_mb*1024**2)
            h.disk_usage = usage_string(h.local_gb_used*1024**3, h.local_gb*1024**3)


        context['hypervisors'] = hypervisors
        context['used_count'] = sum(1 for h in hypervisors if h.servers)
        context['server_count'] = sum(len(h.servers) for h in hypervisors)
        context['cluster_name'] = 'Devstack'
        return context

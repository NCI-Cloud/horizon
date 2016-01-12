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

def hypervisor_status_symbol(h):
    return hypervisor_status_symbol.symbols[h.status] if h.status in hypervisor_status_symbol.symbols else '?'
hypervisor_status_symbol.symbols = { # see http://docs.openstack.org/developer/nova/v2/2.0_server_concepts.html
    'ACTIVE'    :  '',
    'SHUTOFF'   :  '&darr;',
    'ERROR'     :  '&#x2715;', # this is a big cross X
}

def short_name(hostname):
    """If the given hostname matches the pattern specified below, return a
    substring of the hostname (the group from the pattern match)."""
    m = short_name.p.match(hostname)
    if m:
        return m.group('n')
    return hostname
short_name.p = re.compile(r'^tc(?P<n>\d+)$')

def binary_prefix_scale(b):
    """Return (prefix, scale) so that (b) B = (b*scale) (prefix)B.
    For example, binary_prefix_scale(1536) == ('Ki', 1024**-1)."""
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

def hypervisor_color(cpu_utilisation, memory_utilisation, disk_utilisation):
    """Return 12-bit hexadecimal color string (e.g. "#d37") for hypervisor with
    the given cpu, memory and disk utilisations. (These are floating-point
    values between 0 and 1.)

    This implementation uses linear interpolation in hsv space between green
    and red, based on the highest of the three resource utilisations.
    """
    load = max(cpu_utilisation, memory_utilisation, disk_utilisation)
    hue0, hue1 = 1/3., 0 # green, red hard-coded because that's how i roll
    hue = hue0 + min(load,1)*(hue1-hue0) # lerp
    r, g, b = hsv_to_rgb(hue, 0.85, 0.9)
    r, g, b = ('0123456789abcdef'[int(15*x+0.5)] for x in (r,g,b))
    return '#{0}{1}{2}'.format(r, g, b)

def get_overcommit_ratios(confpath='/etc/nova/nova.conf'):
    """Extract and return {cpu,ram,disk}_allocation_ratio values from the given
    conf file. If any value is not found, 1 will be returned for it. The
    return value is a dict, e.g. {'cpu':1.0, 'ram':1.5, 'disk':1.0}.

    The result is saved, so the conf file should only be read once. This means
    that if the conf file changes, this module will need to be reloaded.

    This is not meant to be particularly robust; it is inherently hacky. There
    is apparently no way to get these values properly from the api.
    """
    resources = ['cpu', 'ram', 'disk'] # as they appear in nova.conf
    if not hasattr(get_overcommit_ratios, 'ratios'):
        rs = {}
        p = re.compile(r'^[^#]*(?P<resource>' + '|'.join(resources) + r')_allocation_ratio\s*=\s*(?P<value>[^\s]+)')
        try:
            with open(confpath, 'r') as f:
                for l in f.read().split('\n'):
                    m = p.search(l)
                    if m:
                        try:
                            rs[m.group('resource')] = float(m.group('value'))
                        except ValueError:
                            # forget any previous value, since it was overwritten by something unintelligible
                            del rs[m.group('resource')]
                            continue
        except IOError as ex:
            LOG.debug('Error reading {}: {}'.format(confpath, ex))
        for r in resources:
            if r not in rs:
                rs[r] = 1. # make sure everything is defined, though maybe this should cause a warning
        get_overcommit_ratios.ratios = rs
    return get_overcommit_ratios.ratios

class IndexView(views.APIView):
    template_name = 'admin/hvlist/index.html'

    def get_data(self, request, context, *args, **kwargs):
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

            # maintain lists of which instances belong to which hypervisors
            if host not in hypervisor_instances: hypervisor_instances[host] = []
            hypervisor_instances[host].append(i)

        # get overcommit values
        oc = get_overcommit_ratios()
        p = re.compile(r'^(?P<resource>cpu|ram|disk)_allocation_ratio$')
        for (a, h) in zip(aggregates, host_aggregates):
            h['overcommit'] = {k:oc[k] for k in oc} # copy default overcommit values
            for k in a.metadata:
                m = p.match(k)
                if m:
                    try:
                        h['overcommit'][m.group('resource')] = float(a.metadata[k])
                    except ValueError:
                        LOG.debug('Could not parse host aggregate "{key}" metadata value "{value}" as float.'.format(key=k, value=a.metadata[k]))
                        continue
            h['pretty_overcommit'] = '{cpu} / {ram} / {disk}'.format(**h['overcommit'])

        # assign hosts to host aggregates
        for h in hypervisors:
            for (ha, agg) in zip(host_aggregates, aggregates):
                if h.service['host'] in agg.hosts:
                    ha['hypervisors'].append(h)

        for ha in host_aggregates:
            for h in ha['hypervisors']:
                h.host = h.service['host']
                h.short_name = short_name(h.host)
                h.instances = hypervisor_instances[h.host] if h.host in hypervisor_instances else []


                # convert number of vcpus used (n)ow, and (t)otal available, to float, for arithmetic later on
                vcpus_used,        total_vcpus        = float(h.vcpus_used),             float(h.vcpus)             * ha['overcommit']['cpu']
                memory_bytes_used, total_memory_bytes = float(h.memory_mb_used)*1024**2, float(h.memory_mb)*1024**2 * ha['overcommit']['ram']
                disk_bytes_used,   total_disk_bytes   = float(h.local_gb_used)*1024**3,  float(h.local_gb)*1024**3  * ha['overcommit']['disk']

                # save these values for scaling visual elements later on...
                h.max_vcpus = max(vcpus_used, total_vcpus)
                h.max_memory_bytes = max(memory_bytes_used, total_memory_bytes)
                h.max_disk_bytes = max(disk_bytes_used, total_disk_bytes)

                # colour hypervisors that are up
                h.color = hypervisor_color(vcpus_used/total_vcpus, memory_bytes_used/total_memory_bytes, disk_bytes_used/total_disk_bytes) if h.state == 'up' else '#999'

                # calculate how much of the hypervisor's resources each instance is using
                for i in h.instances:
                    i.status_symbol = hypervisor_status_symbol(i)
                    i.cpuu  = i.flavor_vcpus
                    i.memu  = i.flavor_memory_bytes
                    i.disku = i.flavor_disk_bytes

                # count resources used by host but not allocated to any instance
                h.cpuu  = (vcpus_used - sum(i.flavor_vcpus for i in h.instances))
                h.memu  = (memory_bytes_used - sum(i.flavor_memory_bytes for i in h.instances))
                h.disku = (disk_bytes_used - sum(i.flavor_disk_bytes for i in h.instances))

                # usage strings for cpu/mem/disk
                h.cpu_usage  = '{n:d} / {t:.2g}'.format(n=int(vcpus_used), t=total_vcpus)
                h.mem_usage  = usage_string(memory_bytes_used, total_memory_bytes)
                h.disk_usage = usage_string(disk_bytes_used, total_disk_bytes)

                # are resources overcommitted?
                h.cpu_overcommit  = 'overcommitted' if vcpus_used > total_vcpus else ''
                h.mem_overcommit  = 'overcommitted' if memory_bytes_used > total_memory_bytes else ''
                h.disk_overcommit = 'overcommitted' if disk_bytes_used > total_disk_bytes else ''

            # sort lists of hypervisors in host aggregates
            ha['hypervisors'] = sorted(ha['hypervisors'], lambda hyp: hyp.short_name)

        # scale by 100 everything that will be rendered as a percentage...
        # this would be better in a custom template tag, but here is a link
        # to the documentation I could find about how to do that in horizon:
        resbar_width = 100
        for h in hypervisors:
            h.cpuu  *= resbar_width / h.max_vcpus
            h.memu  *= resbar_width / h.max_memory_bytes
            h.disku *= resbar_width / h.max_disk_bytes
            for i in h.instances:
                i.cpuu  *= resbar_width / h.max_vcpus
                i.memu  *= resbar_width / h.max_memory_bytes
                i.disku *= resbar_width / h.max_disk_bytes

        context['total_hypervisors'] = len(hypervisors)
        context['host_aggregates'] = host_aggregates
        context['used_count'] = sum(1 for h in hypervisors if h.instances)
        context['instance_count'] = sum(len(h.instances) for h in hypervisors)
        return context

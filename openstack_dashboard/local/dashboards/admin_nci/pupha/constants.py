# openstack_dashboard.local.dashboards.admin_nci.pupha.constants
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
from django.utils.translation import ugettext_lazy as _

TEMPLATE_NAME = 'admin/pupha/index.html'
TABLES_TEMPLATE_NAME = 'admin/pupha/tables.html'
SUMMARY_TEMPLATE_NAME = 'horizon/common/_detail_table.html'
TITLE = _('Host Aggregate Details')

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

def format_bytes(b, precision=0):
    p, s = binary_prefix_scale(float(b))
    format_str = '{{scaled:.{}f}} {{prefix}}B'.format(max(0, int(precision)))
    return format_str.format(scaled=b*s, prefix=p)

def su(vcpus, memory_mb, precision=1):
    return ('{:.'+str(max(0, int(precision)))+'f}').format(max(vcpus, memory_mb/su.memory_mb))
su.memory_mb = 4096. # how much memory per vcpu

def short_name(hostname):
    """
    If the given hostname matches the pattern specified below, return a
    substring of the hostname (the group from the pattern match).

    This is useful for two things:
      - making output more concise, by removal of common substring
      - data matching, e.g. "tc0123" and "tc0123.ncmgmt" refer to same entity
    
    """
    m = short_name.p.match(hostname)
    if m:
        return m.group('n')
    return hostname
short_name.p = re.compile(r'^(?P<n>tc\d+)(\.ncmgmt)?$')

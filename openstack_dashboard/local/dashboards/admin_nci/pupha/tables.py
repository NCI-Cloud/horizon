# openstack_dashboard.local.dashboards.admin_nci.pupha.tables
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

from horizon import tables
from django.utils.translation import ugettext_lazy as _
from .constants import format_bytes, su

class ProjectUsageTable(tables.DataTable):
    #id = tables.Column(lambda pu: pu.project.id, hidden=True)
    name = tables.Column(lambda pu: pu.project.name, verbose_name=_('Name'))
    desc = tables.Column(lambda pu: pu.project.description, verbose_name=_('Description'))
    vcpu = tables.Column('vcpus', verbose_name=_('VCPU'), summation='sum')
    ram  = tables.Column(
        'memory_mb',
        verbose_name = _('RAM'),
        filters      = [lambda mb: format_bytes(mb*1024*1024)],
        summation    = 'sum')
    sus  = tables.Column(
        lambda pu: float(su(pu.vcpus, pu.memory_mb)), # without float cast, summation doesn't work (but with float cast, we could potentially lose nice formatting)
        verbose_name = _('SU'),
        help_text    = u'1 SU \u223c 1 VCPU \u00d7 {} RAM'.format(format_bytes(su.memory_mb*1024*1024)), # \u223c is tilde operator; \u00d7 is times operator
        summation    = 'sum')

    class Meta(object):
        #table_actions = (ServiceFilterAction,)
        hidden_title = False

class Format(object):
    """Helpers for consistent formatting across tables."""
    precision = 1
    precision_f = '{{:.{}f}}'.format(precision)
    overcommit = u'\u00d7 {{factor:.{}f}} = {{total}}'.format(precision)

    @staticmethod
    def mb(mb):
        return format_bytes(mb*1024*1024, precision=Format.precision)

class SummaryTable(tables.DataTable):
    name   = tables.Column('name')
    vcpu   = tables.Column('vcpus', verbose_name=_('VCPU'))
    vcpu_o = tables.Column(
        lambda o: (o.vcpu_o, o.vcpus),
        verbose_name=_('overcommit'),
        filters=[lambda (overcommit, vcpus): Format.overcommit.format(factor=overcommit, total=Format.precision_f.format(overcommit*vcpus))]
    )
    vcpu_u = tables.Column('vcpus_used', verbose_name=_('allocated'))
    vcpu_f = tables.Column(
        lambda o: (o.vcpu_o, o.vcpus, o.vcpus_used),
        verbose_name = _('free'),
        filters      = [lambda (overcommit, vcpus, used): Format.precision_f.format(overcommit*vcpus-used)],
    )
    ram    = tables.Column(
        'memory_mb',
        verbose_name = _('RAM'),
        filters      = [Format.mb]
    )
    ram_o  = tables.Column(
        lambda o: (o.memory_mb_o, o.memory_mb),
        verbose_name=_('overcommit'),
        filters = [ # (these are applied in the order written, with output(n)=input(n+1)
            lambda (o, m):  (o, Format.mb(m)),
            lambda (o, fm): Format.overcommit.format(factor=o, total=fm),
        ]
    )
    ram_u  = tables.Column(
        'memory_mb_used',
        verbose_name = _('allocated'),
        filters      = [Format.mb]
    )
    ram_f = tables.Column(
        lambda o: (o.memory_mb_o, o.memory_mb, o.memory_mb_used),
        verbose_name = _('free'),
        filters      = [
            lambda (overcommit, mb, used): overcommit*mb-used,
            Format.mb,
        ]
    )
    class Meta(object):
        name = 'summary'

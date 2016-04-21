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
from .constants import format_bytes, su, short_name
from django.utils.safestring import mark_safe
from django.core import urlresolvers

class Format(object):
    """
    Helpers for various formatting-related operations.

    These may be candidates for conversion to Django filter functions, for
    better separation of logic and rendering code.
    """
    precision = 1
    precision_f = '{{:.{}f}}'.format(precision)
    overcommit = u'\u00d7 {{factor:.{}f}} = {{total}}'.format(precision)

    @staticmethod
    def mb(mb, precision=precision):
        return format_bytes(mb*1024*1024, precision=precision)

    @staticmethod
    def gb(gb, precision=precision):
        return format_bytes(gb*1024*1024*1024, precision=precision)

    @staticmethod
    def progress_bar(u, t, label='&nbsp;'):
        """Return html for progress bar showing u/t (used/total)."""
        return '<span class="bar"><span class="fill" style="width:{percent}%">{label}</span></span>'.format(used=u, total=t, percent=100*float(u)/t, label=label)

    @staticmethod
    def instances_list(instances):
        """
        Return unordered list markup for list of instance names with hyperlinks
        to instance detail pages.
        """
        return '<ul>'+''.join(
            '<li><a href="{link}">{name}</a></li>'.format(
                name=i.name,
                link=urlresolvers.reverse('horizon:admin:instances:detail', args=(i.id,)
            )
        ) for i in instances)+'</ul>'

    @staticmethod
    def hypervisor_color(load):
        """Return 12-bit hexadecimal color string (e.g. "#d37") for hypervisor with
        the given load, which is a floating-point value between 0 and 1.

        This implementation uses linear interpolation in hsv space between green
        and red.
        """
        from colorsys import hsv_to_rgb
        hue0, hue1 = 1/3., 0 # green, red hard-coded because that's how i roll
        hue = hue0 + min(load,1)*(hue1-hue0) # lerp
        r, g, b = hsv_to_rgb(hue, 0.85, 0.9)
        r, g, b = ('0123456789abcdef'[int(15*x+0.5)] for x in (r,g,b))
        return '#{0}{1}{2}'.format(r, g, b)

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

class ProjectUsageTable(tables.DataTable):
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
        hidden_title = False

class HypervisorTable(tables.DataTable):
    status_icon = tables.Column(
        lambda h: h._meta.usage,
        verbose_name = '', # no title for this column
        filters = [
            Format.hypervisor_color,
            lambda col: '<span style="background-color:{}">&nbsp;</span>'.format(col),
            mark_safe
        ],
        classes = ['usage']
    )
    name = tables.Column(
        lambda h: short_name(getattr(h, h.NAME_ATTR)),
        verbose_name = _('Name'),
    )
    status = tables.Column('status')
    state = tables.Column('state')
    vcpu = tables.Column(
        lambda h: (h.vcpus, h.vcpus_used, h._meta.overcommit['cpu']),
        verbose_name = _('VCPU'),
        filters = [
            lambda (t, u, o): Format.progress_bar(u, t*o, '{u} / {t}'.format(u=u, t=t*o)),
            mark_safe
        ],
    )
    ram = tables.Column(
        lambda h: (h.memory_mb, h.memory_mb_used, h._meta.overcommit['ram']),
        verbose_name = _('RAM'),
        filters = [
            lambda (t, u, o): Format.progress_bar(u, t*o, '{u} / {t}'.format(u=Format.mb(u, precision=0), t=Format.mb(t*o, precision=0))),
            mark_safe
        ],
    )
    disk = tables.Column(
        lambda h: (h.local_gb, h.local_gb_used, h._meta.overcommit['disk']),
        verbose_name = _('Local storage'),
        filters = [
            lambda (t, u, o): Format.progress_bar(u, t*o, '{u} / {t}'.format(u=Format.gb(u, precision=0), t=Format.gb(t*o, precision=0))),
            mark_safe
        ],
    )
    instances = tables.Column(
        lambda h: h.instances,
        verbose_name = _('Instances'),
        filters = [
            Format.instances_list, # could try to use django built-in "unordered_list" filter for this
            mark_safe,
        ],
    )

    class Meta(object):
        hidden_title = False

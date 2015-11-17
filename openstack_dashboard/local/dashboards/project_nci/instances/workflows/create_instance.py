# openstack_dashboard.local.dashboards.project_nci.instances.workflows.create_instance
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

import copy
import itertools
import json
import logging
import netaddr
import operator
import os.path
#import pdb ## DEBUG
import re
import socket
import time
import types

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from django.conf import settings
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.debug import sensitive_variables
from django.template.defaultfilters import filesizeformat

from horizon import exceptions
from horizon import forms
from horizon import messages
from horizon import workflows

from openstack_dashboard import api
from openstack_dashboard.dashboards.project.instances.workflows import create_instance as base_mod

from openstack_dashboard.local.nci import crypto as ncicrypto
from openstack_dashboard.local.nci import utils as nciutils
from openstack_dashboard.local.nci.constants import *


LOG = logging.getLogger(__name__)


class SetInstanceDetailsAction(base_mod.SetInstanceDetailsAction):
    Meta = nciutils.subclass_meta_type(base_mod.SetInstanceDetailsAction)

    def populate_image_id_choices(self, request, context):
        choices = super(SetInstanceDetailsAction, self).populate_image_id_choices(request, context)

        # Find the latest VL image for each unique series tag and add an
        # alias item to the top of the images list with a more friendly name
        # so that the user doesn't have to hunt through the entire list
        # looking for the correct image to use.
        self.vl_tags = {}
        for id, image in choices:
            if not id:
                continue

            parts = image.name.split("-")
            if parts[0] == "vl":
                if not image.is_public:
                    LOG.debug("Ignoring non-public VL image: {0}".format(image.name))
                    continue

                # VL images have the following name format:
                #   vl-<tag_base>[-<tag_variant>-...]-<timestamp>
                if len(parts) < 3:
                    LOG.warning("Invalid VL image name format: {0}".format(image.name))
                    continue

                tag = "-".join(parts[1:-1])

                if re.match(r"2[0-9]{7}", parts[-1]):
                    image._vl_ts = parts[-1]
                else:
                    LOG.warning("Invalid or missing timestamp in VL image name: {0}".format(image.name))
                    continue

                if (tag not in self.vl_tags) or (image._vl_ts > self.vl_tags[tag]._vl_ts):
                    self.vl_tags[tag] = image
            else:
                image.name += " [non-VL]"

        def clone_image(tag):
            if "-" in tag:
                (base, variant) = tag.split("-", 1)
            else:
                base = tag
                variant = ""

            if base.startswith("centos"):
                title = "CentOS"
                base = base[6:]
            elif base.startswith("ubuntu"):
                title = "Ubuntu"
                base = base[6:]
            else:
                title = tag
                base = ""
                variant = ""

            if base:
                title += " " + base

            if variant:
                title += " " + variant

            image = copy.copy(self.vl_tags[tag])
            image._real_id = image.id
            image.id = "vltag:" + tag
            image.name = title
            self.vl_tags[tag] = image

            return image

        if self.vl_tags:
            choices.insert(1, ("---", "---------------"))
            for tag in reversed(sorted(self.vl_tags.keys())):
                image = clone_image(tag)
                choices.insert(1, (image.id, image))

        return choices

    def clean_name(self):
        if hasattr(super(SetInstanceDetailsAction, self), "clean_name"):
            val = super(SetInstanceDetailsAction, self).clean_name()
        else:
            val = self.cleaned_data.get("name")

        val = val.strip()
        if val and ("." in val):
            valid_fqdn = r"^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?$"
            if not re.search(valid_fqdn, val):
                msg = _("The specified FQDN doesn't satisfy the requirements of a valid DNS hostname.")
                raise forms.ValidationError(msg)

        return val

    def clean_image_id(self):
        if hasattr(super(SetInstanceDetailsAction, self), "clean_image_id"):
            val = super(SetInstanceDetailsAction, self).clean_image_id()
        else:
            val = self.cleaned_data.get("image_id")

        if val:
            if val == "---":
                val = ""
            elif val.startswith("vltag:"):
                # Convert the VL image tag back into the real image ID.
                tag = val[6:]
                if tag not in self.vl_tags:
                    msg = _("Image tag doesn't exist")
                    raise forms.ValidationError(msg)

                val = self.vl_tags[tag]._real_id

        return val

    def get_help_text(self):
        saved = self._images_cache
        try:
            # Add our VL image aliases to the image cache temporarily so
            # that they are included in the list passed to "initWithImages()"
            # in "horizon/static/horizon/js/horizon.quota.js" (via the
            # "_flavors_and_quotas.html" template).  The result will be
            # that any flavours which are too small will be disabled when
            # a given image alias is selected in the drop down.
            self._images_cache["public_images"].extend(self.vl_tags.values())
            return super(SetInstanceDetailsAction, self).get_help_text()
        finally:
            self._images_cache = saved


class SetInstanceDetails(base_mod.SetInstanceDetails):
    action_class = SetInstanceDetailsAction


class SetAccessControlsAction(base_mod.SetAccessControlsAction):
    Meta = nciutils.subclass_meta_type(base_mod.SetAccessControlsAction)

    def __init__(self, request, context, *args, **kwargs):
        super(SetAccessControlsAction, self).__init__(request, context, *args, **kwargs)
        # Remove the security groups field since they aren't functional on
        # our new cloud.
        del self.fields["groups"]

    def populate_groups_choices(self, request, context):
        return []


class SetAccessControls(base_mod.SetAccessControls):
    action_class = SetAccessControlsAction


class FixedIPMultiWidget(forms.MultiWidget):
    def __init__(self, choices, attrs=None):
        sub_widgets = (
            forms.Select(choices=choices, attrs=attrs),
            forms.TextInput(attrs=attrs),
        )
        super(FixedIPMultiWidget, self).__init__(sub_widgets, attrs)

    def has_choice(self, value):
        for x in self.widgets[0].choices:
            if isinstance(x[1], (list, tuple)):
                for y in x[1]:
                    if y[0] == value:
                        return True
            elif x[0] == value:
                return True

        return False

    def decompress(self, value):
        if value is not None:
            if self.has_choice(value):
                return [value, None]
            else:
                return ["manual", value]
        else:
            return [None, None]

    def value_from_datadict(self, data, files, name):
        v = super(FixedIPMultiWidget, self).value_from_datadict(data, files, name)
        if v[0] == "manual":
            return v[1].strip()
        else:
            return v[0]


# NB: We aren't subclassing the upstream implementation of this action.
class SetNetworkAction(workflows.Action):
    Meta = nciutils.subclass_meta_type(base_mod.SetNetworkAction)

    @staticmethod
    def user_has_ext_net_priv(request):
        return (request.user.is_superuser
            or request.user.has_perms([settings.NCI_EXTERNAL_NET_PERM]))

    def __init__(self, request, context, *args, **kwargs):
        super(SetNetworkAction, self).__init__(request, context, *args, **kwargs)

        # If the user has access to the external network then retrieve any
        # fixed public IP allocations defined for this tenant.
        all_fixed_pub_ips = netaddr.IPSet()
        self.fixed_pub_ips_pool = False
        if self.user_has_ext_net_priv(request):
            try:
                if request.user.project_name in settings.NCI_FIXED_PUBLIC_IPS:
                    for cidr in settings.NCI_FIXED_PUBLIC_IPS[request.user.project_name]:
                        if cidr == "pool":
                            self.fixed_pub_ips_pool = True
                        else:
                            all_fixed_pub_ips.add(netaddr.IPNetwork(cidr))
                elif request.user.project_name == "admin":
                    self.fixed_pub_ips_pool = True
            except (netaddr.AddrFormatError, ValueError) as e:
                LOG.exception("Error parsing fixed public IP list: {0}".format(e))
                messages.error(request, str(e))
                msg = _("Failed to load fixed public IP configuration.")
                messages.warning(request, msg)
                all_fixed_pub_ips = netaddr.IPSet()
                self.fixed_pub_ips_pool = False

        self.fixed_pub_ips_enabled = (bool(all_fixed_pub_ips) or self.fixed_pub_ips_pool)

        # Build the list of network choices.
        networks_list = self.get_networks(request)
        self.networks = dict([(x.id, x) for x in networks_list])

        network_choices = [(x.id, x.name) for x in sorted(networks_list, key=operator.attrgetter('name'))]
        network_choices.insert(0, ("", "-- Unassigned --"))

        # Build the fixed and floating IP choice lists.
        self.pub_ips = self.get_public_ips(request, all_fixed_pub_ips)

        fixed_ip_choices = [
            ("auto", "Automatic"),
            ("manual", "Manual"),
        ]

        if self.fixed_pub_ips_enabled:
            ext_fixed_ip_choices = [(str(x), str(x)) for x in self.pub_ips["fixed"]]
            if self.fixed_pub_ips_pool:
                ext_fixed_ip_choices.append(["ext_pool", "Global Allocation Pool"])

            grp_title = "External"
            if not ext_fixed_ip_choices:
                grp_title += " (none available)"

            fixed_ip_choices.append((grp_title, ext_fixed_ip_choices))
        else:
            ext_fixed_ip_choices = []

        floating_ip_choices = [(x.id, x.ip) for x in sorted(self.pub_ips["float"].itervalues(), key=lambda x: netaddr.IPAddress(x.ip))]
        floating_ip_choices.insert(0, ("", "-- None --"))

        # Create the form fields for each network interface.
        self.intf_limit = settings.NCI_VM_NETWORK_INTF_LIMIT
        if not settings.NCI_DUPLICATE_VM_NETWORK_INTF:
            self.intf_limit = max(1, min(self.intf_limit, len(networks_list)))

        for i in range(0, self.intf_limit):
            self.fields["eth{0:d}_network".format(i)] = forms.ChoiceField(
                label=_("Network"),
                required=(i == 0),
                choices=network_choices,
                initial="",
                help_text=_("The network that this interface should be attached to."))

            self.fields["eth{0:d}_fixed_ip".format(i)] = forms.CharField(
                widget=FixedIPMultiWidget(fixed_ip_choices),
                label=_("Fixed IP"),
                required=True,
                initial="auto",
                help_text=_("The fixed IP address to assign to this interface."))

            self.fields["eth{0:d}_floating_ip".format(i)] = forms.ChoiceField(
                label=_("Floating Public IP"),
                required=False,
                choices=floating_ip_choices,
                initial="",
                help_text=_("A floating IP address to associate with this interface."))

        # Select reasonable defaults if there is an obvious choice.  We only
        # consider external networks as an option if there aren't any floating
        # IPs available.
        external_net_ids = set([x for x, y in self.networks.iteritems() if y.get("router:external", False)])
        private_net_ids = set(self.networks.keys()) - external_net_ids

        default_priv_net = None
        if len(private_net_ids) == 1:
            default_priv_net = iter(private_net_ids).next()
        elif private_net_ids:
            # As a convention, when we setup a new tenant we create a network
            # with the same name as the tenant.
            search = [request.user.project_name]
            if request.user.project_name in ["admin", "z00"]:
                search.append("internal")
            matches = [x for x in private_net_ids if self.networks[x].name in search]
            if len(matches) == 1:
                default_priv_net = matches[0]

        if len(floating_ip_choices) > 1:
            if default_priv_net:
                self.fields["eth0_network"].initial = default_priv_net
                self.fields["eth0_floating_ip"].initial = floating_ip_choices[1][0]
        elif ext_fixed_ip_choices:
            if len(external_net_ids) == 1:
                self.fields["eth0_network"].initial = iter(external_net_ids).next()
                self.fields["eth0_fixed_ip"].initial = ext_fixed_ip_choices[0][0]
                if default_priv_net:
                    assert self.intf_limit > 1
                    self.fields["eth1_network"].initial = default_priv_net
        elif default_priv_net:
            self.fields["eth0_network"].initial = default_priv_net

        # A list of external network IDs is needed for the client side code.
        self.external_nets = ";".join(external_net_ids)

    def get_networks(self, request):
        networks = []
        try:
            networks = api.neutron.network_list_for_tenant(request, request.user.project_id)
        except:
            exceptions.handle(request)
            msg = _("Unable to retrieve available networks.")
            messages.warning(request, msg)

        if not self.fixed_pub_ips_enabled:
            LOG.debug("Excluding external networks")
            networks = filter(lambda x: not x.get("router:external", False), networks)

        # TODO: Workaround until we can unshare the "internal" network.
        if request.user.project_name not in ["admin", "z00"]:
            networks = filter(lambda x: x.get("router:external", False) or not x.shared, networks)

        any_ext_nets = False
        for net in networks:
            # Make sure the "name" attribute is defined.
            net.set_id_as_name_if_empty()
            any_ext_nets = any_ext_nets or net.get("router:external", False)

        if self.fixed_pub_ips_enabled and not any_ext_nets:
            LOG.debug("No external networks found - disabling fixed public IPs")
            self.fixed_pub_ips_enabled = False

        return networks

    def get_public_ips(self, request, all_fixed_pub_ips):
        ips = {}

        try:
            # Select any unassigned floating IPs.
            floats = api.network.tenant_floating_ip_list(request)
            ips["float"] = dict([(x.id, x) for x in floats if not x.port_id])

            if self.fixed_pub_ips_enabled and all_fixed_pub_ips:
                # Take note of all floating IPs (including assigned) since they
                # can't be used as a fixed IP given that a port already exists.
                used_ips = [x.ip for x in floats]

                # Locate any fixed IPs already assigned to an external network
                # port so that we can exclude them from the list.
                for net_id, net in self.networks.iteritems():
                    if not net.get("router:external", False):
                        continue

                    LOG.debug("Getting all ports for network: {0}".format(net_id))
                    ports = api.neutron.port_list(request,
                        tenant_id=request.user.project_id,
                        network_id=net_id)
                    for port in ports:
                        for fip in port.fixed_ips:
                            if fip.get("ip_address"):
                                used_ips.append(fip["ip_address"])

                # Select fixed IPs allocated to the tenant that aren't in use.
                ips["fixed"] = all_fixed_pub_ips - netaddr.IPSet(used_ips)
            else:
                ips["fixed"] = []
        except:
            exceptions.handle(request)
            msg = _("Failed to determine available public IPs.")
            messages.warning(request, msg)
            ips["float"] = {}
            ips["fixed"] = []

        return ips

    def clean(self):
        data = super(SetNetworkAction, self).clean()

        nics = []
        used_ips = {"_float_": set()}
        try:
            for i in range(0, self.intf_limit):
                nic = {}
                field_id = "eth{0:d}_network".format(i)
                net_id = data.get(field_id)
                if net_id:
                    used_ips.setdefault(net_id, set())
                    nic["network_id"] = net_id

                    if i != len(nics):
                        msg = _("Network interfaces must be assigned consecutively.")
                        self._errors[field_id] = self.error_class([msg])
                    elif (not settings.NCI_DUPLICATE_VM_NETWORK_INTF) and (net_id in [n["network_id"] for n in nics]):
                        msg = _("Network is assigned to another interface.")
                        self._errors[field_id] = self.error_class([msg])

                    # Field level validation will have already checked that the
                    # network ID exists by virtue of being a valid choice.
                    assert net_id in self.networks
                    external = self.networks[net_id].get("router:external", False)
                else:
                    external = False

                fixed_subnet_id = None
                field_id = "eth{0:d}_fixed_ip".format(i)
                fixed_ip = data.get(field_id)
                if not fixed_ip:
                    # Value could only be undefined if field level validation
                    # failed since "required=True" for this field.
                    assert self._errors.get(field_id)
                elif fixed_ip == "auto":
                    if external:
                        msg = _("Selected option is not valid on this network.")
                        self._errors[field_id] = self.error_class([msg])
                elif not net_id:
                    msg = _("No network selected.")
                    self._errors[field_id] = self.error_class([msg])
                elif fixed_ip == "ext_pool":
                    if external:
                        # Choice won't be available unless global allocation pool
                        # is enabled.
                        assert self.fixed_pub_ips_pool
                    else:
                        msg = _("Selected option is not available on this network.")
                        self._errors[field_id] = self.error_class([msg])
                else:
                    try:
                        fixed_ip = netaddr.IPAddress(fixed_ip)
                    except (netaddr.AddrFormatError, ValueError) as e:
                        msg = _("Not a valid IP address format.")
                        self._errors[field_id] = self.error_class([msg])
                    else:
                        if external:
                            assert self.fixed_pub_ips_enabled
                            if fixed_ip not in self.pub_ips["fixed"]:
                                msg = _("\"{0}\" is not available on this network.".format(fixed_ip))
                                self._errors[field_id] = self.error_class([msg])
                            elif fixed_ip in used_ips[net_id]:
                                msg = _("IP address is assigned to another interface.")
                                self._errors[field_id] = self.error_class([msg])
                            else:
                                nic["fixed_ip"] = fixed_ip
                                used_ips[net_id].add(fixed_ip)
                        else:
                            # Verify that there is a subnet for the selected network
                            # which contains the fixed IP address.
                            subnet_cidr = None
                            for subnet in self.networks[net_id].subnets:
                                subnet_cidr = netaddr.IPNetwork(subnet.cidr)
                                if fixed_ip in subnet_cidr:
                                    break
                                else:
                                    subnet_cidr = None

                            if not subnet_cidr:
                                msg = _("IP address must be in a subnet range for the selected network.")
                                self._errors[field_id] = self.error_class([msg])
                            elif fixed_ip == subnet_cidr.network:
                                msg = _("Network address is reserved.")
                                self._errors[field_id] = self.error_class([msg])
                            elif fixed_ip == subnet_cidr.broadcast:
                                msg = _("Broadcast address is reserved.")
                                self._errors[field_id] = self.error_class([msg])
                            elif subnet.get("gateway_ip") and (fixed_ip == netaddr.IPAddress(subnet.gateway_ip)):
                                msg = _("IP address is reserved for the subnet gateway.")
                                self._errors[field_id] = self.error_class([msg])
                            else:
                                fixed_subnet_id = subnet.id

                                # Is the IP address already assigned to a port on
                                # this network?
                                LOG.debug("Getting all ports for network: {0}".format(net_id))
                                ports = api.neutron.port_list(self.request,
                                    tenant_id=self.request.user.project_id,
                                    network_id=net_id)
                                found = False
                                for port in ports:
                                    for fip in port.fixed_ips:
                                        if fip.get("ip_address") and (fixed_ip == netaddr.IPAddress(fip["ip_address"])):
                                            found = True
                                            break

                                if found:
                                    msg = _("IP address is already in use.")
                                    self._errors[field_id] = self.error_class([msg])
                                elif fixed_ip in used_ips[net_id]:
                                    msg = _("IP address is assigned to another interface.")
                                    self._errors[field_id] = self.error_class([msg])
                                else:
                                    nic["fixed_ip"] = fixed_ip
                                    used_ips[net_id].add(fixed_ip)

                field_id = "eth{0:d}_floating_ip".format(i)
                floating_ip = data.get(field_id)
                if floating_ip:
                    assert floating_ip in self.pub_ips["float"]
                    if not net_id:
                        msg = _("No network selected.")
                        self._errors[field_id] = self.error_class([msg])
                    elif external:
                        msg = _("Floating IPs cannot be used on an external network.")
                        self._errors[field_id] = self.error_class([msg])
                    elif floating_ip in used_ips["_float_"]:
                        msg = _("IP address is assigned to another interface.")
                        self._errors[field_id] = self.error_class([msg])
                    else:
                        float_net_id = self.pub_ips["float"][floating_ip].floating_network_id
                        LOG.debug("Looking for a route between the networks {0} and {1}".format(net_id, float_net_id))
                        ports = api.neutron.port_list(self.request,
                            network_id=net_id,
                            device_owner="network:router_interface")
                        found = False
                        for port in ports:
                            if fixed_subnet_id and (fixed_subnet_id not in [x.get("subnet_id") for x in port.fixed_ips]):
                                LOG.debug("Ignoring port {0} due to subnet mismatch".format(port.id))
                                continue

                            router = api.neutron.router_get(self.request, port.device_id)
                            if router.get("external_gateway_info", {}).get("network_id") == float_net_id:
                                LOG.debug("Found path to floating IP network via router: {0}".format(router.id))
                                found = True
                                break

                        if not found:
                            if self.networks[net_id].shared:
                                # The Neutron API doesn't return interface ports for routers
                                # owned by another tenant, even if that network is shared
                                # with us.  So we just have to accept the user's request.
                                LOG.warning("Unable to locate router for floating IP on shared network: {0}".format(net_id))
                            else:
                                msg = _("No router interface found that connects the selected network with the floating IP.")
                                self._errors[field_id] = self.error_class([msg])
                        else:
                            nic["floating_ip"] = floating_ip
                            used_ips["_float_"].add(floating_ip)

                if "network_id" in nic:
                    nics.append(nic)
        except:
            exceptions.handle(self.request)
            msg = _("Validation failed with an unexpected error.")
            raise forms.ValidationError(msg)

        if not nics:
            msg = _("At least one network interface must be assigned.")
            raise forms.ValidationError(msg)

        if settings.NCI_DUPLICATE_VM_NETWORK_INTF:
            # See "server_create_hook_func()" for why this check is made.
            float_nets = set([n["network_id"] for n in nics if "floating_ip" in n])
            for net_id in float_nets:
                if len(filter(lambda x: x["network_id"] == net_id, nics)) > 1:
                    msg = _("Networks with a floating IP specified can only be assigned to one interface.")
                    raise forms.ValidationError(msg)

        data["nics"] = nics
        return data


# NB: We aren't subclassing the upstream implementation of this step.
class SetNetwork(workflows.Step):
    action_class = SetNetworkAction
    contributes = ("nics", "network_id")
    template_name = "project/instances/../instances_nci/_update_networks.html"

    def contribute(self, data, context):
        context = super(SetNetwork, self).contribute(data, context)

        if context["nics"]:
            # Emulate the network list set in the upstream implementation.
            context["network_id"] = [n["network_id"] for n in context["nics"]]

        return context


class BootstrapConfigAction(workflows.Action):
    puppet_action = forms.ChoiceField(
        label=_("Puppet Action"),
        required=True,
        choices=[x for x in PUPPET_ACTION_CHOICES if x[0] == "none"],
        initial="none",
        help_text=_("Puppet command to execute."))

    puppet_env = forms.RegexField(
        label=_("Puppet Environment"),
        required=False,
        regex=REPO_BRANCH_REGEX,
        help_text=_("Puppet configuration environment (or equivalent branch name) to deploy."))

    install_updates = forms.ChoiceField(
        label=_("Install Updates"),
        required=True,
        choices=[
            ("reboot", _("Yes (reboot if required)")),
            ("yes", _("Yes (don't reboot)")),
            ("no", _("No")),
        ],
        initial="reboot",
        help_text=_("Whether to install system updates.  (Recommended)"))

    class Meta(object):
        name = _("Initial Boot")
        help_text_template = ("project/instances/../instances_nci/_bootstrap_help.html")

    def __init__(self, request, context, *args, **kwargs):
        super(BootstrapConfigAction, self).__init__(request, context, *args, **kwargs)

        # Check if the project's VL config exists.  We only assign a default
        # Puppet action if it does.  This will allow projects not using the
        # VL environment to still be able to launch VMs without having to
        # change the Puppet action first.
        is_vl = False
        try:
            container = nci_private_container_name(request)
            config_obj_name = nci_vl_project_config_name()
            is_vl = api.swift.swift_object_exists(request,
                container,
                config_obj_name)
        except:
            exceptions.handle(request)

        if is_vl:
            obj = None
            try:
                obj = api.swift.swift_get_object(request,
                    container,
                    config_obj_name,
                    resp_chunk_size=None)
            except:
                exceptions.handle(request)
                msg = _("VL project configuration not found.")
                messages.warning(request, msg)

            if obj:
                project_cfg = None
                try:
                    project_cfg = json.loads(obj.data)
                except ValueError as e:
                    LOG.exception("Error parsing project configuration: {0}".format(e))
                    messages.error(request, str(e))
                    msg = _("VL project configuration is corrupt.")
                    messages.warning(request, msg)

                if project_cfg:
                    self.fields["puppet_env"].initial = project_cfg.get("puppet_env", "")
                    if project_cfg.get("repo_key") and project_cfg.get("eyaml_key") and project_cfg.get("eyaml_cert"):
                        self.fields["puppet_action"].choices = PUPPET_ACTION_CHOICES
                        self.fields["puppet_action"].initial = "apply"

                    default_action = project_cfg.get("puppet_action", "auto")
                    if default_action != "auto":
                        avail_actions = [x[0] for x in self.fields["puppet_action"].choices]
                        if default_action in avail_actions:
                            self.fields["puppet_action"].initial = default_action


    def clean(self):
        data = super(BootstrapConfigAction, self).clean()

        if (data.get("puppet_action", "none") != "none") and not data.get("puppet_env"):
            msg = _("An environment name is required for the selected Puppet action.")
            raise forms.ValidationError(msg)

        return data


class BootstrapConfig(workflows.Step):
    action_class = BootstrapConfigAction
    contributes = ("puppet_action", "puppet_env", "install_updates")
    template_name = "project/instances/../instances_nci/_bootstrap_step.html"


def server_create_hook_func(request, context, floats):
    def _impl(*args, **kwargs):
        float_nets = {}
        kwargs["nics"] = []
        nics = context["nics"] or []
        for n in nics:
            # https://github.com/openstack/python-novaclient/blob/2.20.0/novaclient/v1_1/servers.py#L528
            nic = {"net-id": n["network_id"]}
            ip = n.get("fixed_ip")
            if ip:
                if ip.version == 6:
                    nic["v6-fixed-ip"] = str(ip)
                else:
                    assert ip.version == 4
                    nic["v4-fixed-ip"] = str(ip)

            kwargs["nics"].append(nic)

            if "floating_ip" in n:
                assert n["network_id"] not in float_nets
                float_nets[n["network_id"]] = n["floating_ip"]

        srv = api.nova.server_create(*args, **kwargs)

        if float_nets:
            # Find the ports created for the new instance which we need to
            # associate each floating IP with.  We have to wait until the
            # ports are created by Neutron.  Note that the only unique
            # information we have to identify which port should be paired
            # with each floating IP is the network ID.  Hence we don't
            # support more than one interface connected to the same network
            # when floating IPs are specified.
            try:
                max_attempts = 15
                attempt = 0
                while attempt < max_attempts:
                    attempt += 1

                    LOG.debug("Fetching network ports for instance: {0}".format(srv.id))
                    ports = api.neutron.port_list(request, device_id=srv.id)
                    for p in ports:
                        LOG.debug("Found port: id={0}; owner={1}; network={2}".format(*[p.get(x) for x in ["id", "device_owner", "network_id"]]))
                        if p.get("device_owner", "").startswith("compute:") and (p.get("network_id") in float_nets):
                            for t in api.network.floating_ip_target_list_by_instance(request, srv.id):
                                LOG.debug("Got floating IP target: {0}".format(t))
                                if t.startswith(p.id):
                                    float_id = float_nets[p.network_id]
                                    api.network.floating_ip_associate(request, float_id, t)
                                    del float_nets[p.network_id]
                                    msg = _("Floating IP {0} associated with new instance.".format(floats[float_id].ip))
                                    messages.info(request, msg)
                                    break

                    if not float_nets:
                        # All floating IPs have now been assigned.
                        srv = api.nova.server_get(request, srv.id)
                        break

                    status = api.nova.server_get(request, srv.id).status.lower()
                    if status == "active":
                        if max_attempts != 2:
                            LOG.debug("VM state has become active")
                            max_attempts = 2
                            attempt = 0
                    elif status != "build":
                        LOG.debug("Aborting wait loop due to server status: {0}".format(status))
                        break

                    LOG.debug("Waiting for network port allocation")
                    time.sleep(2)
            except:
                exceptions.handle(request)

            for f in float_nets.itervalues():
                msg = _("Failed to associate floating IP {0} with new instance.".format(floats[f].ip))
                messages.warning(request, msg)

        return srv

    return _impl


def step_generator():
    for step in base_mod.LaunchInstance.default_steps:
        if step == base_mod.SetInstanceDetails:
            yield SetInstanceDetails
        elif step == base_mod.SetAccessControls:
            yield SetAccessControls
        elif step == base_mod.SetNetwork:
            yield SetNetwork
        elif step == base_mod.PostCreationStep:
            # Replace the "Post-Creation" tab with our bootstrap parameters.
            yield BootstrapConfig
        else:
            yield step


class NCILaunchInstance(base_mod.LaunchInstance):
    default_steps = [x for x in step_generator()]

    @sensitive_variables("context")
    def validate(self, context):
        if context["count"] > 1:
            keys = set(itertools.chain.from_iterable(context["nics"]))
            if filter(lambda k: k.endswith("_ip"), keys):
                msg = _("Multiple instances cannot be launched with the same IP address.")
                self.add_error_to_step(msg, SetNetworkAction.slug)
                # Missing from "add_error_to_step()"...
                self.get_step(SetNetworkAction.slug).has_errors = True
                return False

        return True

    @sensitive_variables("context")
    def handle(self, request, context):
        cloud_cfg = {}
        if context["puppet_action"] != "none":
            # Load the project's VL configuration.
            try:
                obj = api.swift.swift_get_object(request,
                    nci_private_container_name(request),
                    nci_vl_project_config_name(),
                    resp_chunk_size=None)
            except:
                exceptions.handle(request)
                msg = _("VL project configuration not found.")
                messages.error(request, msg)
                return False

            try:
                project_cfg = json.loads(obj.data)
            except ValueError as e:
                LOG.exception("Error parsing project configuration: {0}".format(e))
                messages.error(request, str(e))
                msg = _("VL project configuration is corrupt.")
                messages.error(request, msg)
                return False

            # Add the cloud-config parameters for the "nci.puppet" module.
            puppet_cfg = cloud_cfg.setdefault("nci", {}).setdefault("puppet", {})
            puppet_cfg["action"] = context["puppet_action"]
            puppet_cfg["environment"] = context["puppet_env"]

            repo_cfg = puppet_cfg.setdefault("repo", {})
            repo_cfg["path"] = project_cfg.get("repo_path", "")

            eyaml_cfg = puppet_cfg.setdefault("eyaml", {})

            try:
                msg = _("Failed to initialise crypto stash.")
                stash = ncicrypto.CryptoStash(request,
                    project_cfg.get("stash") or {})

                msg = _("Failed to load deployment key.")
                key = stash.load_private_key(project_cfg.get("repo_key"))
                repo_cfg["key"] = key.cloud_config_dict()

                msg = _("Failed to load eyaml key.")
                key = stash.load_private_key(project_cfg.get("eyaml_key"))
                eyaml_cfg["key"] = key.cloud_config_dict()

                msg = _("Failed to load eyaml certificate.")
                cert = stash.load_x509_cert(project_cfg.get("eyaml_cert"))
                eyaml_cfg["cert"] = cert.cloud_config_dict()
            except:
                exceptions.handle(request)
                messages.error(request, msg)
                return False

        cloud_cfg["package_upgrade"] = (context["install_updates"] != "no")
        cloud_cfg["package_reboot_if_required"] = (context["install_updates"] == "reboot")

        if "." in context["name"]:
            cloud_cfg["fqdn"] = context["name"]

        # Construct the "user data" to inject into the VM for "cloud-init".
        user_data = MIMEMultipart()
        try:
            # Note that JSON is also valid YAML:
            #   http://yaml.org/spec/1.2/spec.html#id2759572
            part = MIMEText(json.dumps(cloud_cfg), "cloud-config")
            user_data.attach(part)
        except (ValueError, TypeError) as e:
            LOG.exception("Error serialising userdata: {0}".format(e))
            messages.error(request, str(e))
            msg = _("Failed to construct userdata for VM instance.")
            messages.error(request, msg)
            return False

        context["script_data"] = user_data.as_string()

        # We could copy the contents of the base class function here and make
        # the changes that we need.  But that would create a maintenance
        # headache since for each OpenStack update we'd have to check whether
        # anything in the original implementation changed and replicate it
        # here.  Instead, we'll rebind the "api.nova.server_create()" function
        # in the namespace of the base class function to call our hook closure
        # instead.
        api_proxy = nciutils.AttributeProxy(base_mod.api)
        api_proxy.nova = nciutils.AttributeProxy(base_mod.api.nova)

        floats = self.get_step(SetNetworkAction.slug).action.pub_ips["float"]
        api_proxy.nova.server_create = server_create_hook_func(request, context, floats)

        # We have to strip off any function decorators, otherwise the rebind
        # won't be visible inside the function.  Whilst this does rely on some
        # Python internals, the chances of those changing is significantly
        # lower especially since RedHat doesn't change the Python version
        # in a major release series.
        base_func = nciutils.undecorate(super(NCILaunchInstance, self).handle.__func__, "handle")

        g_dict = base_func.__globals__
        g_dict.update({"api": api_proxy})
        return types.FunctionType(base_func.__code__, g_dict)(self, request, context)


# vim:ts=4 et sw=4 sts=4:

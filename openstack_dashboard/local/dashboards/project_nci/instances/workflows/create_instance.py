# openstack_dashboard.local.dashboards.project_nci.instances.workflows.create_instance
#
# Copyright (c) 2015, NCI, Australian National University.
# All Rights Reserved.
#

import copy
import json
import logging
import netaddr
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

from openstack_dashboard.local.dashboards.project_nci.vlconfig.constants import *
from openstack_dashboard.local.nci import utils as nciutils


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
                # VL images have the following name format:
                #   vl-<tag_base>[-<tag_variant>-...]-<timestamp>
                if len(parts) < 3:
                    LOG.warning("Invalid VL image name format: %s" % image.name)
                    continue

                tag = "-".join(parts[1:-1])

                if re.match(r"2[0-9]{7}", parts[-1]):
                    image._vl_ts = parts[-1]
                else:
                    LOG.warning("Invalid or missing timestamp in VL image name: %s" % image.name)
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
                title += " %s" % base

            if variant:
                title += " %s" % variant

            image = copy.copy(self.vl_tags[tag])
            image._real_id = image.id
            image.id = "vltag:%s" % tag
            image.name = title
            self.vl_tags[tag] = image

            return image

        if self.vl_tags:
            choices.insert(1, ("---", "---------------"))
            for tag in reversed(sorted(self.vl_tags.keys())):
                image = clone_image(tag)
                choices.insert(1, (image.id, image))

        return choices

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


class SetNetworkAction(base_mod.SetNetworkAction):
    public_ip = forms.ChoiceField(
        label=_("Public IP Address"),
        required=False,
        help_text=_("Public IP address to associate with the instance."))

    Meta = nciutils.subclass_meta_type(base_mod.SetNetworkAction)

    @staticmethod
    def user_has_ext_net_priv(request):
        return (request.user.is_superuser
            or request.user.has_perms([settings.NCI_EXTERNAL_NET_PERM]))

    def __init__(self, request, context, *args, **kwargs):
        self.fixed_ips = netaddr.IPSet()
        self.fixed_ips_pool = False
        if self.user_has_ext_net_priv(request):
            try:
                if request.user.project_name in settings.NCI_FIXED_PUBLIC_IPS:
                    for cidr in settings.NCI_FIXED_PUBLIC_IPS[request.user.project_name]:
                        if cidr == "pool":
                            self.fixed_ips_pool = True
                        else:
                            self.fixed_ips.update(netaddr.IPNetwork(cidr))
                else:
                    # No fixed IP config found for this tenant so default to
                    # allowing use of the network's global IP allocation pool.
                    self.fixed_ips_pool = True
            except Exception as e:
                LOG.exception("Error parsing fixed public IP list: %s" % e)
                msg = _("Failed to load fixed public IP configuration.")
                messages.warning(request, msg)
                self.fixed_ips = netaddr.IPSet()
                self.fixed_ips_pool = False

        self.fixed_ips_enabled = (self.fixed_ips or self.fixed_ips_pool)

        super(SetNetworkAction, self).__init__(request, context, *args, **kwargs)

    # We're overriding the base class method here so that we can:
    # + Filter out external network(s) if no fixed IPs are allocated.
    # + Identify all network types for validation later on.
    # + Retain the selected network order when redrawing form on POST.
    #
    # We could do this after calling the base class method but that would be
    # inefficient because we'd have to fetch each network again.
    def populate_network_choices(self, request, context):
        networks = []
        try:
            networks = api.neutron.network_list_for_tenant(request, request.user.project_id)
        except Exception:
            msg = _("Unable to retrieve networks.")
            exceptions.handle(request, msg)

        if not self.fixed_ips_enabled:
            LOG.debug("Excluding external networks")
            networks = filter(lambda x: not x.get("router:external", False), networks)

        # TODO: Workaround until we can unshare the "internal" network.
        if request.user.project_name not in ["admin", "z00"]:
            networks = filter(lambda x: x.get("router:external", False) or not x.get("shared", False), networks)

        any_ext_nets = False
        self.net_is_ext = {}
        for n in networks:
            n.set_id_as_name_if_empty()
            self.net_is_ext[n.id] = n.get("router:external", False)
            any_ext_nets = any_ext_nets or self.net_is_ext[n.id]

        if self.fixed_ips_enabled and not any_ext_nets:
            LOG.debug("No external networks found - disabling fixed external IPs")
            self.fixed_ips_enabled = False

        if request.method == "POST":
            selected = self.data.getlist("network")
            networks = sorted(networks, key=lambda x: selected.index(x.id) if x.id in selected else len(selected))

        return [(network.id, network.name) for network in networks]

    def populate_public_ip_choices(self, request, context):
        choices = []

        try:
            # Add any unassigned floating IPs to the list of choices.
            floats = api.network.tenant_floating_ip_list(request)
            label = "%s (Floating)" if self.fixed_ips_enabled else "%s"
            choices.extend([("fl:%s" % x.id, label % x.ip) for x in floats if not x.port_id])

            if self.fixed_ips_enabled and self.fixed_ips:
                # Take note of all floating IPs (including assigned) since they
                # can't be used as a fixed IP given that a port already exists.
                used_ips = [x.ip for x in floats]

                # Locate any fixed IPs already assigned to an external network
                # port so that we can exclude them from the list.
                for net_id in [x for x, y in self.net_is_ext.iteritems() if y]:
                    LOG.debug("Getting port list for network: %s" % net_id)
                    ports = api.neutron.port_list(request, tenant_id=request.user.project_id, network_id=net_id)
                    for port in ports:
                        for fixed_ip in port.fixed_ips:
                            if fixed_ip.get("ip_address"):
                                used_ips.append(fixed_ip["ip_address"])

                # Add fixed IPs allocated to the tenant that aren't in use.
                used_ips = netaddr.IPSet(used_ips)
                avail_ips = self.fixed_ips - used_ips
                choices.extend([("fx:%s" % x, "%s (Fixed)" % x) for x in avail_ips])

            # Sort the list by IP address.
            choices = sorted(choices, key=lambda x: netaddr.IPAddress(x[1].split()[0]))
        except Exception as e:
            LOG.exception("Error building public IP list: %s" % e)
            msg = _("Failed to populate public IP list.")
            messages.warning(request, msg)
            choices = []

        if self.fixed_ips_enabled and self.fixed_ips_pool:
            choices.append(("pool", "Global Allocation Pool (Fixed)"))

        choices.insert(0, ("", "None"))
        return choices

    def clean(self):
        data = super(SetNetworkAction, self).clean()

        # To keep things simple (including the UI), we always associate the
        # selected public IP address (if any) to the first NIC.
        primary_net_id = None
        for net_id in data.get("network", []):
            if net_id not in self.net_is_ext:
                msg = _("Unknown network selected.")
                raise forms.ValidationError(msg)

            if not primary_net_id:
                primary_net_id = net_id
            elif self.fixed_ips_enabled and self.net_is_ext[net_id]:
                # If allocated fixed IPs are enabled, then we can't allow an
                # external network other than on the first NIC since it
                # would end up with a random public IP address otherwise.
                msg = _("An external network can only be assigned to the first NIC.")
                raise forms.ValidationError(msg)

        if data.get("public_ip"):
            if self.fixed_ips_pool and (data["public_ip"] == "pool"):
                if not (primary_net_id and self.net_is_ext[primary_net_id]):
                    msg = _("A fixed public IP address requires an external network on the first NIC.")
                    raise forms.ValidationError(msg)
                else:
                    del data["public_ip"]
            else:
                pair = data["public_ip"].split(":", 1)
                if (len(pair) != 2) or not pair[1]:
                    msg = _("Invalid public IP address selection.")
                    raise forms.ValidationError(msg)

                ip_type = pair[0]
                if ip_type == "fx":
                    if not (primary_net_id and self.net_is_ext[primary_net_id]):
                        msg = _("A fixed public IP address requires an external network on the first NIC.")
                        raise forms.ValidationError(msg)
                elif ip_type == "fl":
                    if not (primary_net_id and not self.net_is_ext[primary_net_id]):
                        msg = _("A floating public IP address requires a non-external network on the first NIC.")
                        raise forms.ValidationError(msg)
                else:
                    msg = _("Invalid public IP address selection.")
                    raise forms.ValidationError(msg)
        elif self.fixed_ips_enabled and primary_net_id and self.net_is_ext[primary_net_id]:
            msg = _("Select a fixed public IP address for the external network.")
            raise forms.ValidationError(msg)

        data["public_ip_net"] = primary_net_id
        return data


class SetNetwork(base_mod.SetNetwork):
    action_class = SetNetworkAction
    extra_contributes = ["public_ip", "public_ip_net"]

    def __init__(self, workflow):
        super(SetNetwork, self).__init__(workflow)
        self.contributes = list(self.contributes) + self.extra_contributes

        # Use our modified version of the custom workflow template which
        # makes additional fields visible.  Don't bother if the base class
        # has reverted to the default template since it shows all fields.
        if self.template_name != workflows.Step.template_name:
            self.template_name = "project/instances/../instances_nci/_update_networks.html"

    def contribute(self, data, context):
        context = super(SetNetwork, self).contribute(data, context)

        # Because the base class method overrides the default behaviour,
        # we have to explicitly add our extra fields here.
        for k in self.extra_contributes:
            context[k] = data.get(k)

        return context


class BootstrapConfigAction(workflows.Action):
    puppet_action = forms.ChoiceField(
        label=_("Puppet Action"),
        required=False,
        choices=[
            ("apply", _("Apply")),
            ("", _("None")),
        ],
        initial="",
        help_text=_("The Puppet command to execute."))

    repo_branch = forms.RegexField(
        label=_("Puppet Repository Branch"),
        required=False,
        regex=REPO_BRANCH_REGEX,
        help_text=_("The branch to checkout from the Puppet configuration repository."))

    install_updates = forms.BooleanField(
        label=_("Install Updates"),
        required=False,
        initial=True,
        help_text=_("Whether to install system updates.  (Recommended)"))

    class Meta:
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
            is_vl = api.swift.swift_object_exists(request, NCI_PVT_CONTAINER, PROJECT_CONFIG_PATH)
        except Exception:
            exceptions.handle(request)

        if is_vl:
            obj = None
            try:
                obj = api.swift.swift_get_object(request, NCI_PVT_CONTAINER, PROJECT_CONFIG_PATH)
            except Exception as e:
                LOG.exception("Error loading VL project config: %s" % e)
                msg = _("VL project configuration not found.")
                messages.warning(request, msg)

            if obj:
                project_cfg = None
                try:
                    project_cfg = json.loads(obj.data)
                except Exception as e:
                    LOG.exception("Error parsing VL project config: %s" % e)
                    msg = _("VL project configuration is corrupt.")
                    messages.warning(request, msg)

                if project_cfg is not None:
                    self.fields["repo_branch"].initial = project_cfg.get("repo_branch", "")
                    if self.fields["repo_branch"].initial:
                        self.fields["puppet_action"].initial = "apply"

    def clean(self):
        data = super(BootstrapConfigAction, self).clean()

        if data.get("puppet_action") and not data.get("repo_branch"):
            msg = _("A branch name must be specified for the selected Puppet action.")
            raise forms.ValidationError(msg)

        return data


class BootstrapConfig(workflows.Step):
    action_class = BootstrapConfigAction
    contributes = ("puppet_action", "repo_branch", "install_updates")


def server_create_hook_func(request, context):
    fixed_ip = None
    float_id = None
    if context.get("public_ip"):
        ip_net = context.get("public_ip_net")

        pair = context["public_ip"].split(":", 1)
        if pair[0] == "fx":
            fixed_ip = pair[1]
        elif pair[0] == "fl":
            float_id = pair[1]
        else:
            raise AssertionError("Unexpected public IP type")

    def _impl(*args, **kwargs):
        if fixed_ip:
            found = False
            for nic in kwargs.get("nics", []):
                if nic.get("net-id") == ip_net:
                    found = True
                    if ":" in fixed_ip:
                        nic["v6-fixed-ip"] = fixed_ip
                    else:
                        nic["v4-fixed-ip"] = fixed_ip

            if not found:
                msg = _("Unable to locate NIC for fixed IP assignment.")
                messages.error(request, msg)
                raise exceptions.WorkflowError(msg)

        srv = api.nova.server_create(*args, **kwargs)
        LOG.debug("New instance ID: %s" % getattr(srv, "id", "UNKNOWN"))

        if float_id:
            failed = True
            if hasattr(srv, "id"):
                try:
                    # Find the port created for the new instance we just
                    # started which is attached to the network selected for the
                    # floating IP association.  We have to wait until the port
                    # is created by Neutron and a fixed IP is assigned.
                    port_id = None
                    max_attempts = 15
                    attempt = 0
                    while attempt < max_attempts:
                        attempt += 1

                        LOG.debug("Locating port on network: %s" % ip_net)
                        ports = api.neutron.port_list(request,
                            device_id=srv.id,
                            network_id=ip_net)
                        if ports and getattr(ports[0], "fixed_ips", []) and ports[0].fixed_ips[0].get("ip_address"):
                            port_id = ports[0].id
                            LOG.debug("Found port %s with IP address: %s" % (port_id, ports[0].fixed_ips[0]["ip_address"]))
                            break

                        status = api.nova.server_get(request, srv.id).status.lower()
                        if status == "active":
                            if max_attempts != 2:
                                LOG.debug("VM state has become active")
                                max_attempts = 2
                                attempt = 0
                        elif status != "build":
                            LOG.debug("Aborting wait loop due to server status: %s" % status)
                            break

                        LOG.debug("Waiting for network port allocation")
                        time.sleep(2)

                    if port_id:
                        # Now locate that port in the list of floating IP targets.
                        for target in api.network.floating_ip_target_list_by_instance(request, srv.id):
                            LOG.debug("Got floating IP target: %s" % target)
                            if target.startswith(port_id):
                                api.network.floating_ip_associate(request,
                                    float_id,
                                    target)
                                srv = api.nova.server_get(request, srv.id)
                                failed = False
                                break
                except Exception as e:
                    LOG.exception("Error assigning floating IP: %s" % e)

            if failed:
                msg = _("Failed to associate floating IP with new instance.")
                messages.warning(request, msg)
            else:
                msg = _("Floating IP associated with new instance.")
                messages.info(request, msg)

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
        if context.get("public_ip") and (context["count"] > 1):
            msg = _("A single public IP can't be assigned to more than one instance.")
            self.add_error_to_step(msg, SetNetworkAction.slug)
            # Missing from "add_error_to_step()"...
            self.get_step(SetNetworkAction.slug).has_errors = True
            return False

        return True

    @sensitive_variables("context")
    def handle(self, request, context):
        # If a branch name has been specified, then we need to load the
        # project's base configuration first so that we have all the info
        # needed to clone the repository inside the VM.
        deploy_cfg = {}
        if context.get("repo_branch"):
            try:
                obj = api.swift.swift_get_object(request, NCI_PVT_CONTAINER, PROJECT_CONFIG_PATH)
            except Exception:
                msg = _("VL project configuration not found.")
                exceptions.handle(request, msg)
                return False

            try:
                project_cfg = json.loads(obj.data)
            except Exception as e:
                LOG.exception("Error parsing VL project config: %s" % e)
                msg = _("VL project configuration is corrupt.")
                messages.error(request, msg)
                return False

            # Assign the values that we need for deployment.
            copy_keys = ("repo_path", "repo_key_private")
            deploy_cfg.update([(k, v) for k, v in project_cfg.iteritems() if k in copy_keys])

        # Now add the instance specific parameters.
        deploy_cfg.update([(k, context[k]) for k in BootstrapConfig.contributes])

        # Construct the "user data" to inject into the VM for "cloud-init".
        user_data = MIMEMultipart()
        try:
            part = MIMEText(json.dumps(deploy_cfg), "nci-cloud-deploy")
            user_data.attach(part)
        except Exception as e:
            LOG.exception("Error serialising \"nci-cloud-deploy\" configuration: %s" % e)
            msg = _("Failed to construct userdata for VM instance.")
            messages.error(request, msg)
            return False

        context["customization_script"] = user_data.as_string()

        # We could copy the contents of the base class function here and make
        # the changes that we need.  But that would create a maintenance
        # headache since for each OpenStack update we'd have to check whether
        # anything in the original implementation changed and replicate it
        # here.  Instead, we'll rebind the "api.nova.server_create()" function
        # in the namespace of the base class function to call our hook closure
        # instead.
        api_proxy = nciutils.AttributeProxy(base_mod.api)
        api_proxy.nova = nciutils.AttributeProxy(base_mod.api.nova)
        api_proxy.nova.server_create = server_create_hook_func(request, context)

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

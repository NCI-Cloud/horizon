//# sourceURL=/static/project_nci/js/instances_workflow.js
//
// Copyright (c) 2015, NCI, Australian National University.
// All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may
// not use this file except in compliance with the License. You may obtain
// a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
// WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
// License for the specific language governing permissions and limitations
// under the License.
//

horizon.nci_instance_networks = {
  // Groups form fields under one "<div>" element for each network interface.
  // Any fields not associated with a particular interface are left as-is.
  group_fields_by_intf: function() {
    angular.forEach(this.fields_div.children().has("label[for^=\"id_eth\"]"), function(field) {
      var field_id = $(field).find("label").attr("for");
      var intf = field_id.split("_", 3)[1];
      var group_id = this.step_slug + "_intf_group_" + intf;

      var group_div = $(field).prev("#" + group_id);
      if (group_div.length === 0) {
        // Start a new interface group.
        // TODO: Consider using "well-sm" or even "panel" class when Horizon
        // is updated to a later version of Bootstrap.
        group_div = $("<div/>", {
          id: group_id,
          "class": this.step_slug + "-intf-group well",
          style: "padding: 9px; padding-bottom: 0px; margin-bottom: 5px;",
        });

        group_div.append($("<a/>", {
          html: intf,
          "class": "label label-info",
        }));

        this.fields_div.children("div.warning-advanced-routing").clone().appendTo(group_div);

        group_div.insertBefore(field);
      }

      // Move this field into the interface group.
      $(field).appendTo(group_div);
    }, this);

    // Remove the routing warning template and from the first interface.
    this.fields_div.children("div.warning-advanced-routing").remove();
    this.fields_div.find("div.warning-advanced-routing").first().remove();

    this.intf_group_divs = this.fields_div.children("div." + this.step_slug + "-intf-group");

    // Initialise the controls in each interface group.
    angular.forEach(this.intf_group_divs.find("select[name$=\"_network\"]"), function (select) {
      this.network_changed($(select), true);

      $(select).change(this, function(evt) {
        var that = evt.data;
        that.network_changed($(this), false);
        that.show_hide_intf_groups();
      });
    }, this);

    this.show_hide_intf_groups();
  },

  // Hides all interface groups other than those with an assigned network
  // plus the next unassigned interface.
  show_hide_intf_groups: function() {
    var group_count = this.intf_group_divs.length;
    var last_idx = -1;
    for (var i = 0; i < group_count; i++) {
      if (this.intf_group_divs.eq(i).find("select[name$=\"_network\"]").val()) {
        last_idx = i;
      }
    }

    this.intf_group_divs.find("select[name$=\"_network\"] option[value=\"\"]").prop("disabled", false);
    if (last_idx > 0) {
      // Interfaces have to be assigned consecutively so disable the
      // "unassigned" option on all but the last assigned interface
      // group.
      this.intf_group_divs.slice(0, last_idx).find("select[name$=\"_network\"] option[value=\"\"]").prop("disabled", true);
    }

    last_idx++;
    this.intf_group_divs.slice(0, last_idx + 1).removeClass("hide");
    this.intf_group_divs.slice(last_idx + 1).addClass("hide");
  },

  get_network_type: function(id) {
    if (id) {
      for (var i = 0; i < this.external_nets.length; i++) {
        if (this.external_nets[i] === id) {
          return "external";
        }
      }

      return "private";
    }
    else {
      return "";
    }
  },

  // Called whenever the selected network for an interface group changes
  // and when the form is initialised.
  network_changed: function(el, init) {
    var intf_group = el.closest("div." + this.step_slug + "-intf-group");

    var fixed_ip_div = intf_group.children("div").has("select[name*=\"fixed_ip\"]");
    var fixed_ip_select = fixed_ip_div.find("select");

    var floating_ip_div = intf_group.children("div").has("select[name*=\"floating_ip\"]");
    var floating_ip_select = floating_ip_div.find("select");

    if (init) {
      fixed_ip_select.change(function(evt) {
        var el = $(this);
        var fixed_ip_input = el.siblings("input");
        if (el.val() === "manual") {
          fixed_ip_input.prop("disabled", false);
          fixed_ip_input.removeClass("hide");
        }
        else {
          fixed_ip_input.prop("disabled", true);
          fixed_ip_input.addClass("hide");
        }
      });

      floating_ip_select.change(intf_group, function(evt) {
        var intf_group = evt.data;
        var el = $(this);
        if (el.val()) {
          intf_group.children("div.warning-advanced-routing").removeClass("hide");
        }
        else {
          intf_group.children("div.warning-advanced-routing").addClass("hide");
        }
      });
    }

    var refresh = false;
    var show_routing_warn = false;
    var new_net_type = this.get_network_type(el.val());
    if (new_net_type === "") {
      intf_group.children("div.warning-advanced-routing").addClass("hide");

      fixed_ip_select.find("option").prop("disabled", true);
      fixed_ip_select.find("option[value=\"auto\"]").prop("disabled", false);
      fixed_ip_div.addClass("hide");

      floating_ip_select.find("option").prop("disabled", true);
      floating_ip_select.find("option[value=\"\"]").prop("disabled", false);
      floating_ip_div.addClass("hide");

      refresh = true;
    }
    else {
      var old_net_type = el.data("net-type");
      if (new_net_type !== old_net_type) {
        intf_group.children("div.warning-advanced-routing").addClass("hide");

        if (new_net_type === "external") {
          show_routing_warn = true;

          fixed_ip_select.find("option").prop("disabled", true);
          fixed_ip_select.find("optgroup[label=\"External\"] option").prop("disabled", false);
          fixed_ip_div.removeClass("hide");

          floating_ip_select.find("option").prop("disabled", true);
          floating_ip_select.find("option[value=\"\"]").prop("disabled", false);
          floating_ip_div.addClass("hide");
        }
        else {
          fixed_ip_select.find("option").prop("disabled", false);
          fixed_ip_select.find("optgroup[label=\"External\"] option").prop("disabled", true);
          fixed_ip_div.removeClass("hide");

          floating_ip_select.find("option").prop("disabled", false);
          floating_ip_div.removeClass("hide");
        }

        refresh = true;
      }
    }

    if (refresh) {
      el.data("net-type", new_net_type);

      // If there is no fixed IP option selected or the selection is disabled
      // then reset the selection to the first available option (if any).
      if ((fixed_ip_select.val() === null) || !fixed_ip_select.find("option[value=\"" + fixed_ip_select.val() + "\"]").not("[disabled]").length) {
        fixed_ip_select.val(fixed_ip_select.find("option").not("[disabled]").first().attr("value"));
      }

      // As above, but for floating IP.
      if ((floating_ip_select.val() === null) || !floating_ip_select.find("option[value=\"" + floating_ip_select.val() + "\"]").not("[disabled]").length) {
        floating_ip_select.val(floating_ip_select.find("option").not("[disabled]").first().attr("value"));
      }

      fixed_ip_select.change();
      floating_ip_select.change();

      if (show_routing_warn) {
        intf_group.children("div.warning-advanced-routing").removeClass("hide");
      }
    }
  },

  workflow_init: function(modal, step_slug) {
    //debugger;
    this.step_slug = step_slug;

    this.fields_div = $("#" + step_slug + "_fields");
    this.external_nets = this.fields_div.data("external-nets").split(";");

    this.group_fields_by_intf();
  },
};


horizon.nci_instance_bootstrap = {
  workflow_init: function(modal, step_slug) {
    //debugger;
    var puppet_action_select = $("#id_puppet_action");
    puppet_action_select.change(function(evt) {
      var el = $(this);
      var puppet_env_field = $("#id_puppet_env").closest("div.form-field");
      if (el.val()) {
        puppet_env_field.removeClass("hide");
      }
      else {
        puppet_env_field.addClass("hide");
      }
    });

    puppet_action_select.change();
  },
};

// vim:ts=2 et sw=2 sts=2:

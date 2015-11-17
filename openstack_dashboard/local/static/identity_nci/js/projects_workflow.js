//# sourceURL=/static/identity_nci/js/projects_workflow.js
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

horizon.nci_project_membership = {
  workflow_init: function(modal, step_slug, step_id) {
    // Patch the relevant functions of the original implementation which
    // uses hardcoded references to the fully qualified namespace so we
    // can't just derive from it.
    $.extend(horizon.membership, {
      init_data_list: function(step_slug) {
        // Technically speaking this is actually being used as a dictionary
        // so shouldn't be using an Array here but we'll just leave it as is.
        this.data[step_slug] = [];

        // Since every role select element has the same list of members, only
        // enumerate one of them by adding the call to "first()".
        angular.forEach($(this.get_role_element(step_slug, "")).first().find("option"), function(option) {
          this.data[step_slug][option.value] = option.text;
        }, this);
      },

      generate_html: function(step_slug) {
        // Detach the elements from the DOM that we're going to be appending
        // new elements to.
        var add_member_select = $("#" + step_slug + "_add_member_select");
        var add_member_select_parent = add_member_select.parent();
        add_member_select.detach();

        var members_list = $("." + step_slug + "_members");
        var members_list_parent = members_list.parent();
        members_list.detach();

        // For each member, create an option element for the add member selection
        // control and also add them to the visible members list if they have at
        // least one role.
        var options_dict = {};
        var data_id, data = this.data[step_slug];
        for (data_id in data) {
          if(data.hasOwnProperty(data_id)){
            var display_name = data[data_id];
            var member_opt = $("<option/>", {
              html: display_name,
              value: data_id,
            });
            var role_ids = this.get_member_roles(step_slug, data_id);
            if (role_ids.length > 0) {
              members_list.append(this.generate_member_element(step_slug, display_name, data_id, role_ids, "-"));
              member_opt.prop("disabled", true);
            }

            options_dict[display_name] = member_opt;
          }
        }

        // Add the option elements to the select control in member name order.
        var keys = Object.keys(options_dict);
        keys.sort();
        var keys_len = keys.length;
        for (var i = 0; i < keys_len; ++i) {
          add_member_select.append(options_dict[keys[i]]);
        }

        // Reattach the updated elements.
        members_list_parent.prepend(members_list);
        add_member_select_parent.prepend(add_member_select);

        // And reset the add member selection.
        add_member_select.val("");

        this.detect_no_results(step_slug);
      },

      update_membership: function(step_slug) {
        // If the enter key is pressed with focus in the add member list then
        // trigger the same event as clicking the button.
        $("#" + step_slug + "_add_member_select").keydown(function(evt) {
          if (evt.keyCode === 13) {
            $("#" + step_slug + "_add_member_btn").click();
            return false;
          }
        });

        // Add a new member to the default role.
        $("#" + step_slug + "_add_member_btn").click(this, function(evt) {
          evt.preventDefault();
          var that = evt.data;
          var add_member_select = $("#" + step_slug + "_add_member_select");
          var data_id = add_member_select.val();
          if (data_id) {
            // Disable the selected add member option.
            add_member_select.children('option[value="' + data_id + '"]').prop("disabled", true);
            add_member_select.val("");

            // Select the member in the hidden default role list.
            var default_role = that.default_role_id[step_slug];
            that.add_member_to_role(step_slug, data_id, default_role);

            // Add the member to the visible list.
            var display_name = that.data[step_slug][data_id];
            $("." + step_slug + "_members").append(that.generate_member_element(step_slug, display_name, data_id, [default_role], "-"));

            // Reset filter which also has the side effect of fixing up row styles.
            that.list_filtering(step_slug);
            $("input." + step_slug + "_filter").val("");

            that.detect_no_results(step_slug);

            // Set keyboard focus back to add member list.
            add_member_select.focus();
          }
        });

        // Remove member from all roles.
        $("." + step_slug + "_members").on("click", ".btn-group a[href='#add_remove']", this, function(evt) {
          evt.preventDefault();
          var that = evt.data;
          var data_id = that.get_field_id($(this).parent().siblings().attr('data-' + step_slug +  '-id'));

          // Unselect the member in the hidden role lists.
          that.remove_member_from_role(step_slug, data_id);

          // Remove the member from the visible list.
          var member_el = $(this).parent().parent();
          member_el.remove();

          // Re-enable and select the associated option in the add member list.
          var add_member_select = $("#" + step_slug + "_add_member_select");
          add_member_select.children('option[value="' + data_id + '"]').prop("disabled", false);
          add_member_select.val(data_id);

          // Reset filter which also has the side effect of fixing up row styles.
          that.list_filtering(step_slug);
          $("input." + step_slug + "_filter").val("");

          that.detect_no_results(step_slug);
        });
      },
    });

    this.base = horizon.membership;
    this.base.workflow_init(modal, step_slug, step_id);
  },
};

// vim:ts=2 et sw=2 sts=2:

// Copyright (c) 2014, NCI, Australian National University.
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

// This function is called after "horizon.instances.workflow_init()" to fixup
// the network tab on the workflow form so that we can add additional fields
// to it since otherwise they would be hidden.
var nci_instances_workflow_init = function(modal) {
  // Move any form alert elements to the top of the form.
  // See also: horizon/templates/horizon/common/_form_fields.html
  $("#networkListSortContainer td.actions").prepend($("#networkListIdContainer td.actions div.alert-message"))

  // Add a gap between the bottom of the network drag-n-drop "div" and
  // the start of the remaining fields.
  $("#networkListSortContainer").css("margin-bottom", "9px");

  // Hide the network choice field since the drag-n-drop area replaces it.
  $("#networkListId div.form-field:first").hide();

  // And the duplicate help text as well.
  $("#networkListIdContainer td.help_text").hide();

  // Unhide the outer container so that any additional fields are visible.
  $("#networkListIdContainer").show();
}

// vim:ts=2 et sw=2 sts=2:

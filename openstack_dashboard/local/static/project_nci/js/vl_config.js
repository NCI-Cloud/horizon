//# sourceURL=/static/project_nci/js/vl_config.js
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

horizon.nci_vl_config = {
  init: function() {
    //debugger;
    var eyaml_update_select = $("#id_eyaml_update");
    eyaml_update_select.change(function(evt) {
      var el = $(this);
      var key_upload_field = $("#id_eyaml_key_upload").closest("div.form-field");
      var cert_upload_field = $("#id_eyaml_cert_upload").closest("div.form-field");
      if (el.val() === "import") {
        key_upload_field.removeClass("hide");
        cert_upload_field.removeClass("hide");
      }
      else {
        key_upload_field.addClass("hide");
        cert_upload_field.addClass("hide");
      }
    });

    eyaml_update_select.change();
  },
};

// vim:ts=2 et sw=2 sts=2:

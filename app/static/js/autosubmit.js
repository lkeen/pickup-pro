/* Submit a filter form when its control changes.
 *
 * A delegated listener rather than an onchange attribute: inline handlers are
 * exactly what the Content-Security-Policy forbids, and the <noscript> button
 * already covers browsers that never run this. */
(function () {
  "use strict";

  document.addEventListener("change", function (event) {
    var control = event.target.closest("[data-autosubmit]");
    if (control && control.form) control.form.submit();
  });
})();

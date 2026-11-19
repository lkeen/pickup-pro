/* Behaviour every page shares: the account menu and the toasts.
 *
 * The menu is a <details> element, so it opens and closes without this file;
 * this only adds closing it by clicking elsewhere or pressing Escape. Toasts
 * fade out on their own through CSS; this adds the close button. */
(function () {
  "use strict";

  function openMenus() {
    return document.querySelectorAll("details.menu[open]");
  }

  document.addEventListener("click", function (event) {
    Array.prototype.forEach.call(openMenus(), function (menu) {
      if (!menu.contains(event.target)) menu.removeAttribute("open");
    });

    var dismiss = event.target.closest("[data-dismiss]");
    if (dismiss) {
      var toast = dismiss.closest(".toast");
      if (toast) toast.remove();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    Array.prototype.forEach.call(openMenus(), function (menu) {
      menu.removeAttribute("open");
      var summary = menu.querySelector("summary");
      if (summary) summary.focus();
    });
  });
})();

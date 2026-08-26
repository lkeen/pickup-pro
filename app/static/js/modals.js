/* Stat and rating dialogs on the game detail page.
 *
 * The values come from data-* attributes rather than being interpolated into an
 * onclick attribute. That old shape put a username and a free-text comment
 * inside a JavaScript string literal inside an HTML attribute: Jinja escapes for
 * HTML, not for JS string context, so a comment containing a backslash broke the
 * call outright and the pattern was one refactor away from something worse.
 * Reading from a data attribute means the browser does the decoding and the
 * value is never parsed as code. */
(function () {
  "use strict";

  function dialogFor(name) {
    return document.querySelector('[data-dialog="' + name + '"]');
  }

  function openDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function fill(dialog, fields) {
    Object.keys(fields).forEach(function (key) {
      var node = dialog.querySelector('[data-field="' + key + '"]');
      if (!node) return;
      if (node.tagName === "INPUT" || node.tagName === "SELECT" || node.tagName === "TEXTAREA") {
        node.value = fields[key];
      } else {
        node.textContent = fields[key];
      }
    });
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-open-dialog]");
    if (trigger) {
      var dialog = dialogFor(trigger.dataset.openDialog);
      if (!dialog) return;
      fill(dialog, {
        playerName: trigger.dataset.playerName || "",
        userId: trigger.dataset.userId || "",
        points: trigger.dataset.points || "0",
        rebounds: trigger.dataset.rebounds || "0",
        assists: trigger.dataset.assists || "0",
        rating: trigger.dataset.rating || "",
        comment: trigger.dataset.comment || ""
      });
      openDialog(dialog);
      return;
    }

    var closer = event.target.closest("[data-close-dialog]");
    if (closer) {
      var owner = closer.closest("dialog");
      if (owner) owner.close();
    }
  });
})();

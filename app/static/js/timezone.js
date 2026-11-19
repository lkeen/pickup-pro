/* Tell the server which timezone this browser is in.
 *
 * A game's start is typed as wall-clock time, which only means something once
 * it is anchored to a zone, and the zone that matters is the person's own. The
 * server cannot see it, so this reports it two ways:
 *
 *   - into any [data-browser-timezone] form field, so a submitted time is read
 *     in the zone it was typed in;
 *   - as the "tz" cookie, so later pages render times in this zone too.
 *
 * Without it (JavaScript off, or an old browser) the server falls back to
 * APP_TIMEZONE and labels the times it renders with that zone. */
(function () {
  "use strict";

  var zone;
  try {
    zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch (error) {
    return;
  }
  // IANA names only use these characters, all of them cookie-safe, so the name
  // goes into the cookie as is. Percent-encoding would turn "/" into "%2F",
  // which the server does not decode.
  if (!zone || !/^[A-Za-z0-9_+\-\/]+$/.test(zone)) return;

  var fields = document.querySelectorAll("[data-browser-timezone]");
  for (var i = 0; i < fields.length; i++) fields[i].value = zone;

  var cookie = "tz=" + zone;
  if (document.cookie.split("; ").indexOf(cookie) === -1) {
    document.cookie =
      cookie + "; path=/; max-age=31536000; samesite=lax" +
      (location.protocol === "https:" ? "; secure" : "");
  }
})();

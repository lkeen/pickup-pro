/* Maps: the home map, a game's location, and the add-a-court picker.
 *
 * One file for all three because they share tiles and markers. Each map is a
 * [data-map] element whose value picks the setup.
 *
 * Tiles are OpenStreetMap's, which need no API key. The stylesheet renders
 * them in greyscale, inverted in the dark theme, so the map matches the
 * monochrome interface without a second tile provider. The
 * Content-Security-Policy allows exactly that tile host. */
(function () {
  "use strict";

  if (typeof L === "undefined") return;

  var TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  var ATTRIBUTION =
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
  var FALLBACK_VIEW = { center: [39.5, -98.35], zoom: 4 };

  function createMap(element, options) {
    var map = L.map(element, Object.assign({ zoomControl: false }, options));
    L.control.zoom({ position: "bottomright" }).addTo(map);
    // Leaflet's default prefix carries a coloured flag; the plain name keeps
    // the credit and the monochrome.
    map.attributionControl.setPrefix('<a href="https://leafletjs.com">Leaflet</a>');

    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
    return map;
  }

  /* Styled div markers rather than Leaflet's default PNGs: no image assets to
   * vendor, and they follow the theme through CSS. */
  function pin(kind, size, label) {
    return L.divIcon({
      className: "pin pin--" + kind,
      html: '<span class="pin__dot">' + (label || "") + "</span>",
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2]
    });
  }

  function readJson(id) {
    var node = document.getElementById(id);
    if (!node) return null;
    try {
      return JSON.parse(node.textContent);
    } catch (error) {
      return null;
    }
  }

  /* ---------------------------------------------------------------------- */
  /* Home: every court, the panel beside it, and searching near a point.     */
  /* ---------------------------------------------------------------------- */

  function initHome(element) {
    var data = readJson("map-data") || { courts: [] };
    var feed = document.getElementById("feed");
    var panel = feed ? feed.closest(".home__panel") : null;
    var statusEl = document.getElementById("map-status");
    var radiusSelect = document.getElementById("nearby-radius");
    var nearButton = document.getElementById("nearby-search");
    var areaButton = document.getElementById("search-area");

    var map = createMap(element, { scrollWheelZoom: true });
    var markers = {};
    var baseZ = {};
    var selectedId = null;
    var searchLayer = L.layerGroup().addTo(map);
    var pending = null;
    // True while the map is being moved by this script rather than by the
    // player, so only their own panning offers "Search this area".
    var moving = false;

    data.courts.forEach(function (court) {
      var count = Number(court.upcoming) || 0;
      var size = count ? 28 : 16;
      var marker = L.marker([court.lat, court.lng], {
        icon: count ? pin("games", size, String(count)) : pin("court", size),
        title: court.name,
        alt: court.name,
        riseOnHover: true,
        zIndexOffset: count ? 100 : 0
      }).addTo(map);
      marker.bindTooltip(
        court.name + (count ? " · " + count + (count === 1 ? " game" : " games") : ""),
        { direction: "top", offset: [0, -(size / 2) - 2] }
      );
      marker.on("click", function () { showCourt(court.id, true); });
      markers[court.id] = marker;
      baseZ[court.id] = count ? 100 : 0;
    });

    function status(message, isError) {
      if (!statusEl) return;
      statusEl.textContent = message || "";
      statusEl.classList.toggle("is-error", Boolean(isError));
    }

    function moveQuietly(move) {
      moving = true;
      move();
      var done = false;
      function settle() {
        if (done) return;
        done = true;
        setTimeout(function () { moving = false; }, 0);
      }
      map.once("moveend", settle);
      // A move to where the map already is fires no moveend.
      setTimeout(settle, 1000);
    }

    function highlight(courtId) {
      if (selectedId !== null && markers[selectedId]) {
        var previous = markers[selectedId];
        previous.setZIndexOffset(baseZ[selectedId]);
        var oldIcon = previous.getElement();
        if (oldIcon) oldIcon.classList.remove("is-selected");
      }
      selectedId = courtId;
      if (courtId !== null && markers[courtId]) {
        markers[courtId].setZIndexOffset(1000);
        var icon = markers[courtId].getElement();
        if (icon) icon.classList.add("is-selected");
      }
    }

    function clearSearch() {
      searchLayer.clearLayers();
    }

    function drawSearch(lat, lng, radiusKm, fromYou) {
      clearSearch();
      L.circle([lat, lng], {
        radius: radiusKm * 1000,
        className: "search-circle",
        interactive: false
      }).addTo(searchLayer);
      L.marker([lat, lng], {
        icon: pin(fromYou ? "you" : "drop", fromYou ? 18 : 12),
        interactive: false,
        keyboard: false,
        zIndexOffset: 500
      }).addTo(searchLayer);
    }

    function query(params) {
      var parts = Object.keys(params).map(function (key) {
        return encodeURIComponent(key) + "=" + encodeURIComponent(params[key]);
      });
      return parts.length ? "?" + parts.join("&") : "";
    }

    function loadFeed(params, push) {
      if (!feed) return;
      var qs = query(params);
      if (pending) pending.abort();
      pending = new AbortController();
      feed.setAttribute("aria-busy", "true");

      fetch("/dashboard/feed" + qs, {
        headers: { Accept: "text/html" },
        credentials: "same-origin",
        signal: pending.signal
      })
        .then(function (response) {
          // A session that expired mid-visit is redirected to sign in.
          if (response.redirected) {
            window.location.assign(response.url);
            return null;
          }
          return response.text().then(function (body) {
            if (!response.ok) throw new Error(body || "Could not load games.");
            return body;
          });
        })
        .then(function (html) {
          if (html === null) return;
          feed.innerHTML = html;
          status("");
          var url = "/dashboard" + qs;
          if (push) {
            window.history.pushState(params, "", url);
          } else {
            window.history.replaceState(params, "", url);
          }
          if (panel) panel.scrollTop = 0;
        })
        .catch(function (error) {
          if (error.name === "AbortError") return;
          status(error.message || "Could not load games.", true);
        })
        .finally(function () {
          feed.removeAttribute("aria-busy");
        });
    }

    function showAll(push) {
      highlight(null);
      clearSearch();
      loadFeed({}, push);
    }

    function showCourt(courtId, push) {
      var marker = markers[courtId];
      if (!marker) return showAll(push);
      clearSearch();
      highlight(courtId);
      hideAreaButton();
      moveQuietly(function () { map.panTo(marker.getLatLng()); });
      loadFeed({ court: courtId }, push);
    }

    function round(value) {
      return Math.round(value * 1e5) / 1e5;
    }

    function search(lat, lng, radiusKm, options) {
      highlight(null);
      hideAreaButton();
      drawSearch(lat, lng, radiusKm, options.fromYou);
      if (options.fit) {
        moveQuietly(function () {
          map.fitBounds(L.latLng(lat, lng).toBounds(radiusKm * 2000), { padding: [24, 24] });
        });
      }
      loadFeed({ lat: round(lat), lng: round(lng), radius: radiusKm }, options.push);
    }

    function radius() {
      return radiusSelect ? Number(radiusSelect.value) || 10 : 10;
    }

    var lastSearch = data.search
      ? { lat: data.search.lat, lng: data.search.lng, fromYou: false }
      : null;

    function hideAreaButton() {
      if (areaButton) areaButton.hidden = true;
    }

    // Restore whatever the URL describes.
    moveQuietly(function () {
      if (data.search) {
        drawSearch(data.search.lat, data.search.lng, data.search.radius, false);
        map.fitBounds(
          L.latLng(data.search.lat, data.search.lng).toBounds(data.search.radius * 2000),
          { padding: [24, 24], animate: false }
        );
      } else if (data.selected !== null && markers[data.selected]) {
        map.setView(markers[data.selected].getLatLng(), 14, { animate: false });
      } else if (data.courts.length) {
        map.fitBounds(
          data.courts.map(function (court) { return [court.lat, court.lng]; }),
          { padding: [56, 56], maxZoom: 14, animate: false }
        );
      } else {
        map.setView(FALLBACK_VIEW.center, FALLBACK_VIEW.zoom, { animate: false });
      }
    });
    if (data.selected !== null) highlight(data.selected);
    window.history.replaceState(
      data.selected !== null ? { court: data.selected } : (data.search || {}),
      "",
      window.location.pathname + window.location.search
    );

    if (nearButton) {
      nearButton.addEventListener("click", function () {
        if (!navigator.geolocation) {
          status("This browser cannot share your location. Move the map and search that area instead.", true);
          return;
        }
        status("Finding you…");
        nearButton.disabled = true;
        navigator.geolocation.getCurrentPosition(
          function (position) {
            nearButton.disabled = false;
            lastSearch = {
              lat: position.coords.latitude,
              lng: position.coords.longitude,
              fromYou: true
            };
            search(lastSearch.lat, lastSearch.lng, radius(), { fromYou: true, fit: true, push: true });
          },
          function () {
            nearButton.disabled = false;
            status("Could not get your location. Move the map and search that area instead.", true);
          },
          { timeout: 10000, maximumAge: 60000 }
        );
      });
    }

    if (radiusSelect) {
      radiusSelect.addEventListener("change", function () {
        if (lastSearch && searchLayer.getLayers().length) {
          search(lastSearch.lat, lastSearch.lng, radius(), {
            fromYou: lastSearch.fromYou,
            fit: true,
            push: false
          });
        }
      });
    }

    // Panning or zooming by hand offers a search of what is now in view.
    // Not moveend: a window resize ends a move too, and that is not intent.
    map.on("dragend zoomend", function () {
      if (!moving && areaButton) areaButton.hidden = false;
    });

    if (areaButton) {
      areaButton.addEventListener("click", function () {
        var center = map.getCenter();
        var bounds = map.getBounds();
        // The largest circle that fits in the view, so every result is on screen.
        var halfHeight = center.distanceTo(L.latLng(bounds.getNorth(), center.lng));
        var halfWidth = center.distanceTo(L.latLng(center.lat, bounds.getEast()));
        var km = Math.min(Math.max(Math.min(halfHeight, halfWidth) / 1000, 0.5), 200);
        km = Math.round(km * 10) / 10;
        lastSearch = { lat: center.lat, lng: center.lng, fromYou: false };
        search(center.lat, center.lng, km, { fromYou: false, fit: false, push: true });
      });
    }

    // Tapping empty map closes a court, the way a map app dismisses a place.
    map.on("click", function () {
      if (selectedId !== null) showAll(true);
    });

    if (feed) {
      feed.addEventListener("click", function (event) {
        if (event.metaKey || event.ctrlKey || event.shiftKey) return;
        // "Find a game" links go to the games list without script; with it
        // they search around the player instead.
        if (event.target.closest("a[data-near-me]") && nearButton && navigator.geolocation) {
          event.preventDefault();
          nearButton.click();
          return;
        }
        if (event.target.closest("a[data-feed-link]")) {
          event.preventDefault();
          showAll(true);
        }
      });
    }

    window.addEventListener("popstate", function () {
      var params = new URLSearchParams(window.location.search);
      var court = parseInt(params.get("court"), 10);
      var lat = parseFloat(params.get("lat"));
      var lng = parseFloat(params.get("lng"));
      if (!isNaN(court) && markers[court]) {
        showCourt(court, false);
      } else if (!isNaN(lat) && !isNaN(lng)) {
        var km = parseFloat(params.get("radius")) || 10;
        lastSearch = { lat: lat, lng: lng, fromYou: false };
        search(lat, lng, km, { fromYou: false, fit: true, push: false });
      } else {
        showAll(false);
      }
    });
  }

  /* ---------------------------------------------------------------------- */
  /* A single place: the court on a game's page.                             */
  /* ---------------------------------------------------------------------- */

  function initPoint(element) {
    var lat = parseFloat(element.getAttribute("data-lat"));
    var lng = parseFloat(element.getAttribute("data-lng"));
    if (isNaN(lat) || isNaN(lng)) return;

    var map = createMap(element, {
      scrollWheelZoom: false,
      // A small map inside a scrolling page must not trap the thumb.
      dragging: !L.Browser.mobile
    });
    map.setView([lat, lng], 15);
    L.marker([lat, lng], { icon: pin("games", 22), interactive: false, keyboard: false }).addTo(map);
  }

  /* ---------------------------------------------------------------------- */
  /* Picker: drop a pin to fill in a new court's coordinates.                */
  /* ---------------------------------------------------------------------- */

  function initPicker(element) {
    var latInput = document.getElementById(element.getAttribute("data-lat-input"));
    var lngInput = document.getElementById(element.getAttribute("data-lng-input"));
    if (!latInput || !lngInput) return;
    var locateButton = document.querySelector("[data-picker-locate]");

    var map = createMap(element, { scrollWheelZoom: false });
    var marker = null;

    function write(latlng) {
      latInput.value = latlng.lat.toFixed(6);
      lngInput.value = latlng.lng.toFixed(6);
    }

    function place(latlng) {
      if (marker) {
        marker.setLatLng(latlng);
        return;
      }
      marker = L.marker(latlng, { icon: pin("drop", 22), draggable: true, zIndexOffset: 1000 }).addTo(map);
      marker.on("dragend", function () { write(marker.getLatLng()); });
    }

    function typed() {
      var lat = parseFloat(latInput.value);
      var lng = parseFloat(lngInput.value);
      if (isNaN(lat) || isNaN(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return null;
      return L.latLng(lat, lng);
    }

    map.on("click", function (event) {
      place(event.latlng);
      write(event.latlng);
    });

    [latInput, lngInput].forEach(function (input) {
      input.addEventListener("change", function () {
        var latlng = typed();
        if (!latlng) return;
        place(latlng);
        map.panTo(latlng);
      });
    });

    var initial = typed();
    if (initial) {
      place(initial);
      map.setView(initial, 16);
    } else {
      map.setView(FALLBACK_VIEW.center, FALLBACK_VIEW.zoom);
    }

    // The existing courts, faintly, so a duplicate is easy to spot.
    fetch("/api/v1/courts", { headers: { Accept: "application/json" }, credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : { courts: [] }; })
      .then(function (body) {
        var points = [];
        body.courts.forEach(function (court) {
          L.marker([court.lat, court.lng], { icon: pin("muted", 12), keyboard: false })
            .bindTooltip(court.name, { direction: "top", offset: [0, -8] })
            .addTo(map);
          points.push([court.lat, court.lng]);
        });
        if (!initial && points.length) map.fitBounds(points, { padding: [32, 32], maxZoom: 14 });
      })
      .catch(function () { /* The picker works without them. */ });

    if (locateButton) {
      if (!navigator.geolocation) {
        locateButton.hidden = true;
      } else {
        locateButton.addEventListener("click", function () {
          locateButton.disabled = true;
          navigator.geolocation.getCurrentPosition(
            function (position) {
              locateButton.disabled = false;
              var latlng = L.latLng(position.coords.latitude, position.coords.longitude);
              place(latlng);
              write(latlng);
              map.setView(latlng, 17);
            },
            function () { locateButton.disabled = false; },
            { timeout: 10000 }
          );
        });
      }
    }
  }

  var setups = { home: initHome, point: initPoint, picker: initPicker };
  Array.prototype.forEach.call(document.querySelectorAll("[data-map]"), function (element) {
    var setup = setups[element.getAttribute("data-map")];
    if (setup) setup(element);
  });
})();

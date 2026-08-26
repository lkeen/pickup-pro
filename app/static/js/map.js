/* Court map and "find games near me".
 *
 * Talks to /api/v1/courts for the pins and /api/v1/games/nearby for the search.
 * The search endpoint is the GiST-indexed ST_DWithin query behind the Redis
 * cache, so dragging the radius slider is cheap after the first request at a
 * given setting. */
(function () {
  "use strict";

  var root = document.getElementById("court-map");
  if (!root || typeof L === "undefined") return;

  var statusEl = document.getElementById("map-status");
  var resultsEl = document.getElementById("nearby-results");
  var radiusInput = document.getElementById("nearby-radius");
  var radiusLabel = document.getElementById("nearby-radius-label");
  var searchBtn = document.getElementById("nearby-search");

  var map = L.map(root, { scrollWheelZoom: false }).setView([39.5, -98.35], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  /* Styled div markers rather than Leaflet's default PNGs: no image assets to
   * vendor, and they pick up the site's accent colour. */
  function pin(kind) {
    return L.divIcon({
      className: "map-pin map-pin--" + kind,
      iconSize: [18, 18],
      iconAnchor: [9, 9]
    });
  }

  var courtLayer = L.layerGroup().addTo(map);
  var resultLayer = L.layerGroup().addTo(map);
  var youMarker = null;
  var lastPosition = null;

  function status(message, isError) {
    if (!statusEl) return;
    statusEl.textContent = message || "";
    statusEl.className = "small " + (isError ? "field-error" : "muted");
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
  }

  function loadCourts() {
    fetch("/api/v1/courts", { headers: { Accept: "application/json" } })
      .then(function (response) {
        if (!response.ok) throw new Error("Could not load courts");
        return response.json();
      })
      .then(function (data) {
        var bounds = [];
        data.courts.forEach(function (court) {
          L.marker([court.lat, court.lng], { icon: pin("court") })
            .bindPopup(
              "<strong>" + escapeHtml(court.name) + "</strong><br>" +
              escapeHtml(court.address)
            )
            .addTo(courtLayer);
          bounds.push([court.lat, court.lng]);
        });
        if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 13 });
        status(data.count + (data.count === 1 ? " court" : " courts") + " on the map");
      })
      .catch(function (error) {
        status(error.message, true);
      });
  }

  function renderResults(games) {
    resultLayer.clearLayers();
    if (!resultsEl) return;

    if (!games.length) {
      resultsEl.innerHTML =
        '<div class="empty"><p>No games in range. Try a wider radius.</p></div>';
      return;
    }

    var rows = games.map(function (game) {
      L.marker([game.court_lat, game.court_lng], { icon: pin("game") })
        .bindPopup("<strong>" + escapeHtml(game.court_name) + "</strong>")
        .addTo(resultLayer);

      var full = game.spots_available <= 0;
      return (
        "<tr>" +
        '<td><a href="/games/' + game.id + '">' + escapeHtml(game.court_name) + "</a><br>" +
        '<span class="muted small">' + escapeHtml(game.court_address) + "</span></td>" +
        '<td class="numeric">' + game.distance_km + " km</td>" +
        '<td class="numeric"><span class="badge ' +
        (full ? "badge--full" : "badge--open") + '">' +
        game.current_players + "/" + game.max_players + "</span></td>" +
        "</tr>"
      );
    });

    resultsEl.innerHTML =
      '<div class="table-wrap"><table><thead><tr>' +
      "<th>Court</th><th class=\"numeric\">Distance</th><th class=\"numeric\">Roster</th>" +
      "</tr></thead><tbody>" + rows.join("") + "</tbody></table></div>";
  }

  function search(lat, lng) {
    var radius = radiusInput ? radiusInput.value : 10;
    status("Searching…");

    var url = "/api/v1/games/nearby?lat=" + encodeURIComponent(lat) +
      "&lng=" + encodeURIComponent(lng) + "&radius=" + encodeURIComponent(radius);

    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (response) {
        return response.json().then(function (body) {
          if (!response.ok) throw new Error(body.error || "Search failed");
          return body;
        });
      })
      .then(function (data) {
        renderResults(data.games);
        status(
          data.count + (data.count === 1 ? " game" : " games") +
          " within " + data.radius_km + " km"
        );
      })
      .catch(function (error) {
        status(error.message, true);
      });
  }

  function locate() {
    if (!navigator.geolocation) {
      status("This browser cannot share your location.", true);
      return;
    }
    status("Finding you…");
    navigator.geolocation.getCurrentPosition(
      function (position) {
        var lat = position.coords.latitude;
        var lng = position.coords.longitude;
        lastPosition = [lat, lng];

        if (youMarker) youMarker.remove();
        youMarker = L.marker([lat, lng], { icon: pin("you") })
          .bindPopup("You are here")
          .addTo(map);
        map.setView([lat, lng], 12);
        search(lat, lng);
      },
      function () {
        status("Could not get your location. Click the map to search from a point instead.", true);
      },
      { timeout: 10000 }
    );
  }

  if (searchBtn) searchBtn.addEventListener("click", locate);

  if (radiusInput && radiusLabel) {
    var syncLabel = function () {
      radiusLabel.textContent = radiusInput.value + " km";
    };
    radiusInput.addEventListener("input", syncLabel);
    // Re-run only on release, not on every pixel of slider travel.
    radiusInput.addEventListener("change", function () {
      if (lastPosition) search(lastPosition[0], lastPosition[1]);
    });
    syncLabel();
  }

  // Searching from a clicked point works without granting geolocation.
  map.on("click", function (event) {
    lastPosition = [event.latlng.lat, event.latlng.lng];
    if (youMarker) youMarker.remove();
    youMarker = L.marker(lastPosition, { icon: pin("you") })
      .bindPopup("Searching from here")
      .addTo(map);
    search(lastPosition[0], lastPosition[1]);
  });

  loadCourts();
})();

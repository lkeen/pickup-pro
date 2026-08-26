/* Stat trends on a player's profile.
 *
 * Data is embedded in the page as JSON rather than fetched: the profile query
 * has already run to render the table, so a second round trip would buy
 * nothing. */
(function () {
  "use strict";

  if (typeof Chart === "undefined") return;

  var payload = document.getElementById("profile-chart-data");
  if (!payload) return;

  var data;
  try {
    data = JSON.parse(payload.textContent);
  } catch (error) {
    return;
  }
  if (!data.games || data.games.length < 2) return;

  /* Read colours from the stylesheet so the charts follow the theme, including
   * dark mode, instead of hardcoding a second palette. */
  var styles = getComputedStyle(document.documentElement);
  function token(name, fallback) {
    return (styles.getPropertyValue(name) || "").trim() || fallback;
  }

  var accent = token("--color-accent", "#d4581f");
  var text = token("--color-text-muted", "#6b635b");
  var grid = token("--color-border", "#e3ded7");

  Chart.defaults.color = text;
  Chart.defaults.borderColor = grid;
  Chart.defaults.font.family = token("--font-sans", "system-ui, sans-serif");

  var common = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    scales: {
      x: { grid: { display: false } },
      y: { beginAtZero: true, grid: { color: grid }, ticks: { precision: 0 } }
    }
  };

  var trend = document.getElementById("stat-trend");
  if (trend) {
    new Chart(trend, {
      type: "line",
      data: {
        labels: data.games.map(function (g) { return g.date; }),
        datasets: [
          series("Points", data.games.map(function (g) { return g.points; }), accent),
          series("Rebounds", data.games.map(function (g) { return g.rebounds; }), token("--color-success", "#1f7a4d")),
          series("Assists", data.games.map(function (g) { return g.assists; }), text)
        ]
      },
      options: common
    });
  }

  var distribution = document.getElementById("rating-distribution");
  if (distribution && data.ratings && data.ratings.some(function (n) { return n > 0; })) {
    new Chart(distribution, {
      type: "bar",
      data: {
        labels: ["1", "2", "3", "4", "5"],
        datasets: [{
          label: "Ratings received",
          data: data.ratings,
          backgroundColor: accent,
          borderRadius: 4
        }]
      },
      options: Object.assign({}, common, { plugins: { legend: { display: false } } })
    });
  }

  function series(label, values, color) {
    return {
      label: label,
      data: values,
      borderColor: color,
      backgroundColor: color,
      tension: 0.3,
      pointRadius: 3,
      borderWidth: 2
    };
  }
})();

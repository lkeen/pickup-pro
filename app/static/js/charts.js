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
   * dark mode, instead of hardcoding a second palette. The interface is
   * monochrome, so series are told apart by shade and line style. */
  var styles = getComputedStyle(document.documentElement);
  function token(name, fallback) {
    return (styles.getPropertyValue(name) || "").trim() || fallback;
  }

  var ink = token("--ink", "#0b0b0b");
  var muted = token("--muted", "#666666");
  var faint = token("--faint", "#a3a3a3");
  var grid = token("--line", "#ebebeb");

  Chart.defaults.color = muted;
  Chart.defaults.borderColor = grid;
  Chart.defaults.font.family = token("--font-sans", "system-ui, sans-serif");
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxHeight = 6;

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
          series("Points", data.games.map(function (g) { return g.points; }), ink, []),
          series("Rebounds", data.games.map(function (g) { return g.rebounds; }), muted, []),
          series("Assists", data.games.map(function (g) { return g.assists; }), faint, [4, 4])
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
          backgroundColor: ink,
          borderRadius: 4,
          maxBarThickness: 40
        }]
      },
      options: Object.assign({}, common, { plugins: { legend: { display: false } } })
    });
  }

  function series(label, values, color, dash) {
    return {
      label: label,
      data: values,
      borderColor: color,
      backgroundColor: color,
      borderDash: dash,
      tension: 0.3,
      pointRadius: 3,
      borderWidth: 2
    };
  }
})();

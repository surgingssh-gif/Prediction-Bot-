/*
 * app.js - Fills in the website using the data in data.js.
 *
 * data.js is rebuilt by build_site.py after every run, so this file never
 * needs to change when new forecasts come in.
 *
 * Everything that comes from the data is inserted with textContent (never as
 * raw HTML), so a strange question title can't break or hijack the page.
 */
(function () {
  "use strict";

  var DATA = window.FORECAST_DATA || {};
  var stats = DATA.stats || { n: 0 };
  var portfolio = DATA.portfolio || { start: 1000, equity: 1000 };
  var SVG_NS = "http://www.w3.org/2000/svg";
  var AI_COLOR = "var(--series-1)";
  var CROWD_COLOR = "var(--series-2)";

  // ---------------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------------

  /* Creates an HTML element. Strings become text (never HTML). */
  function el(tag, attrs) {
    var node = document.createElement(tag);
    setAttrs(node, attrs);
    for (var i = 2; i < arguments.length; i++) append(node, arguments[i]);
    return node;
  }

  /* Creates an SVG element (used for the charts). */
  function svg(tag, attrs) {
    var node = document.createElementNS(SVG_NS, tag);
    setAttrs(node, attrs);
    for (var i = 2; i < arguments.length; i++) append(node, arguments[i]);
    return node;
  }

  function setAttrs(node, attrs) {
    if (!attrs) return;
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "text") node.textContent = value;
      else if (key === "style" && typeof value === "object") Object.assign(node.style, value);
      else if (key.slice(0, 2) === "on") node.addEventListener(key.slice(2), value);
      else node.setAttribute(key, value);
    });
  }

  function append(node, child) {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { append(node, c); }); return; }
    node.appendChild(typeof child === "object" ? child : document.createTextNode(String(child)));
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

  function pct(p) { return p === null || p === undefined ? "n/a" : Math.round(p * 100) + "%"; }
  function brier(b) { return b === null || b === undefined ? "–" : b.toFixed(3); }
  function money(x, sign) {
    var s = "$" + Math.abs(x).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (x < 0) return "−" + s;
    return sign && x > 0 ? "+" + s : s;
  }
  function shortDate(iso) {
    if (!iso) return "";
    var d = new Date(iso.length === 10 ? iso + "T12:00:00Z" : iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
  }
  function longDate(iso) {
    var d = iso ? new Date(iso) : new Date();
    return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  }
  function keyLine(color) { return el("span", { class: "key-line", style: { borderTopColor: color } }); }
  function keyDot(color) { return el("span", { class: "key-dot", style: { background: color } }); }
  function recordUrl(run) {
    return "https://github.com/" + DATA.repo + "/commits/main/data/forecasts/" + run + ".json";
  }

  // ---------------------------------------------------------------------------
  // Masthead, theme and tabs
  // ---------------------------------------------------------------------------

  function setupMasthead() {
    document.getElementById("updated").textContent = DATA.generated_at
      ? "Updated " + new Date(DATA.generated_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
      : "No data yet";
    document.getElementById("dl-left").textContent = longDate(DATA.generated_at);
    document.getElementById("dl-right").textContent = "Forecaster: " + (DATA.model || "Claude");
    if (DATA.pending && DATA.pending.length) {
      var n = DATA.pending.reduce(function (sum, p) { return sum + p.n; }, 0);
      var notice = document.getElementById("notice");
      notice.textContent = "Claude is still working on " + n + " question" + (n === 1 ? "" : "s") +
        " sent " + shortDate(DATA.pending[0].asked) + ". They'll appear here once answered.";
      notice.hidden = false;
    }
  }

  function setupTheme() {
    var button = document.getElementById("theme-toggle");
    var root = document.documentElement;
    function current() {
      var set = root.getAttribute("data-theme");
      if (set) return set;
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    function label() { button.textContent = current() === "dark" ? "Light mode" : "Dark mode"; }
    try { var saved = localStorage.getItem("theme"); if (saved) root.setAttribute("data-theme", saved); } catch (e) { /* no storage */ }
    label();
    button.addEventListener("click", function () {
      var next = current() === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) { /* no storage */ }
      label();
    });
  }

  var TABS = ["scoreboard", "calibration", "open", "settled", "method"];
  function showTab() {
    var name = (location.hash || "").slice(1);
    if (TABS.indexOf(name) < 0) name = "scoreboard";
    TABS.forEach(function (t) {
      document.getElementById("tab-" + t).hidden = t !== name;
    });
    document.querySelectorAll(".sections a").forEach(function (a) {
      if (a.getAttribute("data-tab") === name) a.setAttribute("aria-current", "page");
      else a.removeAttribute("aria-current");
    });
  }

  // ---------------------------------------------------------------------------
  // Charts
  // ---------------------------------------------------------------------------

  /* Rounded tick values between lo and hi. */
  function ticks(lo, hi, count) {
    var step = (hi - lo) / count;
    var mag = Math.pow(10, Math.floor(Math.log10(step)));
    var nice = [1, 2, 2.5, 5, 10].map(function (m) { return m * mag; }).find(function (s) { return s >= step; });
    var out = [];
    for (var v = Math.ceil(lo / nice) * nice; v <= hi + 1e-9; v += nice) out.push(+v.toFixed(10));
    return out;
  }

  /* Places the tooltip box near (x, y) inside the chart, without spilling out. */
  function placeTooltip(tip, wrap, x, y) {
    tip.hidden = false;
    var w = wrap.clientWidth, tw = tip.offsetWidth;
    var left = x + 14;
    if (left + tw > w) left = x - tw - 14;
    tip.style.left = Math.max(0, left) + "px";
    tip.style.top = Math.max(0, y - 10) + "px";
  }

  function tooltipRows(rows) {
    return rows.map(function (r) {
      return el("div", { class: "tt-row" }, r.key, el("strong", { text: r.value }), el("span", { text: r.name }));
    });
  }

  /*
   * A line chart with a hover crosshair.
   * opts.series: [{name, color, values: [number...]}]  (all the same length)
   * opts.xLabel(i): text for point i;  opts.yFormat(v): text for a value
   * opts.ref: {value, label} for a dashed reference line (optional)
   */
  function lineChart(container, opts) {
    var W = 560, H = 250, M = { l: 48, r: 60, t: 12, b: 26 };
    var n = opts.series[0].values.length;
    var all = [];
    opts.series.forEach(function (s) { all = all.concat(s.values); });
    if (opts.ref) all.push(opts.ref.value);
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);
    var pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.05 || 0.05;
    lo -= pad; hi += pad;
    if (opts.floor !== undefined) lo = Math.max(lo, opts.floor);
    var x = function (i) { return M.l + (n === 1 ? (W - M.l - M.r) / 2 : i * (W - M.l - M.r) / (n - 1)); };
    var y = function (v) { return M.t + (hi - v) * (H - M.t - M.b) / (hi - lo); };

    var root = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": opts.label });
    var grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
    ticks(lo, hi, 4).forEach(function (t) {
      grid.appendChild(svg("line", { x1: M.l, x2: W - M.r, y1: y(t), y2: y(t) }));
      axis.appendChild(svg("text", { x: M.l - 8, y: y(t) + 4, "text-anchor": "end", text: opts.yFormat(t) }));
    });
    [0, Math.floor((n - 1) / 2), n - 1].filter(function (v, i, a) { return a.indexOf(v) === i; }).forEach(function (i) {
      var anchor = n === 1 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle";
      axis.appendChild(svg("text", { x: x(i), y: H - 6, "text-anchor": anchor, text: opts.xLabel(i) }));
    });
    root.appendChild(grid);
    root.appendChild(axis);

    if (opts.ref) {
      root.appendChild(svg("line", { class: "ref", x1: M.l, x2: W - M.r, y1: y(opts.ref.value), y2: y(opts.ref.value) }));
      root.appendChild(svg("text", { class: "ref-label", x: M.l + 4, y: y(opts.ref.value) - 5, text: opts.ref.label }));
    }

    opts.series.forEach(function (s) {
      var d = s.values.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); }).join("");
      if (n > 1) root.appendChild(svg("path", { d: d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
      root.appendChild(svg("circle", { cx: x(n - 1), cy: y(s.values[n - 1]), r: 4, fill: s.color, stroke: "var(--paper)", "stroke-width": 2 }));
    });
    // Direct labels at the right end, nudged apart if they'd overlap.
    var ends = opts.series.map(function (s) { return { s: s, y: y(s.values[n - 1]) }; }).sort(function (a, b) { return a.y - b.y; });
    for (var k = 1; k < ends.length; k++) if (ends[k].y - ends[k - 1].y < 14) ends[k].y = ends[k - 1].y + 14;
    ends.forEach(function (e) {
      root.appendChild(svg("text", { class: "series-label", x: x(n - 1) + 8, y: e.y + 4, text: e.s.short || e.s.name }));
    });

    // Hover / keyboard layer: a hairline snaps to the nearest point.
    var cross = svg("line", { class: "crosshair", y1: M.t, y2: H - M.b, visibility: "hidden" });
    root.appendChild(cross);
    var hit = svg("rect", { x: M.l, y: M.t, width: W - M.l - M.r, height: H - M.t - M.b, fill: "transparent", tabindex: 0,
      "aria-label": "Use the left and right arrow keys to read values" });
    root.appendChild(hit);

    var legend = el("div", { class: "legend" }, opts.series.length > 1 ? opts.series.map(function (s) {
      return el("span", null, keyLine(s.color), s.name);
    }) : null);
    var tip = el("div", { class: "tooltip", hidden: true });
    var holder = el("div", { style: { position: "relative" } }, root, tip);
    var active = n - 1;
    function show(i) {
      active = Math.max(0, Math.min(n - 1, i));
      cross.setAttribute("x1", x(active)); cross.setAttribute("x2", x(active));
      cross.setAttribute("visibility", "visible");
      clear(tip);
      tip.appendChild(el("div", { class: "tt-title", text: opts.xLabel(active, true) }));
      append(tip, tooltipRows(opts.series.map(function (s) {
        return { key: keyLine(s.color), value: opts.yFormat(s.values[active], true), name: s.name };
      })));
      var scale = root.getBoundingClientRect().width / W;
      placeTooltip(tip, holder, x(active) * scale, y(opts.series[0].values[active]) * scale);
    }
    function hide() { tip.hidden = true; cross.setAttribute("visibility", "hidden"); }
    hit.addEventListener("pointermove", function (e) {
      var box = root.getBoundingClientRect();
      var px = (e.clientX - box.left) * W / box.width;
      show(n === 1 ? 0 : Math.round((px - M.l) / ((W - M.l - M.r) / (n - 1))));
    });
    hit.addEventListener("pointerleave", hide);
    hit.addEventListener("blur", hide);
    hit.addEventListener("focus", function () { show(active); });
    hit.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") { show(active - 1); e.preventDefault(); }
      if (e.key === "ArrowRight") { show(active + 1); e.preventDefault(); }
    });

    append(clear(container), el("div", { class: "chart" }, legend, holder));
    if (opts.note) container.appendChild(el("p", { class: "chart-note", text: opts.note }));
  }

  /* The calibration chart: forecast (across) vs how often it happened (up). */
  function calibrationChart(container, cal) {
    var S = 380, M = { l: 46, r: 14, t: 12, b: 40 };
    var size = S - M.l - M.r;
    var x = function (v) { return M.l + v * size; };
    var y = function (v) { return M.t + (1 - v) * size; };
    var root = svg("svg", { viewBox: "0 0 " + S + " " + (M.t + size + M.b), role: "img",
      "aria-label": "Calibration chart: average forecast against how often events happened, for the AI and the crowd" });
    var grid = svg("g", { class: "grid" }), axis = svg("g", { class: "axis" });
    [0, 0.25, 0.5, 0.75, 1].forEach(function (t) {
      grid.appendChild(svg("line", { x1: x(0), x2: x(1), y1: y(t), y2: y(t) }));
      axis.appendChild(svg("text", { x: M.l - 8, y: y(t) + 4, "text-anchor": "end", text: pct(t) }));
      axis.appendChild(svg("text", { x: x(t), y: y(0) + 18, "text-anchor": "middle", text: pct(t) }));
    });
    axis.appendChild(svg("text", { x: x(0.5), y: y(0) + 34, "text-anchor": "middle", text: "Forecast" }));
    axis.appendChild(svg("text", { x: 12, y: y(0.5), "text-anchor": "middle", transform: "rotate(-90 12 " + y(0.5) + ")", text: "Actually happened" }));
    root.appendChild(grid);
    root.appendChild(axis);
    root.appendChild(svg("line", { class: "ref", x1: x(0), y1: y(0), x2: x(1), y2: y(1) }));
    root.appendChild(svg("text", { class: "ref-label", x: x(0.62), y: y(0.62) - 8, transform: "rotate(-45 " + x(0.62) + " " + (y(0.62) - 8) + ")", text: "perfect calibration" }));

    var tip = el("div", { class: "tooltip", hidden: true });
    var holder = el("div", { style: { position: "relative" } }, root, tip);
    var maxN = 1;
    ["ai", "crowd"].forEach(function (k) { (cal[k] || []).forEach(function (b) { maxN = Math.max(maxN, b.n); }); });
    [["crowd", CROWD_COLOR, "Crowd"], ["ai", AI_COLOR, "AI"]].forEach(function (cfg) {
      (cal[cfg[0]] || []).forEach(function (b) {
        var r = 4 + 8 * Math.sqrt(b.n / maxN);
        var g = svg("g", { tabindex: 0, "aria-label": cfg[2] + ": forecast " + pct(b.forecast) + ", happened " + pct(b.observed) + ", " + b.n + " questions" });
        g.appendChild(svg("circle", { cx: x(b.forecast), cy: y(b.observed), r: r, fill: cfg[1], stroke: "var(--paper)", "stroke-width": 2, "fill-opacity": 0.9 }));
        g.appendChild(svg("circle", { cx: x(b.forecast), cy: y(b.observed), r: Math.max(r, 12), fill: "transparent" }));
        function show() {
          clear(tip);
          tip.appendChild(el("div", { class: "tt-title", text: cfg[2] + " · " + (b.bin * 10) + "–" + (b.bin * 10 + 10) + "% bucket" }));
          append(tip, tooltipRows([
            { key: keyDot(cfg[1]), value: pct(b.forecast), name: "average forecast" },
            { key: keyDot(cfg[1]), value: pct(b.observed), name: "actually happened" },
            { key: keyDot(cfg[1]), value: String(b.n), name: b.n === 1 ? "question" : "questions" },
          ]));
          var scale = root.getBoundingClientRect().width / S;
          placeTooltip(tip, holder, x(b.forecast) * scale, y(b.observed) * scale);
        }
        g.addEventListener("pointerenter", show);
        g.addEventListener("focus", show);
        g.addEventListener("pointerleave", function () { tip.hidden = true; });
        g.addEventListener("blur", function () { tip.hidden = true; });
        root.appendChild(g);
      });
    });
    var legend = el("div", { class: "legend" },
      el("span", null, keyDot(AI_COLOR), "AI (" + DATA.model + ")"),
      el("span", null, keyDot(CROWD_COLOR), "Crowd (market price)"));
    append(clear(container), el("div", { class: "chart" }, legend, holder));
  }

  // ---------------------------------------------------------------------------
  // Scoreboard
  // ---------------------------------------------------------------------------

  function renderScoreboard() {
    var n = stats.n || 0;
    var openCount = (DATA.open || []).length;
    document.getElementById("sb-deck").textContent = n
      ? "Every day an AI forecasts about ten real-world questions from Polymarket without seeing the market's odds. " +
        n + " of those questions have now been settled. Here's how its forecasts compare with the crowd's on exactly the same questions."
      : "Every day an AI forecasts about ten real-world questions from Polymarket without seeing the market's odds. " +
        "No questions have been settled yet" + (openCount ? " (" + openCount + " are open)" : "") +
        ". Scores appear here as they close, usually within 1 to 30 days.";

    function side(name, color, value, sub) {
      return el("div", { class: "side" },
        el("h3", null, keyDot(color), name),
        el("div", { class: "big", text: brier(value) }),
        el("div", { class: "sub", text: sub }));
    }
    append(clear(document.getElementById("duel")), [
      side("The AI", AI_COLOR, stats.ai_brier, n ? "closer on " + stats.ai_closer + " of " + n : "Brier score"),
      el("div", { class: "vs", text: "vs." }),
      side("The Crowd", CROWD_COLOR, stats.crowd_brier, n ? "closer on " + stats.crowd_closer + " of " + n : "Brier score"),
    ]);

    var verdict = document.getElementById("verdict");
    clear(verdict);
    if (!n) {
      append(verdict, ["The ", el("strong", { text: "Brier score" }), " measures forecast error: 0 is perfect, 0.25 is what you'd get by always saying 50%, and lower is better."]);
    } else {
      var leader = stats.diff < 0 ? "the AI" : stats.diff > 0 ? "the crowd" : "neither side";
      var range = stats.ci_low === null ? "" : " The 95% range for the difference (AI minus crowd) is " +
        stats.ci_low.toFixed(3) + " to " + stats.ci_high.toFixed(3) + ".";
      var call;
      if (n < 30) call = el("strong", { text: "Too early to call." });
      else if (stats.ci_high < 0) call = el("strong", { text: "The AI is ahead, by more than luck alone would likely explain." });
      else if (stats.ci_low > 0) call = el("strong", { text: "The crowd is ahead, by more than luck alone would likely explain." });
      else call = el("strong", { text: "Too close to call." });
      append(verdict, [call, " So far " + leader + " has the lower (better) score." + range +
        (n < 100 ? " With fewer than about 100 settled questions, differences like this can easily be luck." : "")]);
    }

    var pnl = portfolio.equity - portfolio.start;
    function stat(label, value, hint, cls) {
      return el("div", { class: "stat" }, el("div", { class: "label", text: label }),
        el("div", { class: "value" + (cls ? " " + cls : ""), text: value }), el("div", { class: "hint", text: hint }));
    }
    append(clear(document.getElementById("stats")), [
      stat("Paper bankroll", money(portfolio.equity), "started at " + money(portfolio.start), null),
      stat("Profit / loss", money(pnl, true), portfolio.staked ? (pnl / portfolio.staked * 100).toFixed(1) + "% of money bet" : "fake money", pnl > 0 ? "up" : pnl < 0 ? "down" : null),
      stat("Bets won", portfolio.settled_bets ? portfolio.wins + " of " + portfolio.settled_bets : "–", "settled paper bets", null),
      stat("Open bets", String(portfolio.open_bets || 0), money(portfolio.open_cost || 0) + " in play", null),
      stat("Fees paid", money(portfolio.fees || 0), "Polymarket's real fees", null),
    ]);

    var running = DATA.running || [];
    var rc = document.getElementById("running-chart");
    if (running.length) {
      lineChart(rc, {
        label: "Average Brier score after each settled question, AI versus crowd",
        series: [
          { name: "AI", color: AI_COLOR, values: running.map(function (p) { return p.ai; }) },
          { name: "Crowd", color: CROWD_COLOR, values: running.map(function (p) { return p.crowd; }) },
        ],
        xLabel: function (i, long) { return long ? "After " + running[i].n + " settled · " + shortDate(running[i].date) : String(running[i].n); },
        yFormat: function (v) { return v.toFixed(3); },
        ref: { value: 0.25, label: "always saying 50%" },
        floor: 0,
        note: "Across: number of settled questions. Each point is the average score of everything settled so far.",
      });
    } else {
      append(clear(rc), el("p", { class: "empty", text: "This chart starts once the first questions settle." }));
    }

    var bank = DATA.bankroll || [];
    var bc = document.getElementById("bankroll-chart");
    if (bank.length > 1) {
      lineChart(bc, {
        label: "Paper bankroll over time",
        series: [{ name: "Bankroll", short: money(bank[bank.length - 1].equity), color: AI_COLOR, values: bank.map(function (p) { return p.equity; }) }],
        xLabel: function (i) { return shortDate(bank[i].date); },
        yFormat: function (v, long) { return long ? money(v) : "$" + Math.round(v).toLocaleString("en-US"); },
        ref: { value: portfolio.start, label: "starting $1,000" },
        note: "Open bets count at what was paid for them, until they settle.",
      });
    } else {
      append(clear(bc), el("p", { class: "empty", text: "This chart starts once the first paper bets settle." }));
    }

    var topics = DATA.topics || [];
    var tc = clear(document.getElementById("topics"));
    if (!topics.length) {
      tc.appendChild(el("p", { class: "empty", text: "Topic results appear once questions settle." }));
    } else {
      var rows = topics.map(function (t) {
        var winner = t.diff < 0 ? "AI" : t.diff > 0 ? "Crowd" : "Tie";
        return el("tr", null, el("td", { text: t.topic }), el("td", { class: "r", text: String(t.n) }),
          el("td", { class: "r", text: brier(t.ai_brier) }), el("td", { class: "r", text: brier(t.crowd_brier) }),
          el("td", { text: winner }));
      });
      tc.appendChild(el("div", { class: "table-scroll" }, el("table", { class: "data" },
        el("thead", null, el("tr", null, el("th", { text: "Topic" }), el("th", { class: "r", text: "Settled" }),
          el("th", { class: "r", text: "AI Brier" }), el("th", { class: "r", text: "Crowd Brier" }), el("th", { text: "Better" }))),
        el("tbody", null, rows))));
    }
  }

  // ---------------------------------------------------------------------------
  // Calibration
  // ---------------------------------------------------------------------------

  function renderCalibration() {
    var cal = DATA.calibration || { ai: [], crowd: [] };
    var chart = document.getElementById("cal-chart");
    var table = clear(document.getElementById("cal-table"));
    if (!(cal.ai || []).length) {
      append(clear(chart), el("p", { class: "empty", text: "The calibration chart appears once questions settle." }));
      return;
    }
    calibrationChart(chart, cal);
    var byBin = {};
    ["ai", "crowd"].forEach(function (k) { cal[k].forEach(function (b) { (byBin[b.bin] = byBin[b.bin] || {})[k] = b; }); });
    var rows = Object.keys(byBin).sort(function (a, b) { return a - b; }).map(function (bin) {
      var a = byBin[bin].ai, c = byBin[bin].crowd;
      return el("tr", null, el("td", { text: (bin * 10) + "–" + (bin * 10 + 10) + "%" }),
        el("td", { class: "r", text: a ? a.n + " · said " + pct(a.forecast) + " · " + pct(a.observed) + " happened" : "–" }),
        el("td", { class: "r", text: c ? c.n + " · said " + pct(c.forecast) + " · " + pct(c.observed) + " happened" : "–" }));
    });
    table.appendChild(el("div", { class: "table-scroll" }, el("table", { class: "data" },
      el("thead", null, el("tr", null, el("th", { text: "Bucket" }), el("th", { class: "r", text: "AI" }), el("th", { class: "r", text: "Crowd" }))),
      el("tbody", null, rows))));
  }

  // ---------------------------------------------------------------------------
  // Question cards
  // ---------------------------------------------------------------------------

  /* The 0-100% strip with the AI's dot, the crowd's dot and (if settled) the result. */
  function compareStrip(row) {
    var lo = Math.min(row.ai, row.crowd), hi = Math.max(row.ai, row.crowd);
    var track = el("div", { class: "compare-track", "aria-hidden": "true" },
      el("div", { class: "compare-line" }),
      el("div", { class: "compare-gap", style: { left: lo * 100 + "%", width: (hi - lo) * 100 + "%" } }),
      row.outcome === 0 || row.outcome === 1 ? el("div", { class: "compare-outcome", style: { left: row.outcome * 100 + "%" } }) : null,
      el("div", { class: "compare-dot", style: { left: row.crowd * 100 + "%", background: CROWD_COLOR } }),
      el("div", { class: "compare-dot", style: { left: row.ai * 100 + "%", background: AI_COLOR } }));
    var gap = Math.round(Math.abs(row.ai - row.crowd) * 100);
    return el("div", { class: "compare" }, track,
      el("div", { class: "compare-scale" }, el("span", { text: "0% (No)" }), el("span", { text: "50%" }), el("span", { text: "100% (Yes)" })),
      el("div", { class: "compare-legend" },
        el("span", null, keyDot(AI_COLOR), " AI says ", el("strong", { text: pct(row.ai) })),
        el("span", null, keyDot(CROWD_COLOR), " Crowd said ", el("strong", { text: pct(row.crowd) })),
        el("span", { text: gap + "-point gap" })));
  }

  function sources(row) {
    if (!row.news || !row.news.length) return el("p", { class: "record-link", text: "No news headlines were found for this question." });
    return el("details", { class: "more" }, el("summary", { text: "News the AI read (" + row.news.length + ")" }),
      el("ul", null, row.news.map(function (h) {
        var label = (h.d ? h.d + " · " : "") + (h.s || "");
        return el("li", null, h.l ? el("a", { href: h.l, target: "_blank", rel: "noopener", text: h.t }) : h.t,
          label ? el("span", { text: " (" + label + ")" }) : null);
      })));
  }

  function card(row, settled) {
    var title = row.url ? el("a", { href: row.url, target: "_blank", rel: "noopener", text: row.q }) : row.q;
    var meta = [row.topic, settled ? "Settled " + shortDate(row.settled) : "Closes " + shortDate(row.end), "Asked " + shortDate(row.asked)];
    var right = null;
    if (settled) {
      var result = row.outcome === "void" ? "Cancelled" : row.outcome === 1 ? "Resolved YES" : "Resolved NO";
      var badges = [el("span", { class: "badge plain", text: result })];
      if (row.ai_brier !== undefined) {
        var aiWon = row.ai_brier < row.crowd_brier, tie = row.ai_brier === row.crowd_brier;
        badges.push(" ", el("span", { class: "badge " + (tie ? "plain" : aiWon ? "win" : "loss"), text: tie ? "Tie" : aiWon ? "AI was closer" : "Crowd was closer" }));
      }
      right = el("div", { class: "pnl" }, badges,
        row.pnl !== undefined ? el("div", { class: row.pnl > 0 ? "up" : row.pnl < 0 ? "down" : "", style: { marginTop: "8px" } },
          money(row.pnl, true), el("small", { text: "paper bet " + row.bet.side })) : null);
    } else if (row.bet) {
      right = el("span", { class: "badge bet", text: "Paper bet: " + row.bet.side });
    }

    var betLine = row.bet
      ? el("p", { class: "bet-line" }, "Bought ", el("strong", { text: row.bet.side }), " at " + Math.round(row.bet.price * 100) +
        "¢ a share: " + row.bet.shares + " shares for " + money(row.bet.cost) + " including " + money(row.bet.fee) + " in fees.")
      : row.note ? el("p", { class: "bet-line", text: "No bet: " + row.note.replace(/\.$/, "") + "." }) : null;

    return el("li", { class: "card" },
      el("div", { class: "card-top" },
        el("div", null, el("h3", null, title),
          el("p", { class: "meta" }, meta.map(function (m, i) { return [i ? el("span", { class: "sep", text: "·" }) : null, m]; }))),
        right),
      compareStrip(row),
      betLine,
      row.why ? el("p", { class: "reason", text: row.why }) : null,
      sources(row),
      el("p", { class: "record-link" }, el("a", { href: recordUrl(row.run), target: "_blank", rel: "noopener", text: "Original record" }),
        " · committed to GitHub when it was made, before the result was known"));
  }

  var openFilter = "bets";
  function renderOpen() {
    var all = DATA.open || [];
    var rows = openFilter === "bets" ? all.filter(function (r) { return r.bet; }) : all;
    var betCount = all.filter(function (r) { return r.bet; }).length;
    document.getElementById("open-sub").textContent = all.length + " waiting to settle · " + betCount + " with paper bets · soonest first";
    document.querySelectorAll("[data-filter]").forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.getAttribute("data-filter") === openFilter));
    });
    var list = clear(document.getElementById("open-list"));
    if (!rows.length) {
      list.appendChild(el("li", { class: "empty", text: all.length
        ? "No paper bets are open right now. The AI only bets when it disagrees with the crowd by " + Math.round(DATA.settings.min_edge * 100) + "+ points."
        : "No open forecasts yet. The first ones arrive after the first daily run." }));
      return;
    }
    rows.forEach(function (r) { list.appendChild(card(r, false)); });
  }

  function renderSettled() {
    var rows = DATA.settled || [];
    var total = DATA.settled_total || 0;
    document.getElementById("settled-sub").textContent = total
      ? total + " settled · newest first" + (total > rows.length ? " · showing the latest " + rows.length : "")
      : "";
    var list = clear(document.getElementById("settled-list"));
    if (!rows.length) {
      list.appendChild(el("li", { class: "empty", text: "Nothing has settled yet. Questions close 1 to 30 days after they're asked." }));
      return;
    }
    rows.forEach(function (r) { list.appendChild(card(r, true)); });
  }

  // ---------------------------------------------------------------------------
  // Methodology
  // ---------------------------------------------------------------------------

  function renderMethod() {
    var s = DATA.settings || {};
    var p = function (text) { return el("p", { text: text }); };
    var h = function (text) { return el("h3", { text: text }); };
    var li = function (text) { return el("li", { text: text }); };
    append(clear(document.getElementById("method")), [
      h("The question"),
      p("Can an AI predict real-world events better than the crowd? Prediction markets like Polymarket let people trade on " +
        "questions such as “Will the Fed cut rates in October?”. A share pays $1 if the answer is Yes, so its price works as " +
        "the crowd's probability: 62¢ means about a 62% chance. Markets like these are hard to beat, which makes them a tough benchmark."),
      h("Each day"),
      el("ol", null, [
        li("About " + s.per_day + " new questions are picked from Polymarket's most-traded markets. Each one must be about the " +
          "economy, politics, tech, business, science, weather or entertainment; close in " + s.min_days + " to " + s.max_days +
          " days; have at least $" + (s.min_volume || 0).toLocaleString() + " traded, a tight price spread and written resolution rules; " +
          "and not be nearly certain (the crowd must be between " + pct(s.min_price) + " and " + pct(s.max_price) + "). " +
          "Sports, esports, crypto price bets and questions about Anthropic (the AI's maker) are skipped. No more than 3 per topic per day."),
        li("For each question, the top " + s.headlines + " Google News headlines from the last " + s.lookback.replace("d", " days") +
          " are collected. Headlines that mention prediction markets, betting or odds are thrown out, so the AI can't see the crowd's price."),
        li("All the questions go to Claude (" + DATA.model + ", " + DATA.effort + " effort) in one request. It sees each question, its " +
          "rules and its news, but never the market price. It answers with a probability and a short explanation. " +
          "Each question is forecast once, and the same model is used for the whole experiment."),
        li("The forecasts are saved and committed to GitHub straight away, with a timestamp, before any result is known. " +
          "The files are never edited afterwards (the “Original record” links show their history)."),
      ]),
      h("Scoring"),
      p("The Brier score is the squared gap between a forecast and what happened (1 for Yes, 0 for No), averaged over all " +
        "questions. Lower is better: 0 is perfect, and always saying 50% scores 0.25. Both the AI and the crowd are scored on exactly " +
        "the same questions. The crowd's forecast is the market's midpoint price at the moment the questions were picked, " +
        "which is also when the AI's news was gathered, so both sides had the same information at the same time. " +
        "Cancelled questions, and any that closed before the AI's answer arrived, are left out."),
      p("The scoreboard also shows a 95% range for the difference between the two scores. If that range includes zero, " +
        "the difference could just be luck."),
      h("Paper trading (fake money)"),
      p("The AI starts with $" + (s.start || 1000).toLocaleString() + " of pretend money. It bets only when its probability " +
        "is at least " + Math.round(s.min_edge * 100) + " points away from the price it would actually pay. It buys at the current " +
        "asking price (not the midpoint) and pays Polymarket's real taker fee, so the results aren't flattered. " +
        "Bet size uses the Kelly formula, scaled down to " + s.kelly * 100 + "% of what Kelly suggests, and never more than " +
        s.max_bet * 100 + "% of the bankroll on one question."),
      h("Limits to keep in mind"),
      el("ul", null, [
        li("Small samples are noisy. Expect wild swings until at least 100 questions have settled."),
        li("The news filter can't catch everything. An article might still mention, say, interest-rate futures pricing, " +
          "which is crowd-like information from a different market."),
        li("The AI only reads headlines (Google's free feed has no article text), while traders can read everything."),
        li("The questions aren't independent: two candidates in one election, or several Fed outcomes, rise and fall together."),
        li("The question filters (most-traded, not nearly certain) shape which questions are tested, so results may not apply to all questions."),
        li("Paper trades assume the asking price was available for the full amount. A real order might move the price a little."),
      ]),
      h("Cost"),
      p("One request a day through Anthropic's Message Batches API, which is half price. Total so far: $" +
        (DATA.total_cost || 0).toFixed(2) + "."),
      p("Research only. Paper trading with fake money: no real bets are placed, ever. Nothing here is financial or betting advice."),
    ]);

    var runs = DATA.runs || [];
    var rc = clear(document.getElementById("runs"));
    if (!runs.length) {
      rc.appendChild(el("p", { class: "empty", text: "No runs yet." }));
      return;
    }
    rc.appendChild(el("div", { class: "table-scroll" }, el("table", { class: "data" },
      el("thead", null, el("tr", null, el("th", { text: "Run" }), el("th", { text: "Questions sent" }), el("th", { text: "Answered" }),
        el("th", { class: "r", text: "Questions" }), el("th", { class: "r", text: "Cost" }))),
      el("tbody", null, runs.slice().reverse().map(function (r) {
        return el("tr", null,
          el("td", null, el("a", { href: recordUrl(r.run), target: "_blank", rel: "noopener", text: r.run })),
          el("td", { text: r.asked ? r.asked.replace("T", " ").replace("Z", " UTC") : "" }),
          el("td", { text: r.error ? "Failed: " + r.error : r.answered ? r.answered.replace("T", " ").replace("Z", " UTC") : "" }),
          el("td", { class: "r", text: String(r.n) }),
          el("td", { class: "r", text: r.cost === null || r.cost === undefined ? "–" : "$" + r.cost.toFixed(3) }));
      })))));
  }

  // ---------------------------------------------------------------------------
  // Start
  // ---------------------------------------------------------------------------

  setupTheme();
  setupMasthead();
  renderScoreboard();
  renderCalibration();
  renderOpen();
  renderSettled();
  renderMethod();
  document.querySelectorAll("[data-filter]").forEach(function (b) {
    b.addEventListener("click", function () { openFilter = b.getAttribute("data-filter"); renderOpen(); });
  });
  window.addEventListener("hashchange", showTab);
  showTab();
})();

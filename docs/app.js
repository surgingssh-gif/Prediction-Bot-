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
  var MARKET_COLOR = "var(--series-2)";

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
  // Animation helpers (all skipped for people who prefer reduced motion)
  // ---------------------------------------------------------------------------

  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* Counts a number up from 0 to `target`, showing it with `format`. */
  function countUp(node, target, format, delay) {
    if (REDUCED || !isFinite(target) || target === 0) { node.textContent = format(target); return; }
    var duration = 1400, start = null;
    node.textContent = format(0);
    setTimeout(function () {
      requestAnimationFrame(function step(now) {
        if (start === null) start = now;
        var t = Math.min((now - start) / duration, 1);
        var eased = 1 - Math.pow(1 - t, 4);  // fast at first, then settles gently
        node.textContent = format(target * eased);
        if (t < 1) requestAnimationFrame(step);
        else node.textContent = format(target);
      });
    }, delay || 0);
  }

  /* Fades sections in as they scroll into view (and starts their animations). */
  function setupReveal() {
    var targets = document.querySelectorAll(
      ".section-head, .chart, .table-scroll, .cards > li, .stats.three, ol.calls, .duel, .verdict, .prose, .empty, .sub-head");
    if (REDUCED || !("IntersectionObserver" in window)) {
      targets.forEach(function (t) { t.classList.add("in"); });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
    targets.forEach(function (t) {
      if (!t.classList.contains("section-head")) t.classList.add("reveal");
      io.observe(t);
    });
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

  var TABS = ["portfolio", "positions", "closed", "accuracy", "method"];
  // Old links still land on the right tab.
  var OLD_TABS = { scoreboard: "portfolio", open: "positions", settled: "closed", calibration: "accuracy", analysis: "accuracy" };
  function showTab() {
    var name = (location.hash || "").slice(1);
    name = OLD_TABS[name] || name;
    if (TABS.indexOf(name) < 0) name = "portfolio";
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
    var W = opts.width || 560, H = opts.height || 250, M = { l: 48, r: 72, t: 12, b: 26 };
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

    opts.series.forEach(function (s, si) {
      var d = s.values.map(function (v, i) { return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); }).join("");
      if (n > 1 && opts.series.length === 1) {
        // A soft shaded area under a single line, fading down to the axis.
        var gid = "grad-" + Math.random().toString(36).slice(2, 8);
        root.appendChild(svg("defs", null, svg("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 },
          svg("stop", { offset: "0%", "stop-color": s.color, "stop-opacity": 0.22 }),
          svg("stop", { offset: "100%", "stop-color": s.color, "stop-opacity": 0 }))));
        root.appendChild(svg("path", { class: "area", d: d + "L" + x(n - 1).toFixed(1) + "," + (H - M.b) + "L" + x(0).toFixed(1) + "," + (H - M.b) + "Z", fill: "url(#" + gid + ")" }));
      }
      if (n > 1) root.appendChild(svg("path", { class: "draw", pathLength: 1, d: d, fill: "none", stroke: s.color, "stroke-width": 2.25, "stroke-linejoin": "round", "stroke-linecap": "round", style: "animation-delay:" + (0.15 + si * 0.2) + "s" }));
      // The latest value: a dot with a gentle pulse around it.
      root.appendChild(svg("circle", { class: "pulse", cx: x(n - 1), cy: y(s.values[n - 1]), r: 4, fill: s.color }));
      root.appendChild(svg("circle", { class: "end-dot", cx: x(n - 1), cy: y(s.values[n - 1]), r: 4.5, fill: s.color, stroke: "var(--raised)", "stroke-width": 2 }));
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
      "aria-label": "Calibration chart: average forecast against how often events happened, for the AI and the market" });
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
    [["crowd", MARKET_COLOR, "Market"], ["ai", AI_COLOR, "AI"]].forEach(function (cfg) {
      (cal[cfg[0]] || []).forEach(function (b) {
        var r = 4 + 8 * Math.sqrt(b.n / maxN);
        var g = svg("g", { tabindex: 0, "aria-label": cfg[2] + ": forecast " + pct(b.forecast) + ", happened " + pct(b.observed) + ", " + b.n + " questions" });
        g.appendChild(svg("circle", { class: "cal-dot", cx: x(b.forecast), cy: y(b.observed), r: r, fill: cfg[1], stroke: "var(--raised)", "stroke-width": 2, "fill-opacity": 0.9,
          style: "animation-delay:" + (0.2 + b.bin * 0.07 + (cfg[0] === "ai" ? 0.04 : 0)) + "s" }));
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
      el("span", null, keyDot(MARKET_COLOR), "Market price"));
    append(clear(container), el("div", { class: "chart" }, legend, holder));
  }

  /*
   * A tiny chart of the market's price over time (orange) with the AI's
   * forecast as a dashed blue line, so you can see if the market is moving
   * toward the AI. The scale zooms in on the prices so small moves show.
   */
  function sparkline(row, width, height) {
    var W = width || 120, H = height || 34, P = 4;
    var pts = (row.spark || []).filter(function (p) { return p[1] !== null && p[1] !== undefined; });
    if (!pts.length) return null;
    var vals = pts.map(function (p) { return p[1]; }).concat([row.ai]);
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals);
    if (hi - lo < 0.1) { var mid = (hi + lo) / 2; lo = mid - 0.05; hi = mid + 0.05; }
    var x = function (i) { return pts.length === 1 ? W - P : P + i * (W - 2 * P) / (pts.length - 1); };
    var y = function (v) { return P + (hi - v) * (H - 2 * P) / (hi - lo); };
    var first = pts[0][1], last = pts[pts.length - 1][1];
    var root = svg("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, class: "spark", role: "img",
      "aria-label": "Market price went from " + pct(first) + " to " + pct(last) + "; the AI said " + pct(row.ai) });
    root.appendChild(svg("line", { x1: P, x2: W - P, y1: y(row.ai), y2: y(row.ai), stroke: AI_COLOR, "stroke-width": 1.5, "stroke-dasharray": "3 3" }));
    if (pts.length > 1) {
      root.appendChild(svg("path", { class: "draw", pathLength: 1, d: pts.map(function (p, i) { return (i ? "L" : "M") + x(i).toFixed(1) + "," + y(p[1]).toFixed(1); }).join(""),
        fill: "none", stroke: MARKET_COLOR, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    }
    root.appendChild(svg("circle", { cx: x(pts.length - 1), cy: y(last), r: 3, fill: MARKET_COLOR, stroke: "var(--paper)", "stroke-width": 1.5 }));
    return root;
  }

  /* How far the market has moved toward (+) or away from (-) the AI, in points. */
  function moveText(row) {
    if (row.latest === undefined || row.latest === null) return "no newer price yet";
    var pts = Math.round((row.latest - row.crowd) * 100);
    if (pts === 0) return "unchanged";
    var toward = (row.ai > row.crowd) === (pts > 0);
    return (pts > 0 ? "+" : "−") + Math.abs(pts) + " pts, " + (toward ? "toward" : "away from") + " the AI";
  }

  // ---------------------------------------------------------------------------
  // Portfolio (the front page)
  // ---------------------------------------------------------------------------

  function stat(label, value, hint, cls) {
    return el("div", { class: "stat" }, el("div", { class: "label", text: label }),
      el("div", { class: "value" + (cls ? " " + cls : ""), text: value }), el("div", { class: "hint", text: hint }));
  }
  function upDown(x) { return x > 0 ? "up" : x < 0 ? "down" : null; }

  /* The price of the side we bought (YES price, or 1 - YES price for NO). */
  function sidePrice(bet, yesPrice) { return bet.side === "YES" ? yesPrice : 1 - yesPrice; }
  function cents(p) { return Math.round(p * 100) + "¢"; }

  function renderPortfolio() {
    var start = portfolio.start || 1000;
    var value = portfolio.marked_equity !== undefined ? portfolio.marked_equity : portfolio.equity;
    var total = value - start;
    var realized = portfolio.pnl || 0;
    var unreal = portfolio.unrealized || 0;

    var hero = document.getElementById("hero-pnl");
    hero.className = "hero-num " + (upDown(total) || "");
    countUp(hero, total, function (v) { return money(v, true); }, 150);
    document.querySelector(".hero").classList.add(total >= 0 ? "is-up" : "is-down");
    document.getElementById("hero-sub").textContent = (total >= 0 ? "Up " : "Down ") +
      Math.abs(total / start * 100).toFixed(1) + "% on " + money(start) + " of paper money. " +
      money(realized, true) + " from settled bets, " + money(unreal, true) + " on open bets at today's market prices.";
    append(clear(document.getElementById("hero-side")),
      el("div", null, "Account value", el("strong", { id: "hero-value", text: money(value) })));
    countUp(document.getElementById("hero-value"), value, function (v) { return money(v); }, 150);

    var cash = portfolio.cash || 0;
    append(clear(document.getElementById("pstats")), [
      stat("Settled profit", money(realized, true), (portfolio.settled_bets || 0) + " bet" + (portfolio.settled_bets === 1 ? "" : "s") + " closed", upDown(realized)),
      stat("Open profit", money(unreal, true), (portfolio.open_bets || 0) + " open at today's prices", upDown(unreal)),
      stat("Win rate", portfolio.settled_bets ? Math.round(portfolio.wins / portfolio.settled_bets * 100) + "%" : "–",
        portfolio.settled_bets ? portfolio.wins + " of " + portfolio.settled_bets + " bets won" : "no bets settled yet", null),
      stat("Cash available", money(cash), cash < 1 ? "all money is in open bets" : money(portfolio.open_cost || 0) + " in open bets", null),
      stat("Fees paid", money(portfolio.fees || 0), "Polymarket's taker fees", null),
    ]);

    // Account value over time.
    var acct = DATA.account || [];
    var ac = document.getElementById("account-chart");
    if (acct.length > 1) {
      lineChart(ac, {
        label: "Paper account value over time",
        // Wide on computers; narrower on phones so the labels stay readable.
        width: window.innerWidth < 760 ? 400 : 1060, height: window.innerWidth < 760 ? 260 : 300,
        series: [{ name: "Account value", short: money(acct[acct.length - 1].value), color: AI_COLOR, values: acct.map(function (p) { return p.value; }) }],
        xLabel: function (i) { return shortDate(acct[i].date); },
        yFormat: function (v, long) { return long ? money(v) : "$" + Math.round(v).toLocaleString("en-US"); },
        ref: { value: start, label: "starting $1,000" },
      });
    } else {
      append(clear(ac), el("p", { class: "empty", text: "This chart starts after the first full day of trading." }));
    }

    // Open positions, soonest to close first.
    var open = (DATA.open || []).filter(function (r) { return r.bet; });
    document.getElementById("positions-sub").textContent = open.length + " open · " + money(portfolio.open_cost || 0) + " invested · soonest to close first";
    var pc = clear(document.getElementById("positions"));
    if (!open.length) {
      pc.appendChild(el("p", { class: "empty", text: "No open positions." }));
    } else {
      var rows = open.map(function (r) {
        var b = r.bet;
        var now = r.latest !== undefined ? sidePrice(b, r.latest) : null;
        var val = b.value !== undefined ? b.value : b.cost;
        var pl = val - b.cost;
        return el("tr", null,
          el("td", null, r.url ? el("a", { href: r.url, target: "_blank", rel: "noopener", text: r.q }) : r.q,
            el("div", { class: "row-meta", text: r.topic + " · AI " + pct(r.ai) + " vs market " + pct(r.crowd) })),
          el("td", { class: "nowrap" }, el("span", { class: "side-tag", text: b.side }), " @ " + cents(b.price)),
          el("td", { class: "r" }, el("div", { class: "now-cell" }, sparkline(r, 64, 24), el("span", { text: now === null ? "–" : cents(now) }))),
          el("td", { class: "r hide-sm", text: money(b.cost) }),
          el("td", { class: "r hide-sm", text: money(val) }),
          el("td", { class: "r nowrap " + (upDown(pl) || ""), text: money(pl, true) }),
          el("td", { class: "r nowrap hide-sm", text: shortDate(r.end).replace(/, \d{4}$/, "") }));
      });
      pc.appendChild(el("div", { class: "table-scroll" }, el("table", { class: "data ptable" },
        el("thead", null, el("tr", null, el("th", { text: "Market" }), el("th", { text: "Position" }), el("th", { class: "r", text: "Now" }),
          el("th", { class: "r hide-sm", text: "Cost" }), el("th", { class: "r hide-sm", text: "Value" }),
          el("th", { class: "r", text: "Profit" }), el("th", { class: "r hide-sm", text: "Closes" }))),
        el("tbody", null, rows))));
      pc.appendChild(el("p", { class: "chart-note" }, "“Now” is the market price of the side we hold. Open profit isn't final until the question settles. ",
        el("a", { href: "#positions", text: "Reasoning and news for every position" })));
    }

    // Recently closed bets.
    var closed = (DATA.settled || []).filter(function (r) { return r.bet && r.pnl !== undefined; }).slice(0, 10);
    var cc = clear(document.getElementById("recent-closed"));
    if (!closed.length) {
      cc.appendChild(el("p", { class: "empty", text: "No bets have settled yet." }));
    } else {
      cc.appendChild(el("div", { class: "table-scroll" }, el("table", { class: "data ptable" },
        el("thead", null, el("tr", null, el("th", { text: "Market" }), el("th", { text: "Position" }), el("th", { text: "Result" }),
          el("th", { class: "r hide-sm", text: "Cost" }), el("th", { class: "r", text: "Profit" }), el("th", { class: "r hide-sm", text: "Settled" }))),
        el("tbody", null, closed.map(function (r) {
          var result = r.outcome === "void" ? "Cancelled" : r.outcome === 1 ? "YES" : "NO";
          return el("tr", null,
            el("td", null, r.url ? el("a", { href: r.url, target: "_blank", rel: "noopener", text: r.q }) : r.q,
              el("div", { class: "row-meta", text: r.topic + " · AI " + pct(r.ai) + " vs market " + pct(r.crowd) })),
            el("td", { class: "nowrap" }, el("span", { class: "side-tag", text: r.bet.side }), " @ " + cents(r.bet.price)),
            el("td", { text: result }),
            el("td", { class: "r hide-sm", text: money(r.bet.cost) }),
            el("td", { class: "r nowrap " + (upDown(r.pnl) || ""), text: money(r.pnl, true) }),
            el("td", { class: "r nowrap hide-sm", text: shortDate(r.settled).replace(/, \d{4}$/, "") }));
        })))));
    }

    // What's working: settled bets broken down.
    var bets = DATA.bets || {};
    var bc = clear(document.getElementById("bet-breakdown"));
    if (!(bets.by_side || []).length) {
      bc.appendChild(el("p", { class: "empty", text: "Appears once paper bets settle." }));
    } else {
      var toRows = function (groups) {
        return groups.map(function (g) {
          return [g.label, String(g.n), g.wins + " (" + Math.round(g.wins / g.n * 100) + "%)", money(g.pnl, true), g.roi === null ? "–" : (g.roi > 0 ? "+" : "") + g.roi + "%"];
        });
      };
      var head = ["", "Bets", "Won", "Profit", "Return"];
      append(bc, [
        el("h3", { class: "sub-head", text: "By size of disagreement with the market" }), simpleTable(head, toRows(bets.by_gap || [])),
        el("h3", { class: "sub-head", text: "By side" }), simpleTable(head, toRows(bets.by_side || [])),
        el("h3", { class: "sub-head", text: "By topic" }), simpleTable(head, toRows(bets.by_topic || [])),
      ]);
    }
  }

  // ---------------------------------------------------------------------------
  // Accuracy: the AI's forecasts vs. the market's prices
  // ---------------------------------------------------------------------------

  function renderAccuracy() {
    var n = stats.n || 0;
    document.getElementById("acc-deck").textContent =
      "Before each bet, the AI writes down its own probability without seeing the market's price. Here it's scored against " +
      "the market price at that moment, on the same questions. " +
      (n ? n + " questions have settled so far." : "Scores appear as questions settle.");

    function side(name, color, value, sub) {
      return el("div", { class: "side" },
        el("h3", null, keyDot(color), name),
        el("div", { class: "big", text: brier(value), "data-count": value === undefined || value === null ? null : value }),
        el("div", { class: "sub", text: sub }));
    }
    append(clear(document.getElementById("duel")), [
      side("The AI", AI_COLOR, stats.ai_brier, n ? "closer on " + stats.ai_closer + " of " + n : "Brier score"),
      el("div", { class: "vs", text: "vs." }),
      side("The Market", MARKET_COLOR, stats.crowd_brier, n ? "closer on " + stats.crowd_closer + " of " + n : "Brier score"),
    ]);

    document.querySelectorAll("#duel .big[data-count]").forEach(function (node, i) {
      countUp(node, parseFloat(node.getAttribute("data-count")), brier, 200 + i * 120);
    });

    var verdict = clear(document.getElementById("verdict"));
    if (!n) {
      append(verdict, ["The ", el("strong", { text: "Brier score" }), " measures forecast error: 0 is perfect, 0.25 is what you'd get by always saying 50%, and lower is better."]);
    } else {
      var leader = stats.diff < 0 ? "the AI" : stats.diff > 0 ? "the market" : "neither side";
      var range = stats.ci_low === null ? "" : " The 95% range for the difference (AI minus market) is " +
        stats.ci_low.toFixed(3) + " to " + stats.ci_high.toFixed(3) + ".";
      var call;
      if (n < 30) call = el("strong", { text: "Too early to call." });
      else if (stats.ci_high < 0) call = el("strong", { text: "The AI is ahead, by more than luck alone would likely explain." });
      else if (stats.ci_low > 0) call = el("strong", { text: "The market is ahead, by more than luck alone would likely explain." });
      else call = el("strong", { text: "Too close to call." });
      append(verdict, [call, " Lower is better; so far " + leader + " has the lower score." + range +
        (n < 100 ? " With fewer than about 100 settled questions, differences like this can easily be luck." : "")]);
    }

    var running = DATA.running || [];
    var rc = document.getElementById("running-chart");
    if (running.length) {
      lineChart(rc, {
        label: "Average Brier score after each settled question, AI versus market",
        series: [
          { name: "AI", color: AI_COLOR, values: running.map(function (p) { return p.ai; }) },
          { name: "Market", color: MARKET_COLOR, values: running.map(function (p) { return p.crowd; }) },
        ],
        xLabel: function (i, long) { return long ? "After " + running[i].n + " settled · " + shortDate(running[i].date) : String(running[i].n); },
        yFormat: function (v) { return v.toFixed(3); },
        ref: { value: 0.25, label: "always saying 50%" },
        floor: 0,
        note: "Across: number of settled questions. Each point averages everything settled so far.",
      });
    } else {
      append(clear(rc), el("p", { class: "empty", text: "This chart starts once the first questions settle." }));
    }

    var topics = DATA.topics || [];
    var tc = clear(document.getElementById("topics"));
    if (!topics.length) {
      tc.appendChild(el("p", { class: "empty", text: "Topic results appear once questions settle." }));
    } else {
      tc.appendChild(simpleTable(["Topic", "Settled", "AI", "Market", "Better"], topics.map(function (t) {
        return [t.topic, String(t.n), brier(t.ai_brier), brier(t.crowd_brier), t.diff < 0 ? "AI" : t.diff > 0 ? "Market" : "Tie"];
      })));
    }

    renderCalibration();
    renderAnalysis();
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
      el("thead", null, el("tr", null, el("th", { text: "Bucket" }), el("th", { class: "r", text: "AI" }), el("th", { class: "r", text: "Market" }))),
      el("tbody", null, rows))));
  }

  // ---------------------------------------------------------------------------
  // Question cards
  // ---------------------------------------------------------------------------

  /* The 0-100% strip with the AI's dot, the market's dot and (if settled) the result. */
  function compareStrip(row) {
    var lo = Math.min(row.ai, row.crowd), hi = Math.max(row.ai, row.crowd);
    var track = el("div", { class: "compare-track", "aria-hidden": "true" },
      el("div", { class: "compare-line" }),
      el("div", { class: "compare-gap", style: { left: lo * 100 + "%", width: (hi - lo) * 100 + "%" } }),
      row.outcome === 0 || row.outcome === 1 ? el("div", { class: "compare-outcome", style: { left: row.outcome * 100 + "%" } }) : null,
      el("div", { class: "compare-dot", style: { left: row.crowd * 100 + "%", background: MARKET_COLOR } }),
      el("div", { class: "compare-dot", style: { left: row.ai * 100 + "%", background: AI_COLOR } }));
    var gap = Math.round(Math.abs(row.ai - row.crowd) * 100);
    return el("div", { class: "compare" }, track,
      el("div", { class: "compare-scale" }, el("span", { text: "0% (No)" }), el("span", { text: "50%" }), el("span", { text: "100% (Yes)" })),
      el("div", { class: "compare-legend" },
        el("span", null, keyDot(AI_COLOR), " AI says ", el("strong", { text: pct(row.ai) })),
        el("span", null, keyDot(MARKET_COLOR), " Market said ", el("strong", { text: pct(row.crowd) })),
        el("span", { text: gap + "-point gap" })),
      row.outcome === undefined ? el("div", { class: "live" }, sparkline(row, 140, 34),
        el("span", null, "Market now ", el("strong", { text: row.latest !== undefined ? pct(row.latest) : pct(row.crowd) }),
          el("span", { class: "muted", text: " · " + moveText(row) }))) : null);
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
        badges.push(" ", el("span", { class: "badge " + (tie ? "plain" : aiWon ? "win" : "loss"), text: tie ? "Tie" : aiWon ? "AI was closer" : "Market was closer" }));
      }
      right = el("div", { class: "pnl" }, badges,
        row.pnl !== undefined ? el("div", { class: row.pnl > 0 ? "up" : row.pnl < 0 ? "down" : "", style: { marginTop: "8px" } },
          money(row.pnl, true), el("small", { text: "paper bet " + row.bet.side })) : null);
    } else if (row.bet) {
      right = el("span", { class: "badge bet", text: "Paper bet: " + row.bet.side });
    }

    var betLine = row.bet
      ? el("p", { class: "bet-line" }, "Bought ", el("strong", { text: row.bet.side }), " at " + Math.round(row.bet.price * 100) +
        "¢ a share: " + row.bet.shares + " shares for " + money(row.bet.cost) + " including " + money(row.bet.fee) + " in fees." +
        (row.bet.value !== undefined && row.outcome === undefined ? " Worth " + money(row.bet.value) + " at today's price (" +
          money(row.bet.value - row.bet.cost, true) + ")." : ""))
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
        ? "No paper bets are open right now. The AI only bets when it disagrees with the market by " + Math.round(DATA.settings.min_edge * 100) + "+ points."
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
  // Analysis
  // ---------------------------------------------------------------------------

  function simpleTable(headers, rows) {
    return el("div", { class: "table-scroll" }, el("table", { class: "data" },
      el("thead", null, el("tr", null, headers.map(function (h, i) { return el("th", { class: i ? "r" : null, text: h }); }))),
      el("tbody", null, rows.map(function (r) {
        return el("tr", null, r.map(function (c, i) { return el("td", { class: i ? "r" : null, text: c }); }));
      }))));
  }

  function renderAnalysis() {
    // Market movement
    var mv = DATA.movement || { n: 0 };
    var mc = clear(document.getElementById("movement"));
    if (!mv.n) {
      mc.appendChild(el("p", { class: "empty", text: "This needs at least one day of price changes after a forecast." }));
    } else {
      var flat = mv.n - mv.toward - mv.away;
      append(mc, [
        el("div", { class: "stats three" },
          el("div", { class: "stat" }, el("div", { class: "label", text: "Moved toward the AI" }), el("div", { class: "value", text: String(mv.toward) }), el("div", { class: "hint", text: Math.round(mv.toward / mv.n * 100) + "% of " + mv.n })),
          el("div", { class: "stat" }, el("div", { class: "label", text: "Moved away" }), el("div", { class: "value", text: String(mv.away) }), el("div", { class: "hint", text: Math.round(mv.away / mv.n * 100) + "% of " + mv.n })),
          el("div", { class: "stat" }, el("div", { class: "label", text: "Average move" }), el("div", { class: "value " + (mv.avg_pts > 0 ? "up" : mv.avg_pts < 0 ? "down" : ""), text: (mv.avg_pts > 0 ? "+" : "") + mv.avg_pts.toFixed(1) + " pts" }), el("div", { class: "hint", text: flat + " barely moved" }))),
        el("p", { class: "chart-note", text: "Compares each market's price when the AI forecast it with the latest price before it settled. Positive means the market moved in the direction the AI predicted. Questions where the AI was within 2 points of the market are left out." }),
      ]);
    }

    // Three forecasters
    var fc = clear(document.getElementById("forecasters"));
    if (!stats.n) {
      fc.appendChild(el("p", { class: "empty", text: "Appears once questions settle." }));
    } else {
      var list = [["The AI", stats.ai_brier], ["The market", stats.crowd_brier], ["Blend (average of both)", stats.blend_brier], ["Always saying 50%", 0.25]];
      fc.appendChild(simpleTable(["Forecaster", "Brier score", "vs. the market"], list.map(function (f) {
        var d = f[1] - stats.crowd_brier;
        return [f[0], brier(f[1]), f[0] === "The market" ? "–" : (d < 0 ? "better by " : d > 0 ? "worse by " : "same ") + Math.abs(d).toFixed(3)];
      })));
    }

    // Best and worst calls
    [["best", "No settled question where the AI beat the market yet."], ["worst", "No settled question where the market beat the AI yet."]].forEach(function (cfg) {
      var box = clear(document.getElementById(cfg[0] + "-calls"));
      var rows = DATA[cfg[0]] || [];
      if (!rows.length) { box.appendChild(el("p", { class: "empty", text: cfg[1] })); return; }
      box.appendChild(el("ol", { class: "calls" }, rows.map(function (r) {
        var result = r.outcome === 1 ? "YES" : "NO";
        return el("li", null, r.url ? el("a", { href: r.url, target: "_blank", rel: "noopener", text: r.q }) : r.q,
          el("div", { class: "row-meta", text: "Resolved " + result + " · AI " + pct(r.ai) + " vs market " + pct(r.crowd) +
            " · Brier " + brier(r.ai_brier) + " vs " + brier(r.crowd_brier) }));
      })));
    });
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
      p("Can an AI predict real-world events better than the market? Prediction markets like Polymarket let people trade on " +
        "questions such as “Will the Fed cut rates in October?”. A share pays $1 if the answer is Yes, so its price works as " +
        "the market's probability: 62¢ means about a 62% chance. Markets like these are hard to beat, which makes them a tough benchmark."),
      h("Each day"),
      el("ol", null, [
        li("About " + s.per_day + " new questions are picked from Polymarket's most-traded markets. Each one must be about the " +
          "economy, politics, tech, business, science, weather or entertainment; close in " + s.min_days + " to " + s.max_days +
          " days; have at least $" + (s.min_volume || 0).toLocaleString() + " traded, a tight price spread and written resolution rules; " +
          "and not be nearly certain (the market must be between " + pct(s.min_price) + " and " + pct(s.max_price) + "). " +
          "Sports, esports, crypto price bets and questions about Anthropic (the AI's maker) are skipped. No more than 3 per topic per day."),
        li("For each question, the top " + s.headlines + " Google News headlines from the last " + s.lookback.replace("d", " days") +
          " are collected. Headlines that mention prediction markets, betting or odds are thrown out, so the AI can't see the market's price."),
        li("All the questions go to Claude (" + DATA.model + ", " + DATA.effort + " effort) in one request. It sees each question, its " +
          "rules and its news, but never the market price. It answers with a probability and a short explanation. " +
          "Each question is forecast once, and the same model is used for the whole experiment."),
        li("The forecasts are saved and committed to GitHub straight away, with a timestamp, before any result is known. " +
          "The files are never edited afterwards (the “Original record” links show their history)."),
      ]),
      h("Scoring"),
      p("The Brier score is the squared gap between a forecast and what happened (1 for Yes, 0 for No), averaged over all " +
        "questions. Lower is better: 0 is perfect, and always saying 50% scores 0.25. Both the AI and the market are scored on exactly " +
        "the same questions. The market's forecast is the market's midpoint price at the moment the questions were picked, " +
        "which is also when the AI's news was gathered, so both sides had the same information at the same time. " +
        "Cancelled questions, and any that closed before the AI's answer arrived, are left out."),
      p("The scoreboard also shows a 95% range for the difference between the two scores. If that range includes zero, " +
        "the difference could just be luck."),
      h("Other measures"),
      el("ul", null, [
        li("Blend: a third forecaster that averages the AI and the market, scored the same way. Combining independent forecasts often beats each one alone."),
        li("Market movement: the market's price is recorded once a day while a question is open. If prices tend to move toward the AI's forecast after it's made, the AI may be picking up information before the market does. This is an early signal only; the Brier score on settled questions is the real test."),
        li("Open bets are also valued at today's market midpoint (\u201cAt today's prices\u201d). That figure isn't profit until the question settles."),
      ]),
      h("Paper trading (fake money)"),
      p("The AI starts with $" + (s.start || 1000).toLocaleString() + " of pretend money. It bets only when its probability " +
        "is at least " + Math.round(s.min_edge * 100) + " points away from the price it would actually pay. It buys at the current " +
        "asking price (not the midpoint) and pays Polymarket's real taker fee, so the results aren't flattered. " +
        "Bet size uses the Kelly formula, scaled down to " + s.kelly * 100 + "% of what Kelly suggests, and never more than " +
        s.max_bet * 100 + "% of the bankroll on one question. At most " + Math.round((s.daily_budget || 0.1) * 100) +
        "% of the available cash goes into new bets each day; if a day's bets add up to more, they're all scaled down by the same proportion. " +
        "There are also never more than " + (s.per_story || 2) + " open bets on the same real-world story (questions that share a name, " +
        "like \u201cBrazil\u201d or \u201cGemini\u201d), with the biggest disagreements getting priority. " +
        "(Both limits were added on Oct 5, 2026: within four days the whole bankroll was tied up, five bets of it on one election.)"),
      h("Limits to keep in mind"),
      el("ul", null, [
        li("Small samples are noisy. Expect wild swings until at least 100 questions have settled."),
        li("The news filter can't catch everything. An article might still mention, say, interest-rate futures pricing, " +
          "which is market-like information from a different market."),
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
  renderPortfolio();
  renderAccuracy();
  renderOpen();
  renderSettled();
  renderMethod();
  document.querySelectorAll("[data-filter]").forEach(function (b) {
    b.addEventListener("click", function () { openFilter = b.getAttribute("data-filter"); renderOpen(); });
  });
  window.addEventListener("hashchange", showTab);
  showTab();
  setupReveal();
})();

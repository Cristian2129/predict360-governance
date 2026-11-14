/* Predict360 stress simulator (US-10, B12b-2). Inlined into index.html by dashboard_render.py.
 *
 * A hypothetical scenario: it never changes the verdict, which was fixed by the paired
 * bootstrap with the assumptions recorded in the evidence record (acta).
 *
 * The pure functions below mirror src/predict360/evaluator.py line by line, in the same
 * floating point order, so that with the assumptions of the acta they reproduce the
 * evaluator's numbers exactly (tests/test_simulator_parity.py runs them with Node 20 in CI):
 *   gain(captured)   = effectiveness * loss_given_event * captured        (_gain_cop_m)
 *   cost(K)          = K * cost_per_contact_cop / 1,000,000               (_contact_cost_cop_m)
 *   appliedPoint     = last published point with k <= K requested         (applied_point)
 *   randomNet        = gain(total * (K / N)) - cost(K)                    (random_baseline)
 *   kStar            = best published point, the first one on ties        (_published)
 */
(function (root) {
  "use strict";

  var EPS = 1e-9;
  var COP_PER_MILLION = 1000000;

  function gain(capturedCopM, a) {
    return a.action_effectiveness * a.loss_given_event * capturedCopM;
  }

  function cost(kClients, a) {
    return kClients * a.cost_per_contact_cop / COP_PER_MILLION;
  }

  function netValue(point, a) {
    return gain(point.captured_cop_m, a) - cost(point.k, a);
  }

  function appliedPoint(curve, kRequested) {
    var chosen = null;
    for (var i = 0; i < curve.length; i++) {
      if (curve[i].k <= kRequested + EPS) { chosen = curve[i]; }
    }
    return chosen;
  }

  function kStar(curve, a) {
    var best = null, bestNet = null;
    for (var i = 0; i < curve.length; i++) {
      var net = netValue(curve[i], a);
      if (best === null || net > bestNet) { best = curve[i]; bestNet = net; }
    }
    return { k: best.k, captured_cop_m: best.captured_cop_m, net_value_cop_m: bestNet };
  }

  function randomNet(totalCopM, nClients, kApplied, a) {
    var share = kApplied / nClients;
    return gain(totalCopM * share, a) - cost(kApplied, a);
  }

  /* One label at one set of assumptions: what the stress view shows. */
  function scenario(label, rule, a) {
    var rows = [], ruleNet = null, random = null;
    for (var i = 0; i < label.models.length; i++) {
      var m = label.models[i];
      var point = appliedPoint(m.curve, a.capacity_share * m.n_clients);
      var star = kStar(m.curve, a);
      var row = { model_id: m.model_id, k_applied: point.k, net: netValue(point, a), k_star: star.k,
                  below_k_star: star.k > point.k };
      if (m.model_id === rule) { ruleNet = row.net; }
      if (random === null) { random = randomNet(m.event_exposure_cop_m, m.n_clients, point.k, a); }
      rows.push(row);
    }
    for (var j = 0; j < rows.length; j++) {
      rows[j].difference = (ruleNet === null || rows[j].model_id === rule) ? null : rows[j].net - ruleNet;
    }
    return { rows: rows, random: random };
  }

  /* What the curve shows at some assumptions: every model's net value per published point,
     its K*, the random line (0 to the last point) and the vertical range (always with 0). */
  function curveGeometry(label, a) {
    var series = [], stars = [], values = [0];
    for (var i = 0; i < label.models.length; i++) {
      var m = label.models[i], line = [];
      for (var j = 0; j < m.curve.length; j++) {
        var net = netValue(m.curve[j], a);
        line.push([m.curve[j].k, net]);
        values.push(net);
      }
      series.push({ model_id: m.model_id, points: line });
      var star = kStar(m.curve, a);
      stars.push({ model_id: m.model_id, k: star.k, net: star.net_value_cop_m });
    }
    var last = label.models[0].curve[label.models[0].curve.length - 1];
    var randomEnd = [last.k, netValue(last, a)];
    values.push(randomEnd[1]);
    return { series: series, stars: stars, random: [[0, 0], randomEnd],
             low: Math.min.apply(null, values), high: Math.max.apply(null, values) };
  }

  /* With the acta's assumptions the simulator must give the evaluator's numbers; otherwise
     the page disables it instead of showing numbers that disagree with the pipeline. */
  function selfCheck(sim) {
    var a = sim.defaults, problems = [];
    var close = function (x, y) { return Math.abs(x - y) <= 1e-6; };
    Object.keys(sim.labels).forEach(function (name) {
      sim.labels[name].models.forEach(function (m) {
        var where = name + "." + m.model_id;
        var point = appliedPoint(m.curve, a.capacity_share * m.n_clients);
        if (!point || point.k !== m.k_applied) { problems.push(where + ": k_applied"); return; }
        if (!close(netValue(point, a), m.at_k_net_value_cop_m)) { problems.push(where + ": net value at K"); }
        if (kStar(m.curve, a).k !== m.k_star_k) { problems.push(where + ": K*"); }
        if (!close(randomNet(m.event_exposure_cop_m, m.n_clients, point.k, a), m.random_net_value_cop_m)) {
          problems.push(where + ": random");
        }
        m.curve.forEach(function (p) {
          if (!close(netValue(p, a), p.net_value_cop_m)) { problems.push(where + ": curve point " + p.k); }
        });
      });
    });
    return problems;
  }

  /* Same display rules as formatting.py (es): whole millions from a thousand up, else one decimal. */
  function groupEs(value, decimals) {
    var fixed = Math.abs(value).toFixed(decimals).split(".");
    var whole = fixed[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (value < 0 ? "-" : "") + whole + (decimals ? "," + fixed[1] : "");
  }

  function formatCopM(value) {
    return "COP " + groupEs(value, Math.abs(value) >= 1000 ? 0 : 1) + " M";
  }

  function formatCount(value) {
    return groupEs(value, 0);
  }

  var api = { gain: gain, cost: cost, netValue: netValue, appliedPoint: appliedPoint, kStar: kStar,
              randomNet: randomNet, scenario: scenario, curveGeometry: curveGeometry, selfCheck: selfCheck,
              formatCopM: formatCopM,
              formatCount: formatCount };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;          /* Node: parity tests */
    return;
  }
  root.Predict360Sim = api;

  /* --- browser ------------------------------------------------------------------------- */
  function ready(fn) {
    if (document.readyState !== "loading") { fn(); } else { document.addEventListener("DOMContentLoaded", fn); }
  }

  ready(function () {
    var source = document.getElementById("sim-data");
    if (!source) { return; }
    var sim = JSON.parse(source.textContent);
    var form = document.getElementById("sim-controls");
    var status = document.getElementById("sim-status");
    var problems = selfCheck(sim);
    if (problems.length) {
      status.hidden = false;
      status.textContent = "El simulador no coincide con el evaluador (" + problems.length +
        " diferencias): queda deshabilitado y se muestran los valores del acta.";
      Array.prototype.forEach.call(form.elements, function (el) { el.disabled = true; });
      return;
    }
    var inputs = {
      capacity_share: document.getElementById("sim-capacity"),
      action_effectiveness: document.getElementById("sim-effectiveness"),
      cost_per_contact_cop: document.getElementById("sim-cost")
    };
    var set = function (selector, text) {
      var el = document.querySelector(selector);
      if (el) { el.textContent = text; }
    };

    function current() {
      return {
        capacity_share: Number(inputs.capacity_share.value) / 100,
        action_effectiveness: Number(inputs.action_effectiveness.value) / 100,
        loss_given_event: sim.defaults.loss_given_event,
        cost_per_contact_cop: Number(inputs.cost_per_contact_cop.value)
      };
    }

    function update() {
      var a = current();
      set("#sim-capacity-out", groupEs(a.capacity_share * 100, 0) + " %");
      set("#sim-effectiveness-out", groupEs(a.action_effectiveness * 100, 0) + " %");
      set("#sim-cost-out", "COP " + formatCount(a.cost_per_contact_cop));
      Object.keys(sim.labels).forEach(function (name) {
        var result = scenario(sim.labels[name], sim.rule, a);
        set('[data-sim-net="' + name + '.random"]', formatCopM(result.random));
        result.rows.forEach(function (row) {
          var key = name + "." + row.model_id;
          set('[data-sim-net="' + key + '"]', formatCopM(row.net));
          set('[data-sim-kapplied="' + key + '"]', formatCount(row.k_applied));
          set('[data-sim-kstar="' + key + '"]', formatCount(row.k_star));
          set('[data-sim-diff="' + key + '"]', row.difference === null ? "—" : formatCopM(row.difference));
          var slot = document.querySelector('[data-sim-slot="' + key + '"]');
          if (slot) {
            slot.hidden = !row.below_k_star;
            if (row.below_k_star) { slot.setAttribute("data-sim-warning", key); }
            else { slot.removeAttribute("data-sim-warning"); }
            slot.textContent = row.below_k_star
              ? row.model_id + ": la capacidad (" + formatCount(row.k_applied) + " clientes) queda por debajo de K* (" +
                formatCount(row.k_star) + "): más capacidad de gestión aumentaría el valor neto."
              : "";
          }
        });
        redraw(name, a, result.rows.length ? result.rows[0].k_applied : null);
      });
    }

    /* The whole curve follows the controls: lines, K*, random line, zero axis and the range. */
    function redraw(name, a, kApplied) {
      var svg = document.querySelector('svg[data-curve="' + name + '"]');
      if (!svg) { return; }
      var x0 = Number(svg.getAttribute("data-x0")), xscale = Number(svg.getAttribute("data-xscale"));
      var top = Number(svg.getAttribute("data-top")), plotH = Number(svg.getAttribute("data-plot-h"));
      var g = curveGeometry(sim.labels[name], a);
      var span = (g.high - g.low) || 1;
      var X = function (k) { return (x0 + xscale * k).toFixed(1); };
      var Y = function (v) { return (top + (g.high - v) / span * plotH).toFixed(1); };
      var path = function (points) {
        return points.map(function (p) { return X(p[0]) + "," + Y(p[1]); }).join(" ");
      };
      g.series.forEach(function (s) {
        var line = svg.querySelector('[data-series="' + s.model_id + '"]');
        if (line) { line.setAttribute("points", path(s.points)); }
      });
      g.stars.forEach(function (s) {
        var dot = svg.querySelector('[data-kstar="' + s.model_id + '"]');
        if (dot) {
          dot.setAttribute("cx", X(s.k));
          dot.setAttribute("cy", Y(s.net));
          var title = dot.querySelector("title");
          if (title) { title.textContent = "K* " + s.model_id + ": " + formatCount(s.k) + " clientes, " + formatCopM(s.net); }
        }
      });
      var random = svg.querySelector('[data-series="random"]');
      if (random) { random.setAttribute("points", path(g.random)); }
      var zero = svg.querySelector("[data-zero]");
      if (zero) { zero.setAttribute("y1", Y(0)); zero.setAttribute("y2", Y(0)); }
      var high = svg.querySelector('[data-tick="high"]'), low = svg.querySelector('[data-tick="low"]');
      if (high) { high.textContent = formatCopM(g.high); high.setAttribute("y", (Number(Y(g.high)) + 4).toFixed(1)); }
      if (low) { low.textContent = formatCopM(g.low); low.setAttribute("y", (Number(Y(g.low)) + 4).toFixed(1)); }
      var capacity = svg.querySelector("[data-capacity-line]");
      if (capacity && kApplied !== null) {
        capacity.setAttribute("x1", X(kApplied));
        capacity.setAttribute("x2", X(kApplied));
      }
    }

    form.addEventListener("input", update);
    document.getElementById("sim-reset").addEventListener("click", function () {
      inputs.capacity_share.value = Math.round(sim.defaults.capacity_share * 100);
      inputs.action_effectiveness.value = Math.round(sim.defaults.action_effectiveness * 100);
      inputs.cost_per_contact_cop.value = sim.defaults.cost_per_contact_cop;
      update();
    });
    update();
  });
})(this);

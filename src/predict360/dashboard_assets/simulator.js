/* Predict360 «Decisión en COP» simulator (US-10). Inlined into index.html by dashboard_render.py.
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
 *   breakeven        = cost(K) / (loss_given_event * captured)            (breakeven_effectiveness)
 * story() writes every sentence of the view as dashboard_render.stress_story() does in Python,
 * and the numbers are written as formatting.py writes them (exact ties round half to even).
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

  function breakeven(capturedCopM, kApplied, a) {
    var gainPerUnit = a.loss_given_event * capturedCopM;
    if (gainPerUnit <= 0) { return null; }
    return cost(kApplied, a) / gainPerUnit;
  }

  /* One label at one set of assumptions: the rows of the technical table. */
  function scenario(label, rule, a) {
    var rows = [], ruleNet = null, random = null;
    for (var i = 0; i < label.models.length; i++) {
      var m = label.models[i];
      var point = appliedPoint(m.curve, a.capacity_share * m.n_clients);
      var star = kStar(m.curve, a);
      var row = { model_id: m.model_id, name: m.name, k_applied: point.k, net: netValue(point, a), k_star: star.k,
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

  /* Bars of net value from a zero line, highest first (mirrors _bar_layout). */
  function bars(options, bestId) {
    var low = 0, high = 0;
    options.forEach(function (o) { low = Math.min(low, o.net); high = Math.max(high, o.net); });
    var span = (high - low) || 1;
    var zero = (0 - low) / span * 100;
    var sorted = options.slice().sort(function (x, y) { return y.net - x.net; });
    return { zero: zero, rows: sorted.map(function (o) {
      var pos = (o.net - low) / span * 100;
      var tone = o.net < 0 ? "neg" : (o.id === bestId ? "best" : "other");
      return { id: o.id, name: o.name, net: o.net, tone: tone, left: Math.min(zero, pos), width: Math.abs(pos - zero) };
    }) };
  }

  function joinAnd(items) {
    return items.length === 1 ? items[0] : items.slice(0, -1).join(", ") + " y " + items[items.length - 1];
  }

  /* «capacidad de hoy» at the acta's capacity, «capacidad del escenario» away from it (mirrors _capacity_texts). */
  function capacityTexts(k, kToday, scenario) {
    if (!scenario) {
      return { barsTitle: "Valor neto llamando a " + formatCount(k) + " clientes (capacidad de hoy)",
               scope: "Con la capacidad de hoy: " + formatCount(k) + " clientes",
               capacityHeader: "Capacidad de hoy (clientes)", netHeader: "Valor neto con la capacidad de hoy",
               legendCapacity: "Capacidad de hoy",
               belowLead: "Con la capacidad de hoy (" + formatCount(k) + " clientes) quedan" };
    }
    var where = "capacidad del escenario: " + formatCount(k) + " clientes (hoy: " + formatCount(kToday) + ")";
    return { barsTitle: "Valor neto con la " + where, scope: "Con la " + where,
             capacityHeader: "Capacidad del escenario (clientes; hoy: " + formatCount(kToday) + ")",
             netHeader: "Valor neto con la capacidad del escenario", legendCapacity: "Capacidad del escenario",
             belowLead: "Con la " + where + ", quedan" };
  }

  /* Every sentence of the view for one label (mirrors _story_texts word by word). */
  function storyTexts(labelName, k, a, best, ruleOpt, recovered, costCopM, be, below, kToday, scenario) {
    var capacity = capacityTexts(k, kToday, scenario);
    var answer;
    if (best.net < 0) {
      answer = "Con su equipo de hoy, llamar no compensa el costo en " + labelName + ": la mejor opción, " +
        best.phrase + ", deja " + formatCopM(best.net) + ".";
    } else if (ruleOpt === null || ruleOpt === best) {
      answer = "Con su equipo de hoy, " + best.phrase + " deja " + formatCopM(best.net) + " netos en " + labelName + ".";
    } else {
      answer = "Con su equipo de hoy, " + best.phrase + " deja " + formatCopM(best.net) + " netos en " + labelName +
        "; " + ruleOpt.phrase + ", " + formatCopM(ruleOpt.net) + ".";
    }
    var effectiveness = formatDecimal(a.action_effectiveness * 100, 0);
    var threshold;
    if (be === null) {
      threshold = "Con " + best.phrase + ", en la lista no hay plata en riesgo: llamar no compensa con ninguna efectividad.";
    } else {
      var margin = (a.action_effectiveness - be) * 100;
      var needed = be * 100 < 1 ? "aunque se recupere menos de 1 de cada 100"
        : "mientras se recuperen al menos " + formatDecimal(be * 100, 1) + " de cada 100";
      threshold = "Con " + best.phrase + ", llamar compensa " + needed + ". Hoy suponemos " + effectiveness + ": " +
        (margin >= 0 ? "margen de " + formatDecimal(margin, 1) + " puntos." : "faltan " + formatDecimal(-margin, 1) + " puntos.");
    }
    var belowText = "";
    if (below.length) {
      belowText = capacity.belowLead + " por debajo de su mejor número " +
        "de contactos: " + joinAnd(below.map(function (b) { return b[0] + " (" + formatCount(b[1]) + ")"; })) + ".";
    }
    var texts = {
      barsTitle: capacity.barsTitle, scope: capacity.scope, capacityHeader: capacity.capacityHeader,
      netHeader: capacity.netHeader, legendCapacity: capacity.legendCapacity,
      answer: answer, k: formatCount(k), capacity: formatCount(k) + " clientes",
      who: formatCount(best.k) + " clientes", whoNote: "los de mayor riesgo según " + best.phrase,
      captured: formatCopM(best.captured), recovered: formatCopM(recovered),
      recoveredNote: "se recuperan " + effectiveness + " de cada 100",
      cost: formatCopM(costCopM),
      costNote: formatCount(best.k) + " × COP " + formatCount(a.cost_per_contact_cop),
      net: "Quedan " + formatCopM(best.net) + " netos", threshold: threshold, below: belowText
    };
    return texts;
  }

  /* What the view says for one label at some assumptions (mirrors stress_story). actaShare, when
     given, is the acta's capacity: away from it every capacity text speaks of the scenario. */
  function story(label, rule, a, randomName, actaShare) {
    var options = [], best = null, ruleOpt = null, below = [], k = null;
    for (var i = 0; i < label.models.length; i++) {
      var m = label.models[i];
      var point = appliedPoint(m.curve, a.capacity_share * m.n_clients);
      if (k === null) { k = point.k; }
      var opt = { id: m.model_id, name: m.name, phrase: m.phrase, net: netValue(point, a),
                  captured: point.captured_cop_m, k: point.k };
      options.push(opt);
      if (best === null || opt.net > best.net) { best = opt; }
      if (m.model_id === rule) { ruleOpt = opt; }
      var star = kStar(m.curve, a);
      if (star.k > point.k) { below.push([m.name, star.k]); }
    }
    var first = label.models[0];
    options.push({ id: "random", name: randomName, net: randomNet(first.event_exposure_cop_m, first.n_clients, k, a) });
    var be = breakeven(best.captured, best.k, a);
    return { best: best.id, breakeven: be, bars: bars(options, best.id),
             texts: storyTexts(label.name, k, a, best, ruleOpt, gain(best.captured, a), cost(best.k, a), be, below,
                               first.k_applied, actaShare !== undefined && a.capacity_share !== actaShare) };
  }

  /* What the curve shows at some assumptions: every model's net value per published point,
     its best number of contacts, the random line (0 to the last point) and the vertical range. */
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
      stars.push({ model_id: m.model_id, name: m.name, k: star.k, net: star.net_value_cop_m });
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

  /* Python's rounding: correctly rounded, exact ties to even. toFixed is correctly rounded but
     sends exact ties up; a double is an exact tie at d decimals iff x * 2^(d+1) is an odd integer. */
  function fixedEven(x, d) {
    var text = x.toFixed(d);
    var t = x * Math.pow(2, d + 1);
    if (Number.isInteger(t) && t % 2 === 1) {
      var n = Math.floor(x * Math.pow(10, d));
      if (n % 2 === 0) { text = (n / Math.pow(10, d)).toFixed(d); }
    }
    return text;
  }

  /* Same display rules as formatting.py (es): whole millions from a thousand up, else one decimal. */
  function groupEs(value, decimals) {
    var fixed = fixedEven(Math.abs(value), decimals).split(".");
    var whole = fixed[0].replace(/\B(?=(\d{3})+(?!\d))/g, ".");
    return (value < 0 ? "-" : "") + whole + (decimals ? "," + fixed[1] : "");
  }

  function formatCopM(value) {
    return "COP " + groupEs(value, Math.abs(value) >= 1000 ? 0 : 1) + " M";
  }

  function formatCount(value) {
    return groupEs(value, 0);
  }

  function formatDecimal(value, decimals) {
    return groupEs(value, decimals);
  }

  var api = { gain: gain, cost: cost, netValue: netValue, appliedPoint: appliedPoint, kStar: kStar,
              randomNet: randomNet, breakeven: breakeven, scenario: scenario, bars: bars, story: story,
              curveGeometry: curveGeometry, selfCheck: selfCheck,
              formatCopM: formatCopM, formatCount: formatCount, formatDecimal: formatDecimal };

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
      Array.prototype.forEach.call(document.querySelectorAll(selector), function (el) { el.textContent = text; });
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
      set("#sim-capacity-share", groupEs(a.capacity_share * 100, 0) + " %");
      set("#sim-effectiveness-out", "se recuperan " + groupEs(a.action_effectiveness * 100, 0) +
        " de cada 100 en riesgo contactados");
      set("#sim-cost-out", "COP " + formatCount(a.cost_per_contact_cop));
      Object.keys(sim.labels).forEach(function (name) {
        var st = story(sim.labels[name], sim.rule, a, sim.random_name, sim.defaults.capacity_share);
        Object.keys(st.texts).forEach(function (key) { set('[data-sim-text="' + name + "." + key + '"]', st.texts[key]); });
        set('[data-sim-capacity-for="' + name + '"]', st.texts.capacity);
        var zero = st.bars.zero.toFixed(2) + "%";
        st.bars.rows.forEach(function (r, i) {
          var row = document.querySelector('[data-bar="' + name + "." + r.id + '"]');
          if (!row) { return; }
          row.style.order = i;
          row.className = "bar-row tone-" + r.tone;
          var bar = row.querySelector(".bar");
          bar.style.left = r.left.toFixed(2) + "%";
          bar.style.width = r.width.toFixed(2) + "%";
          row.querySelector(".bar-zero").style.left = zero;
          row.querySelector(".bar-value").textContent = formatCopM(r.net);
        });
        var result = scenario(sim.labels[name], sim.rule, a);
        set('[data-sim-net="' + name + '.random"]', formatCopM(result.random));
        result.rows.forEach(function (row) {
          var key = name + "." + row.model_id;
          set('[data-sim-net="' + key + '"]', formatCopM(row.net));
          set('[data-sim-kapplied="' + key + '"]', formatCount(row.k_applied));
          set('[data-sim-kstar="' + key + '"]', formatCount(row.k_star));
          set('[data-sim-diff="' + key + '"]', row.difference === null ? "—" : formatCopM(row.difference));
        });
        redraw(name, a, result.rows.length ? result.rows[0].k_applied : null);
      });
    }

    /* The whole curve follows the controls: lines, best number of contacts, random line, zero axis and range. */
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
          if (title) { title.textContent = "Mejor número de contactos, " + s.name + ": " + formatCount(s.k) + " clientes, " + formatCopM(s.net); }
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

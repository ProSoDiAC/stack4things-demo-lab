const PHASE_LABELS = {
  idle: "Idle",
  waiting_clients: "Waiting for clients",
  broadcast: "Broadcast global model",
  local_training: "Local training on edge",
  upload_weights: "Uploading weights",
  aggregating: "FedAvg aggregation",
  evaluating: "Server evaluation",
  round_complete: "Round complete",
  finished: "Training finished",
};

const CLIENT_IDS = ["board-alpha", "board-beta", "board-gamma"];
const FLOW_PATHS = {
  "board-alpha": { x1: 180, y1: 420, x2: 450, y2: 200 },
  "board-beta": { x1: 450, y1: 420, x2: 450, y2: 200 },
  "board-gamma": { x1: 720, y1: 420, x2: 450, y2: 200 },
};

const SCENARIO_UI = {
  heart: {
    pill: "Heart Ch.19",
    subtitle: "3 edge cohorts · federated learning",
    cloudSubtitle: "Global model · FedAvg",
    clients: {
      "board-alpha": { slug: "alpha", line: "Clinical cohort A", csv: "heart_1.csv" },
      "board-beta": { slug: "beta", line: "Clinical cohort B", csv: "heart_2.csv" },
      "board-gamma": { slug: "gamma", line: "Clinical cohort C", csv: "heart_3.csv" },
    },
  },
  pm: {
    pill: "Maintenance",
    subtitle: "3 production lines · federated learning",
    cloudSubtitle: "Global model · FedAvg",
    clients: {
      "board-alpha": { slug: "alpha", line: "CNC spindle", csv: "machine_1.csv" },
      "board-beta": { slug: "beta", line: "Conveyor motor", csv: "machine_2.csv" },
      "board-gamma": { slug: "gamma", line: "Pump line", csv: "machine_3.csv" },
    },
  },
};

let lastPhase = "";
let pollTimer = null;
let activeScenario = "heart";

function apiBase() {
  if (window.FL_VIZ_BASE) return window.FL_VIZ_BASE;
  if (window.location.pathname.indexOf("/horizon/fl-live") === 0) {
    return "/horizon/fl-live";
  }
  return "";
}

function parseState(text) {
  return JSON.parse(text.replace(/\bNaN\b/g, "null").replace(/\bInfinity\b/g, "null"));
}

function phaseLabel(phase) {
  return PHASE_LABELS[phase] || (phase || "idle").replace(/_/g, " ");
}

function scenarioMeta(state) {
  if (state && state.scenario_ui) {
    return state.scenario_ui;
  }
  var sid = (state && state.fl_scenario) || activeScenario || "heart";
  var ui = SCENARIO_UI[sid] || SCENARIO_UI.heart;
  if (state && state.scenario_clients) {
    return Object.assign({}, ui, { clients: state.scenario_clients });
  }
  return ui;
}

function boardSlug(boardId, base) {
  if (base && base.slug) {
    return base.slug;
  }
  var parts = String(boardId || "").split("-");
  return parts.length > 1 ? parts[parts.length - 1] : boardId;
}

function clientMeta(state, boardId) {
  var ui = scenarioMeta(state);
  var fromState = (state && state.scenario_clients && state.scenario_clients[boardId]) || {};
  var base = (ui.clients && ui.clients[boardId]) || { line: "—", csv: "—" };
  return {
    slug: boardSlug(boardId, base),
    line: fromState.line || base.line || "—",
    csv: fromState.csv || base.csv || "—",
  };
}

function applyScenarioLabels(state) {
  var ui = scenarioMeta(state);
  activeScenario = (state && state.fl_scenario) || activeScenario;
  var setText = function (id, text) {
    var el = document.getElementById(id);
    if (el && text) el.textContent = text;
  };
  setText("scenarioSubtitle", ui.subtitle);
  setText("cloudSubtitle", ui.cloudSubtitle);
  setText("scenarioPill", ui.pill);
  CLIENT_IDS.forEach(function (id) {
    var meta = clientMeta(state, id);
    var g = document.getElementById("client-" + meta.slug);
    if (!g) return;
    var line = g.querySelector(".machine-line");
    if (line) line.textContent = meta.line;
  });
}

function spawnFlow(clientId, color, duration) {
  color = color || "#00d4ff";
  duration = duration || 1800;
  var path = FLOW_PATHS[clientId];
  if (!path) return;
  var svg = document.getElementById("flows");
  if (!svg) return;
  var c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
  c.setAttribute("r", "6");
  c.setAttribute("class", "flow-particle");
  c.setAttribute("fill", color);
  svg.appendChild(c);
  var t0 = performance.now();
  function tick(now) {
    var p = Math.min(1, (now - t0) / duration);
    c.setAttribute("cx", path.x1 + (path.x2 - path.x1) * p);
    c.setAttribute("cy", path.y1 + (path.y2 - path.y1) * p);
    if (p < 1) requestAnimationFrame(tick);
    else c.remove();
  }
  requestAnimationFrame(tick);
}

function statusLabel(status, phase) {
  if (phase === "finished") {
    return "done";
  }
  if (status === "reconnecting") {
    return "reconnecting";
  }
  if (status && status !== "offline") {
    return status;
  }
  if (phase === "waiting_clients" || phase === "broadcast" || phase === "local_training") {
    return "waiting";
  }
  return status || "offline";
}

function updateClients(state) {
  var clients = state.clients || {};
  var phase = state.phase || "idle";
  CLIENT_IDS.forEach(function (id) {
    var meta = clientMeta(state, id);
    var g = document.getElementById("client-" + meta.slug);
    if (!g) return;
    var info = clients[id] || { status: "offline", samples: 0, last_action: "" };
    var csvName = info.csv_file ? info.csv_file.split("/").pop() : meta.csv;
    var st = g.querySelector(".client-status");
    var sm = g.querySelector(".samples");
    var label = statusLabel(info.status, phase);
    if (st) st.textContent = label;
    if (sm) {
      sm.textContent = info.samples
        ? csvName + " · " + info.samples + " samples"
        : csvName;
    }
    g.classList.remove("active", "training", "uploading", "reconnecting", "waiting", "done");
    if (phase === "finished") {
      g.classList.add("done");
    } else if (info.status === "training") {
      g.classList.add("training", "active");
    } else if (info.status === "reconnecting") {
      g.classList.add("reconnecting", "active");
    } else if (info.status === "uploaded" || info.status === "connected") {
      g.classList.add("uploading", "active");
    } else if (info.status === "connected") {
      g.classList.add("active");
    } else if (
      label === "waiting" &&
      phase !== "idle" &&
      info.status === "offline"
    ) {
      g.classList.add("waiting", "active");
    }
  });
}

function drawChart(accSeries, lossSeries) {
  var canvas = document.getElementById("accChart");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var w = canvas.width;
  var h = canvas.height;
  var padL = 44;
  var padR = 40;
  var padT = 14;
  var padB = 22;
  var chartW = w - padL - padR;
  var chartH = h - padT - padB;

  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0b1220";
  ctx.fillRect(0, 0, w, h);

  accSeries = accSeries || [];
  lossSeries = lossSeries || [];

  ctx.font = "10px Segoe UI, system-ui, sans-serif";
  ctx.textBaseline = "middle";

  var lossValues = lossSeries
    .map(function (pt) { return pt.value; })
    .filter(function (v) { return v != null; });
  var lossMin = lossValues.length ? Math.min.apply(null, lossValues) : 0;
  var lossMax = lossValues.length ? Math.max.apply(null, lossValues) : 1;
  if (lossMax <= lossMin) lossMax = lossMin + 0.5;

  // Horizontal grid + left Y-axis (accuracy 0-100%)
  for (var i = 0; i <= 4; i++) {
    var pct = 1 - i / 4;
    var y = padT + chartH * (i / 4);
    ctx.strokeStyle = "#2a4068";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillStyle = "#8ba3c7";
    ctx.textAlign = "right";
    ctx.fillText(Math.round(pct * 100) + "%", padL - 5, y);
  }

  // Right Y-axis (loss values)
  for (var j = 0; j <= 4; j++) {
    var lossVal = lossMax - (lossMax - lossMin) * (j / 4);
    var yLoss = padT + chartH * (j / 4);
    ctx.fillStyle = "#ff8a8a";
    ctx.textAlign = "left";
    ctx.fillText(lossVal.toFixed(2), w - padR + 5, yLoss);
  }

  ctx.fillStyle = "#6ec8ff";
  ctx.textAlign = "center";
  ctx.save();
  ctx.translate(10, padT + chartH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText("accuracy", 0, 0);
  ctx.restore();

  ctx.fillStyle = "#ff8a8a";
  ctx.save();
  ctx.translate(w - 8, padT + chartH / 2);
  ctx.rotate(Math.PI / 2);
  ctx.fillText("loss", 0, 0);
  ctx.restore();

  var maxRound = 0;
  accSeries.forEach(function (pt) {
    if (pt.round != null && pt.round > maxRound) maxRound = pt.round;
  });
  lossSeries.forEach(function (pt) {
    if (pt.round != null && pt.round > maxRound) maxRound = pt.round;
  });
  var xSteps = Math.max(accSeries.length, lossSeries.length, 1);
  if (maxRound <= 0 && xSteps > 1) maxRound = xSteps - 1;

  function xForIndex(i, len) {
    if (len <= 1) return padL + chartW / 2;
    return padL + chartW * (i / (len - 1));
  }

  function xForRound(roundVal, len, idx) {
    if (roundVal != null && maxRound > 0) {
      return padL + chartW * (roundVal / maxRound);
    }
    return xForIndex(idx, len);
  }

  if (maxRound > 0) {
    ctx.fillStyle = "#8ba3c7";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    var xTicks = Math.min(maxRound, 6);
    for (var t = 0; t <= xTicks; t++) {
      var rnd = Math.round((maxRound * t) / xTicks);
      var x = padL + chartW * (rnd / maxRound);
      ctx.fillText(String(rnd), x, h - padB + 6);
    }
    ctx.fillStyle = "#6ec8ff";
    ctx.fillText("round", padL + chartW / 2, h - 4);
  } else if (accSeries.length) {
    ctx.fillStyle = "#8ba3c7";
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    accSeries.forEach(function (pt, i) {
      var x = xForIndex(i, accSeries.length);
      ctx.fillText(String(pt.round != null ? pt.round : i), x, h - padB + 6);
    });
  }

  if (!accSeries.length && !lossSeries.length) return;

  function drawAccSeries(series, color) {
    if (!series.length) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    var started = false;
    series.forEach(function (pt, i) {
      if (pt.value == null) return;
      var x = xForRound(pt.round, series.length, i);
      var norm = Math.max(0, Math.min(1, pt.value));
      var y = padT + chartH * (1 - norm);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
  }

  function drawLossSeries(series, color) {
    if (!series.length) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    var started = false;
    series.forEach(function (pt, i) {
      if (pt.value == null) return;
      var x = xForRound(pt.round, series.length, i);
      var norm = (pt.value - lossMin) / (lossMax - lossMin);
      var y = padT + chartH * (1 - norm);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
  }

  drawAccSeries(accSeries, "#3dd68c");
  drawLossSeries(lossSeries, "#ff6b6b");
}

function renderEvents(events, phase) {
  var ul = document.getElementById("eventLog");
  if (!ul) return;
  ul.innerHTML = "";
  var filtered = events.slice();
  if (phase === "finished") {
    filtered = filtered.filter(function (e) {
      var msg = String(e.message || e.kind || "").toLowerCase();
      return !(
        msg.indexOf("waiting for flower") >= 0 ||
        msg.indexOf("reconnecting") >= 0
      );
    });
  }
  filtered.reverse().slice(0, 25).forEach(function (e) {
    var li = document.createElement("li");
    var t = new Date(e.t * 1000).toLocaleTimeString();
    li.innerHTML = "<strong>" + t + "</strong> — " + (e.message || e.kind);
    ul.appendChild(li);
  });
}

function onState(state) {
  if (!state) return;
  applyScenarioLabels(state);
  var phaseEl = document.getElementById("phaseLabel");
  var roundEl = document.getElementById("roundNum");
  var totalEl = document.getElementById("totalRounds");
  if (phaseEl) {
    phaseEl.textContent = phaseLabel(state.phase);
    phaseEl.classList.toggle("phase-finished", state.phase === "finished");
  }
  if (roundEl) roundEl.textContent = state.round != null ? state.round : 0;
  if (totalEl) totalEl.textContent = state.total_rounds != null ? state.total_rounds : 2;
  updateClients(state);

  drawChart(state.accuracy || [], state.loss || []);
  var acc = state.accuracy || [];
  var lastAcc = document.getElementById("lastAcc");
  if (lastAcc && acc.length) {
    lastAcc.textContent = (acc[acc.length - 1].value * 100).toFixed(1) + "%";
  }
  var loss = state.loss || [];
  var lastLoss = document.getElementById("lastLoss");
  if (lastLoss && loss.length && loss[loss.length - 1].value != null) {
    lastLoss.textContent = Number(loss[loss.length - 1].value).toFixed(3);
  }
  renderEvents(state.events || [], state.phase);

  var cloud = document.getElementById("cloudNode");
  if (cloud && (state.phase === "aggregating" || state.phase === "broadcast")) {
    cloud.classList.add("pulse");
    setTimeout(function () { cloud.classList.remove("pulse"); }, 1200);
  }

  if (state.phase !== lastPhase) {
    if (state.phase === "broadcast") {
      CLIENT_IDS.forEach(function (id) { spawnFlow(id, "#4facfe", 2000); });
    }
    if (state.phase === "upload_weights") {
      CLIENT_IDS.forEach(function (id) {
        if ((state.clients[id] || {}).status === "uploaded") {
          spawnFlow(id, "#3dd68c", 1600);
        }
      });
    }
    lastPhase = state.phase;
  }
}

function fetchState() {
  var base = apiBase();
  fetch(base + "/api/state", { cache: "no-store" })
    .then(function (r) {
      if (!r.ok) {
        throw new Error("state HTTP " + r.status);
      }
      return r.text();
    })
    .then(function (t) { onState(parseState(t)); })
    .catch(function (err) {
      var phaseEl = document.getElementById("phaseLabel");
      if (phaseEl) {
        phaseEl.textContent = "Dashboard offline";
      }
    });
}

function connect() {
  var base = apiBase();
  if (!document.body.classList.contains("embed")) {
    initLiveZoom();
  }
  fetchState();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchState, 1000);

  if (typeof EventSource === "undefined") return;
  var es = new EventSource(base + "/api/events");
  es.onmessage = function (ev) {
    try { onState(parseState(ev.data)); } catch (e) { /* ignore */ }
  };
  es.onerror = function () {
    es.close();
    setTimeout(connect, 3000);
  };
}

connect();

function initLiveZoom() {
  var shell = document.getElementById("live-zoom-shell");
  var viewport = document.getElementById("live-zoom-viewport");
  if (!shell || !viewport) return;

  var zoom = { scale: 1, panX: 0, panY: 0 };
  var panning = false;
  var lastPt = { x: 0, y: 0 };

  function clampScale(value) {
    return Math.min(4, Math.max(0.35, value));
  }

  function applyTransform() {
    viewport.style.transform =
      "translate(" + zoom.panX + "px," + zoom.panY + "px) scale(" + zoom.scale + ")";
  }

  function zoomAt(factor, clientX, clientY) {
    var rect = shell.getBoundingClientRect();
    var ox = clientX - rect.left;
    var oy = clientY - rect.top;
    var prev = zoom.scale;
    var next = clampScale(prev * factor);
    if (next === prev) return;
    zoom.panX = ox - ((ox - zoom.panX) * next) / prev;
    zoom.panY = oy - ((oy - zoom.panY) * next) / prev;
    zoom.scale = next;
    applyTransform();
  }

  function resetZoom() {
    zoom.scale = 1;
    zoom.panX = 0;
    zoom.panY = 0;
    applyTransform();
  }

  shell.addEventListener(
    "wheel",
    function (e) {
      if (e.target.closest(".topology-zoom-controls")) return;
      e.preventDefault();
      var factor = e.deltaY > 0 ? 0.9 : 1.1;
      zoomAt(factor, e.clientX, e.clientY);
    },
    { passive: false }
  );

  shell.addEventListener("mousedown", function (e) {
    if (e.button !== 0) return;
    if (e.target.closest(".topology-zoom-controls")) return;
    panning = true;
    lastPt = { x: e.clientX, y: e.clientY };
    shell.classList.add("is-panning");
  });

  window.addEventListener("mousemove", function (e) {
    if (!panning) return;
    zoom.panX += e.clientX - lastPt.x;
    zoom.panY += e.clientY - lastPt.y;
    lastPt = { x: e.clientX, y: e.clientY };
    applyTransform();
  });

  window.addEventListener("mouseup", function () {
    panning = false;
    shell.classList.remove("is-panning");
  });

  var btnIn = document.getElementById("zoom-in");
  var btnOut = document.getElementById("zoom-out");
  var btnReset = document.getElementById("zoom-reset");
  if (btnIn) {
    btnIn.addEventListener("click", function () {
      var rect = shell.getBoundingClientRect();
      zoomAt(1.2, rect.left + rect.width / 2, rect.top + rect.height / 2);
    });
  }
  if (btnOut) {
    btnOut.addEventListener("click", function () {
      var rect = shell.getBoundingClientRect();
      zoomAt(1 / 1.2, rect.left + rect.width / 2, rect.top + rect.height / 2);
    });
  }
  if (btnReset) btnReset.addEventListener("click", resetZoom);

  applyTransform();
}

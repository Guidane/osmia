// --- Wire Harness Designer (simplified SpliceCAD-style editor) ---
// A device shows its connectors as plain squares on its left/right side.
// Clicking a source connector then a destination connector creates a harness:
// a single bundle line with its own mating connector (named opposite of the
// device connector, e.g. J01 <-> P01). Selecting the harness line opens a
// dense pinout table below the canvas.

// Osmia: the designer lives at /harness/designer/ and its API under /harness/api/.
// api() maps the original "/api/..." paths onto that and sends Django's CSRF token.
const OSMIA = document.getElementById("harness-app").dataset;
function api(path, opts = {}) {
  const url = OSMIA.api + path.replace(/^\/api/, "");
  const method = (opts.method || "GET").toUpperCase();
  if (method !== "GET") {
    opts.headers = { ...(opts.headers || {}), "X-CSRFToken": OSMIA.csrf };
  }
  return fetch(url, { credentials: "same-origin", ...opts });
}

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");

const state = {
  devices: {},        // deviceId -> full device object (cache)
  project: { id: null, name: "Untitled Harness", instances: [], harnesses: [] },
  selectedInstance: null,
  selectedHarness: null,
  pendingPlaceDeviceId: null,
  pendingConnectorFrom: null, // { instance_id, connector_id }
  dragging: null,             // { instance_id, offsetX, offsetY }
  signalRules: [],            // [[sigA, sigB], ...] — global compatibility pairs
  users: [],                  // [{id, name}, ...] — no auth, just a name registry
};

const BOX_HEADER = 26;
const ROW_H = 78;
const MARGIN_TOP = 12;
const MARGIN_BOTTOM = 12;
const BOX_WIDTH = 170;
const CONN_W = 18;
const CONN_H = 66;

const WIRE_TYPES = [
  ["none", "None"],
  ["twisted", "Twisted"],
  ["shielded", "Shielded"],
  ["twisted_shielded", "Twisted + Shielded"],
];

function genId() {
  return Math.random().toString(36).slice(2, 10);
}

function setStatus(msg) {
  document.getElementById("status-msg").textContent = msg || "";
  if (msg) setTimeout(() => { if (document.getElementById("status-msg").textContent === msg) setStatus(""); }, 2500);
}

function oppositeConnectorName(id) {
  const m = id.match(/^([A-Za-z]+)(.*)$/);
  if (!m) return id;
  const prefix = m[1].toUpperCase();
  const rest = m[2];
  if (prefix === "J") return "P" + rest;
  if (prefix === "P") return "J" + rest;
  return "P" + rest;
}

// ---------- Pin availability & signal compatibility ----------

function pinKey(instanceId, connectorId, pinId) {
  return `${instanceId}::${connectorId}::${pinId}`;
}

// Every pin already wired into any harness/branch in the current project.
function usedPinKeys() {
  const used = new Set();
  for (const harness of state.project.harnesses) {
    for (const branch of harness.branches) {
      for (const conn of branch.connections) {
        used.add(pinKey(harness.from_instance, harness.from_connector, conn.from_pin));
        used.add(pinKey(branch.to_instance, branch.to_connector, conn.to_pin));
      }
    }
  }
  return used;
}

function signalHasRules(sig) {
  const s = sig.trim().toUpperCase();
  return state.signalRules.some(([a, b]) => a.trim().toUpperCase() === s || b.trim().toUpperCase() === s);
}

// Whether two pin signal names are allowed to be wired together, per the
// global Signal Rules. A signal with no rule mentioning it anywhere is
// unrestricted (so devices that never define rules keep working as before);
// once a signal has at least one rule, only its explicitly listed partners
// (or itself, if that pair is listed) are allowed.
function signalsCompatible(sigA, sigB) {
  if (!sigA || !sigB) return true;
  const a = sigA.trim().toUpperCase();
  const b = sigB.trim().toUpperCase();
  if (!signalHasRules(a) && !signalHasRules(b)) return true;
  return state.signalRules.some(([x, y]) => {
    const ux = x.trim().toUpperCase();
    const uy = y.trim().toUpperCase();
    return (ux === a && uy === b) || (ux === b && uy === a);
  });
}

// Pairs pins from two pin lists, skipping anything already used elsewhere in
// the project, matching by signal compatibility first, then whatever's left
// over positionally.
function pairAvailablePins(fromPins, toPins, usedKeys, fromCtx, toCtx) {
  const sameConnector = fromCtx.instanceId === toCtx.instanceId && fromCtx.connectorId === toCtx.connectorId;

  if (sameConnector) {
    // Loopback: from/to are the same connector's own pins. Pair them up
    // within one shared pool so a pin is never used twice and never paired
    // with itself (which the two-list algorithm below can't guarantee once
    // both lists are literally the same pins).
    const pool = fromPins.filter(p => !usedKeys.has(pinKey(fromCtx.instanceId, fromCtx.connectorId, p.id)));
    const used = new Set();
    const pairs = [];
    for (const fp of pool) {
      if (used.has(fp.id)) continue;
      const match = pool.find(tp => tp.id !== fp.id && !used.has(tp.id) && signalsCompatible(fp.signal, tp.signal));
      if (match) {
        pairs.push([fp, match]);
        used.add(fp.id);
        used.add(match.id);
      }
    }
    const remaining = pool.filter(p => !used.has(p.id));
    for (let i = 0; i + 1 < remaining.length; i += 2) pairs.push([remaining[i], remaining[i + 1]]);
    return pairs;
  }

  const availableFrom = fromPins.filter(p => !usedKeys.has(pinKey(fromCtx.instanceId, fromCtx.connectorId, p.id)));
  const availableTo = toPins.filter(p => !usedKeys.has(pinKey(toCtx.instanceId, toCtx.connectorId, p.id)));
  const usedTo = new Set();
  const usedFrom = new Set();
  const pairs = [];
  for (const fp of availableFrom) {
    const match = availableTo.find(tp => !usedTo.has(tp.id) && signalsCompatible(fp.signal, tp.signal));
    if (match) {
      pairs.push([fp, match]);
      usedTo.add(match.id);
      usedFrom.add(fp.id);
    }
  }
  const remainingFrom = availableFrom.filter(p => !usedFrom.has(p.id));
  const remainingTo = availableTo.filter(p => !usedTo.has(p.id));
  const n = Math.min(remainingFrom.length, remainingTo.length);
  for (let i = 0; i < n; i++) pairs.push([remainingFrom[i], remainingTo[i]]);
  return pairs;
}

// ---------- Device / connector geometry ----------

function connectorsOnSide(device, side) {
  return device.connectors.filter(c => c.side === side);
}

function deviceBoxSize(device) {
  const leftCount = connectorsOnSide(device, "left").length;
  const rightCount = connectorsOnSide(device, "right").length;
  const rows = Math.max(leftCount, rightCount, 1);
  const height = Math.max(60, BOX_HEADER + MARGIN_TOP + rows * ROW_H + MARGIN_BOTTOM);
  return { width: BOX_WIDTH, height };
}

// Center point of the device-side connector square, plus which side it's on.
function connectorSquarePosition(instance, device, connectorId) {
  const connector = device.connectors.find(c => c.id === connectorId);
  if (!connector) return null;
  const side = connector.side;
  const sideConnectors = connectorsOnSide(device, side);
  const idx = sideConnectors.findIndex(c => c.id === connectorId);
  const { width } = deviceBoxSize(device);
  const x = instance.x + (side === "left" ? 0 : width);
  const y = instance.y + BOX_HEADER + MARGIN_TOP + idx * ROW_H + ROW_H / 2;
  return { x, y, side };
}

function getInstance(instanceId) {
  return state.project.instances.find(i => i.instance_id === instanceId);
}

function getHarness(harnessId) {
  return state.project.harnesses.find(h => h.id === harnessId);
}

function getConnector(device, connectorId) {
  return device.connectors.find(c => c.id === connectorId);
}

// Orders a harness's connections so pins sharing a "set" (e.g. a DSUB PWR/GND
// pair) are shown adjacent to each other, grouped in the order each set first
// appears. Connections whose from-pin has no set keep their original slot.
function orderConnectionsForDisplay(connectionsHolder, fromConnector) {
  const meta = connectionsHolder.connections.map((conn, idx) => {
    const pin = fromConnector.pins.find(p => p.id === conn.from_pin);
    const setKey = pin && pin.set ? pin.set : null;
    const key = setKey !== null ? setKey : `__solo_${idx}`;
    return { conn, idx, key };
  });
  const firstSeen = new Map();
  for (const m of meta) {
    if (!firstSeen.has(m.key)) firstSeen.set(m.key, m.idx);
  }
  meta.sort((a, b) => (firstSeen.get(a.key) - firstSeen.get(b.key)) || (a.idx - b.idx));
  return meta;
}

// A harness has ONE trunk connector (from_instance/from_connector) and one or
// more branches fanning out to different destination connectors — all wires
// sharing that same source connector live in a single harness. The line runs
// directly between the actual device connector rectangles (no separate
// "harness-side" square/stub) — from the source connector to a split point,
// then from that split point out to each destination connector. With a
// single branch the split point collapses onto the source, so it renders as
// one plain line straight into the destination.
function harnessGeometry(harness) {
  const fromInst = getInstance(harness.from_instance);
  if (!fromInst) return null;
  const fromDevice = state.devices[fromInst.device_id];
  if (!fromDevice) return null;
  const fromDevPos = connectorSquarePosition(fromInst, fromDevice, harness.from_connector);
  if (!fromDevPos) return null;

  // Loopback branches (self-referencing: to_instance/to_connector are the
  // same as the trunk's) have no real destination, so they're kept out of
  // the centroid the split point is based on — but they still get a slot
  // alongside the real branches (see loopbackVirtualSlot below).
  const branchGeo = [];
  const loopbackBranches = [];
  for (const branch of harness.branches) {
    const isLoopback = branch.to_instance === harness.from_instance && branch.to_connector === harness.from_connector;
    if (isLoopback) { loopbackBranches.push(branch); continue; }
    const toInst = getInstance(branch.to_instance);
    if (!toInst) continue;
    const toDevice = state.devices[toInst.device_id];
    if (!toDevice) continue;
    const toDevPos = connectorSquarePosition(toInst, toDevice, branch.to_connector);
    if (!toDevPos) continue;
    branchGeo.push({ branch, toInst, toDevice, toDevPos });
  }
  if (branchGeo.length === 0 && loopbackBranches.length === 0) return null;

  let splitPoint = fromDevPos;
  if (branchGeo.length > 1) {
    const cx = branchGeo.reduce((s, b) => s + b.toDevPos.x, 0) / branchGeo.length;
    const cy = branchGeo.reduce((s, b) => s + b.toDevPos.y, 0) / branchGeo.length;
    const SPLIT_FRACTION = 0.4;
    splitPoint = {
      x: fromDevPos.x + (cx - fromDevPos.x) * SPLIT_FRACTION,
      y: fromDevPos.y + (cy - fromDevPos.y) * SPLIT_FRACTION,
    };
  }

  const loopbackGeo = loopbackBranches.map((branch, idx) => ({
    branch,
    hairpin: loopbackHairpin(fromDevPos, idx),
  }));

  return { fromInst, fromDevice, fromDevPos, branchGeo, splitPoint, loopbackGeo };
}

const LOOP_LEG = 48;      // how far the hairpin's legs extend from the connector
const LOOP_GAP = 18;      // vertical spacing between the two legs
const LOOP_RADIUS = LOOP_GAP / 2;
const LOOP_STEP = 34;     // vertical offset between stacked loopbacks on the same connector
const LOOP_Y_OFFSET = 18; // shifts the hairpin off the connector's dead center, so it
                           // doesn't attach at the exact same point the main line does

// A proper hairpin: two straight legs off the connector, capped by a
// semicircle — always anchored to the connector's own position and side,
// completely independent of wherever any real branch lines happen to go, so
// it never drifts or skews when devices move or a branch's angle changes.
// Offset above center so it doesn't land on top of the main harness line's
// exit point.
function loopbackHairpin(fromDevPos, loopIndex) {
  const dir = fromDevPos.side === "left" ? -1 : 1;
  const centerY = fromDevPos.y - LOOP_Y_OFFSET + loopIndex * LOOP_STEP;
  const nearX = fromDevPos.x;
  const farX = fromDevPos.x + dir * LOOP_LEG;
  const arcCenterX = farX - dir * LOOP_RADIUS;
  return { dir, nearX, farX, arcCenterX, centerY, y1: centerY - LOOP_RADIUS, y2: centerY + LOOP_RADIUS };
}

// ---------- Rendering ----------

function render() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (const harness of state.project.harnesses) {
    drawHarness(harness, harness.id === state.selectedHarness);
  }

  for (const inst of state.project.instances) {
    drawInstance(inst, inst.instance_id === state.selectedInstance);
  }

  if (state.pendingConnectorFrom) {
    const inst = getInstance(state.pendingConnectorFrom.instance_id);
    const device = state.devices[inst.device_id];
    const pos = connectorSquarePosition(inst, device, state.pendingConnectorFrom.connector_id);
    ctx.save();
    ctx.strokeStyle = "#3b7dd8";
    ctx.lineWidth = 2;
    ctx.strokeRect(pos.x - CONN_W / 2 - 4, pos.y - CONN_H / 2 - 4, CONN_W + 8, CONN_H + 8);
    ctx.restore();
  }
}

// Two straight legs off the connector, capped by a semicircle — a proper
// hairpin, not a straight-plus-curve teardrop.
function drawLoopback(hairpin, color, thickness) {
  const { dir, nearX, arcCenterX, centerY, y1, y2 } = hairpin;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = thickness;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(nearX, y1);
  ctx.lineTo(arcCenterX, y1);
  ctx.arc(arcCenterX, centerY, LOOP_RADIUS, -Math.PI / 2, Math.PI / 2, dir === -1);
  ctx.lineTo(nearX, y2);
  ctx.stroke();
  ctx.restore();
}

function hitTestLoopback(hairpin, x, y) {
  const { nearX, farX, y1, y2 } = hairpin;
  const minX = Math.min(nearX, farX) - 8;
  const maxX = Math.max(nearX, farX) + 8;
  return x >= minX && x <= maxX && y >= y1 - 8 && y <= y2 + 8;
}

function drawHarness(harness, selected) {
  const geo = harnessGeometry(harness);
  if (!geo) return;
  const { fromDevPos, branchGeo, splitPoint, loopbackGeo } = geo;
  const totalCount = harness.branches.reduce((n, b) => n + b.connections.length, 0);
  const trunkColor = selected ? "#3b7dd8" : "#555";

  ctx.save();

  // single line from the source connector out to the split point
  if (branchGeo.length > 0) {
    const trunkThickness = selected ? Math.min(4 + totalCount, 14) : Math.min(2 + totalCount, 12);
    ctx.strokeStyle = trunkColor;
    ctx.lineWidth = trunkThickness;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(fromDevPos.x, fromDevPos.y);
    ctx.lineTo(splitPoint.x, splitPoint.y);
    ctx.stroke();
  }

  for (const lg of loopbackGeo) {
    const loopThickness = selected ? Math.min(4 + lg.branch.connections.length, 14) : Math.min(2 + lg.branch.connections.length, 12);
    drawLoopback(lg.hairpin, trunkColor, loopThickness);
  }

  // branch lines fanning out from the split point directly into each
  // destination connector — no separate stub or mating-connector square
  for (const bg of branchGeo) {
    const branchThickness = selected ? Math.min(4 + bg.branch.connections.length, 14) : Math.min(2 + bg.branch.connections.length, 12);
    ctx.strokeStyle = trunkColor;
    ctx.lineWidth = branchThickness;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(splitPoint.x, splitPoint.y);
    ctx.lineTo(bg.toDevPos.x, bg.toDevPos.y);
    ctx.stroke();
  }

  // junction dot where the trunk splits (only visible once there's a fan-out)
  if (branchGeo.length > 1) {
    ctx.fillStyle = trunkColor;
    ctx.beginPath();
    ctx.arc(splitPoint.x, splitPoint.y, 4, 0, Math.PI * 2);
    ctx.fill();
  }

  // harness label + total wire count, placed on the trunk (or on the single
  // branch/loopback line when there's only one thing off the split point)
  const labelP1 = fromDevPos;
  let labelP2;
  if (branchGeo.length > 1) labelP2 = splitPoint;
  else if (branchGeo.length === 1) labelP2 = branchGeo[0].toDevPos;
  else if (loopbackGeo.length > 0) labelP2 = { x: loopbackGeo[0].hairpin.arcCenterX, y: loopbackGeo[0].hairpin.centerY };
  else labelP2 = fromDevPos;
  const mx = (labelP1.x + labelP2.x) / 2;
  const my = (labelP1.y + labelP2.y) / 2;
  ctx.font = "bold 11px sans-serif";
  const label = `${harness.label || "H"} (${totalCount})`;
  const textW = ctx.measureText(label).width;
  ctx.fillStyle = "#fff";
  ctx.fillRect(mx - textW / 2 - 4, my - 9, textW + 8, 16);
  ctx.fillStyle = selected ? "#3b7dd8" : "#333";
  ctx.textAlign = "center";
  ctx.fillText(label, mx, my + 3);
  ctx.textAlign = "left";

  ctx.restore();
}

function drawConnectorRect(pos, fill, stroke, width) {
  const w = width || CONN_W;
  ctx.save();
  ctx.fillStyle = fill;
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 2;
  ctx.fillRect(pos.x - w / 2, pos.y - CONN_H / 2, w, CONN_H);
  ctx.strokeRect(pos.x - w / 2, pos.y - CONN_H / 2, w, CONN_H);
  ctx.restore();
}

function drawConnectorLabel(pos, text, color, width) {
  ctx.save();
  ctx.font = "bold 10px sans-serif";
  ctx.fillStyle = color;
  const gap = (width || CONN_W) / 2 + 6;
  if (pos.side === "left") {
    ctx.textAlign = "right";
    ctx.fillText(text, pos.x - gap, pos.y + 3);
  } else {
    ctx.textAlign = "left";
    ctx.fillText(text, pos.x + gap, pos.y + 3);
  }
  ctx.restore();
}

function drawInstance(inst, selected) {
  const device = state.devices[inst.device_id];
  if (!device) return;
  const { width, height } = deviceBoxSize(device);

  ctx.save();
  ctx.fillStyle = "#fff";
  ctx.strokeStyle = selected ? "#3b7dd8" : "#333";
  ctx.lineWidth = selected ? 3 : 1.5;
  ctx.fillRect(inst.x, inst.y, width, height);
  ctx.strokeRect(inst.x, inst.y, width, height);

  ctx.fillStyle = device.color || "#3b7dd8";
  ctx.fillRect(inst.x, inst.y, width, BOX_HEADER);
  ctx.strokeRect(inst.x, inst.y, width, BOX_HEADER);
  ctx.fillStyle = "#fff";
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.fillText(inst.label || device.name, inst.x + width / 2, inst.y + 17);
  ctx.textAlign = "left";

  for (const connector of device.connectors) {
    const pos = connectorSquarePosition(inst, device, connector.id);
    const isPending = state.pendingConnectorFrom &&
      state.pendingConnectorFrom.instance_id === inst.instance_id &&
      state.pendingConnectorFrom.connector_id === connector.id;
    drawConnectorRect(pos, isPending ? "#eaf1fd" : "#fff", isPending ? "#3b7dd8" : "#333");
    drawConnectorLabel(pos, connector.id, "#222");
  }

  ctx.restore();
}

// ---------- Hit testing ----------

function hitTestConnector(x, y) {
  for (const inst of state.project.instances) {
    const device = state.devices[inst.device_id];
    if (!device) continue;
    for (const connector of device.connectors) {
      const pos = connectorSquarePosition(inst, device, connector.id);
      if (Math.abs(x - pos.x) <= CONN_W / 2 + 4 && Math.abs(y - pos.y) <= CONN_H / 2 + 4) {
        return { instance_id: inst.instance_id, connector_id: connector.id };
      }
    }
  }
  return null;
}

function hitTestInstance(x, y) {
  for (let i = state.project.instances.length - 1; i >= 0; i--) {
    const inst = state.project.instances[i];
    const device = state.devices[inst.device_id];
    if (!device) continue;
    const { width, height } = deviceBoxSize(device);
    if (x >= inst.x && x <= inst.x + width && y >= inst.y && y <= inst.y + height) {
      return inst.instance_id;
    }
  }
  return null;
}

function distToSegment(p, a, b) {
  const l2 = (b.x - a.x) ** 2 + (b.y - a.y) ** 2;
  if (l2 === 0) return Math.hypot(p.x - a.x, p.y - a.y);
  let t = ((p.x - a.x) * (b.x - a.x) + (p.y - a.y) * (b.y - a.y)) / l2;
  t = Math.max(0, Math.min(1, t));
  const projX = a.x + t * (b.x - a.x);
  const projY = a.y + t * (b.y - a.y);
  return Math.hypot(p.x - projX, p.y - projY);
}

function hitTestHarness(x, y) {
  for (const harness of state.project.harnesses) {
    const geo = harnessGeometry(harness);
    if (!geo) continue;
    const { fromDevPos, branchGeo, splitPoint, loopbackGeo } = geo;
    const totalCount = harness.branches.reduce((n, b) => n + b.connections.length, 0);
    const trunkThickness = Math.min(2 + totalCount, 12);
    if (branchGeo.length > 0 && distToSegment({ x, y }, fromDevPos, splitPoint) <= trunkThickness / 2 + 4) {
      return harness.id;
    }
    for (const bg of branchGeo) {
      const branchThickness = Math.min(2 + bg.branch.connections.length, 12);
      if (distToSegment({ x, y }, splitPoint, bg.toDevPos) <= branchThickness / 2 + 4) {
        return harness.id;
      }
    }
    for (const lg of loopbackGeo) {
      if (hitTestLoopback(lg.hairpin, x, y)) {
        return harness.id;
      }
    }
  }
  return null;
}

// ---------- Canvas interaction ----------

function canvasMouseDown(e) {
  const { x, y } = mousePosFromEvent(e);

  const connector = hitTestConnector(x, y);
  if (connector) {
    if (!state.pendingConnectorFrom) {
      state.pendingConnectorFrom = connector;
      setStatus("Select the destination connector… (Esc to cancel)");
    } else if (state.pendingConnectorFrom.instance_id === connector.instance_id) {
      state.pendingConnectorFrom = null;
      setStatus("Cancelled");
    } else {
      const from = state.pendingConnectorFrom;
      state.pendingConnectorFrom = null;
      startHarnessCreation(from, connector);
    }
    updateLoopbackButton();
    render();
    return;
  }

  const instId = hitTestInstance(x, y);
  if (instId) {
    state.pendingConnectorFrom = null;
    updateLoopbackButton();
    const inst = getInstance(instId);
    state.dragging = { instance_id: instId, offsetX: x - inst.x, offsetY: y - inst.y };
    selectInstance(instId);
    return;
  }

  const harnessId = hitTestHarness(x, y);
  if (harnessId) {
    state.pendingConnectorFrom = null;
    updateLoopbackButton();
    selectHarness(harnessId);
    render();
    return;
  }

  if (state.pendingPlaceDeviceId) {
    placeDevice(state.pendingPlaceDeviceId, x, y);
    return;
  }

  state.pendingConnectorFrom = null;
  updateLoopbackButton();
  selectNone();
  render();
}

function canvasMouseMove(e) {
  const { x, y } = mousePosFromEvent(e);

  if (state.dragging) {
    const inst = getInstance(state.dragging.instance_id);
    inst.x = Math.max(0, x - state.dragging.offsetX);
    inst.y = Math.max(0, y - state.dragging.offsetY);
    render();
  }
}

function canvasMouseUp() {
  state.dragging = null;
}

function mousePosFromEvent(e) {
  const rect = canvas.getBoundingClientRect();
  return { x: e.clientX - rect.left, y: e.clientY - rect.top };
}

// Shows a "Loop Back this connector instead" button whenever a connector is
// pending — an alternative to clicking a second connector on the canvas, so
// looping a set's pins back to each other doesn't need a placeholder device.
function updateLoopbackButton() {
  const btn = document.getElementById("btn-loopback-pending");
  btn.classList.toggle("hidden", !state.pendingConnectorFrom);
}

document.getElementById("btn-loopback-pending").onclick = () => {
  const from = state.pendingConnectorFrom;
  if (!from) return;
  state.pendingConnectorFrom = null;
  updateLoopbackButton();
  startHarnessCreation(from, from);
  render();
};

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (connectModal && !connectModal.classList.contains("hidden")) {
      closeConnectModal();
    }
    state.pendingConnectorFrom = null;
    updateLoopbackButton();
    render();
  }
  if (e.key === "Delete" || e.key === "Backspace") {
    if (document.activeElement && ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
    if (state.selectedInstance) deleteInstance(state.selectedInstance);
    else if (state.selectedHarness) deleteHarness(state.selectedHarness);
  }
});

canvas.addEventListener("mousedown", canvasMouseDown);
canvas.addEventListener("mousemove", canvasMouseMove);
canvas.addEventListener("mouseup", canvasMouseUp);
canvas.addEventListener("mouseleave", canvasMouseUp);

// ---------- Harness creation ----------
// A harness has one trunk connector (from_instance/from_connector) and a list
// of branches, each fanning out to a different destination connector. Any
// connector already part of a harness — whether it's currently the trunk or
// one of the branches — pulls a newly-wired connector into that SAME
// harness. If the shared connector was a branch (not the trunk), the harness
// is re-rooted so that connector becomes the trunk instead, since it's now
// the actual hub multiple things converge on — that's what makes the split
// point land in the middle of the units again instead of drawing a separate
// straight line per source.

function findHarnessContainingConnector(instanceId, connectorId) {
  // A harness where this connector is already the trunk wins over one where
  // it's a branch, so joining never has to re-root (and re-attach) a harness.
  for (const harness of state.project.harnesses) {
    if (harness.from_instance === instanceId && harness.from_connector === connectorId) {
      return { harness, role: "trunk" };
    }
  }
  for (const harness of state.project.harnesses) {
    const branch = harness.branches.find(b => b.to_instance === instanceId && b.to_connector === connectorId);
    if (branch) return { harness, role: "branch", branch };
  }
  return null;
}

// Makes `newTrunkConn` (currently one of `harness`'s branches) the trunk,
// demoting the old trunk to a branch in its place. Connections on the
// swapped branch have their from/to sides flipped so the pin pairing stays
// correct from the new trunk's point of view.
function rerootHarness(harness, newTrunkConn) {
  const branchIdx = harness.branches.findIndex(
    b => b.to_instance === newTrunkConn.instance_id && b.to_connector === newTrunkConn.connector_id
  );
  if (branchIdx < 0) return; // already the trunk, or not part of this harness — nothing to do

  const newTrunkBranch = harness.branches[branchIdx];
  const isOldTrunkLoopback = b => b.to_instance === harness.from_instance && b.to_connector === harness.from_connector;
  const oldLoopbacks = harness.branches.filter(isOldTrunkLoopback);
  if (oldLoopbacks.length) {
    state.project.harnesses.push({
      id: genId(),
      label: `H${state.project.harnesses.length + 1}`,
      from_instance: harness.from_instance,
      from_connector: harness.from_connector,
      from_harness_connector: harness.from_harness_connector,
      from_verified: harness.from_verified,
      branches: oldLoopbacks,
    });
    harness.branches = harness.branches.filter(b => !isOldTrunkLoopback(b));
  }
  const oldTrunk = {
    to_instance: harness.from_instance,
    to_connector: harness.from_connector,
    to_harness_connector: harness.from_harness_connector,
    to_verified: harness.from_verified,
  };

  harness.branches.splice(harness.branches.indexOf(newTrunkBranch), 1, {
    id: genId(),
    ...oldTrunk,
    connections: newTrunkBranch.connections.map(c => ({
      ...c,
      from_pin: c.to_pin,
      to_pin: c.from_pin,
      from_verified: c.to_verified,
      to_verified: c.from_verified,
    })),
  });

  harness.from_instance = newTrunkConn.instance_id;
  harness.from_connector = newTrunkConn.connector_id;
  harness.from_harness_connector = newTrunkBranch.to_harness_connector;
  harness.from_verified = newTrunkBranch.to_verified;
}

// Figures out which (if either) existing harness the two just-clicked
// connectors already belong to, and whether that harness would have to be
// re-rooted onto the shared connector. Nothing is changed here: the re-root
// (`reroot`) is only applied by commitBranch once wires are actually added, so
// opening the connect popup and cancelling leaves the project untouched.
function resolveHarnessTarget(fromConn, toConn) {
  // Loopback: never re-root. Re-rooting would move an existing harness's trunk
  // onto this connector, so the harness would re-attach and its split point
  // and mating-connector names would change after the initial connection.
  // Join a harness only if this connector is already its trunk; otherwise the
  // loopback gets its own harness anchored on this connector.
  if (fromConn.instance_id === toConn.instance_id && fromConn.connector_id === toConn.connector_id) {
    const trunkHarness = state.project.harnesses.find(
      h => h.from_instance === fromConn.instance_id && h.from_connector === fromConn.connector_id
    );
    return { existingHarness: trunkHarness || null, effectiveFromConn: fromConn, effectiveToConn: toConn };
  }
  const matchFrom = findHarnessContainingConnector(fromConn.instance_id, fromConn.connector_id);
  if (matchFrom) {
    const reroot = matchFrom.role === "branch" ? fromConn : null;
    return { existingHarness: matchFrom.harness, effectiveFromConn: fromConn, effectiveToConn: toConn, reroot };
  }
  const matchTo = findHarnessContainingConnector(toConn.instance_id, toConn.connector_id);
  if (matchTo) {
    const reroot = matchTo.role === "branch" ? toConn : null;
    return { existingHarness: matchTo.harness, effectiveFromConn: toConn, effectiveToConn: fromConn, reroot };
  }
  return { existingHarness: null, effectiveFromConn: fromConn, effectiveToConn: toConn };
}

// Creates the harness (if it doesn't exist yet) and/or the branch to this
// destination (if it doesn't exist yet), then appends the given pin pairs as
// connections on that branch. Returns the harness.
function commitBranch(existingHarness, fromConn, toConn, pinPairs, reroot = null) {
  let harness = existingHarness;
  if (harness && reroot) rerootHarness(harness, reroot);
  if (!harness) {
    harness = {
      id: genId(),
      label: `H${state.project.harnesses.length + 1}`,
      from_instance: fromConn.instance_id,
      from_connector: fromConn.connector_id,
      from_harness_connector: oppositeConnectorName(fromConn.connector_id),
      from_verified: false, // confirmed by the trunk device's responsible user
      branches: [],
    };
    state.project.harnesses.push(harness);
  }

  let branch = harness.branches.find(b => b.to_instance === toConn.instance_id && b.to_connector === toConn.connector_id);
  if (!branch) {
    branch = {
      id: genId(),
      to_instance: toConn.instance_id,
      to_connector: toConn.connector_id,
      to_harness_connector: oppositeConnectorName(toConn.connector_id),
      to_verified: false, // confirmed by this destination device's responsible user
      connections: [],
    };
    harness.branches.push(branch);
  }

  for (const [fp, tp] of pinPairs) branch.connections.push(makeConnection(fp, tp));
  return harness;
}

function makeConnection(fromPin, toPin) {
  return {
    id: genId(),
    from_pin: fromPin.id,
    to_pin: toPin.id,
    wire_type: "none", // none | twisted | shielded | twisted_shielded
    awg: "",
    length: "",
    from_verified: false, // confirmed by the from-side device's responsible user
    to_verified: false,   // confirmed by the to-side device's responsible user
  };
}

// Groups a connector's pins into named sets (e.g. "Set 1": pins 1 & 13) plus
// one solo group per ungrouped pin, for display in pickers and the modal.
function connectorGroups(connector) {
  const bySet = new Map();
  const groups = [];
  for (const pin of connector.pins) {
    if (pin.set) {
      if (!bySet.has(pin.set)) {
        const group = { key: `set:${pin.set}`, name: pin.set, pins: [] };
        bySet.set(pin.set, group);
        groups.push(group);
      }
      bySet.get(pin.set).pins.push(pin);
    } else {
      groups.push({ key: `pin:${pin.id}`, name: pin.label, pins: [pin] });
    }
  }
  return groups;
}

// Matches pins between two chosen groups, respecting pin availability and
// the global signal compatibility rules (see pairAvailablePins).
function pairPinsInGroups(fromGroup, toGroup, usedKeys, fromCtx, toCtx) {
  return pairAvailablePins(fromGroup.pins, toGroup.pins, usedKeys, fromCtx, toCtx);
}

// Groups with at least one still-available pin, for picker dropdowns.
function availableGroups(connector, ctx, usedKeys) {
  return connectorGroups(connector).filter(g => g.pins.some(p => !usedKeys.has(pinKey(ctx.instanceId, ctx.connectorId, p.id))));
}

// Named sets only (drops the one-pin "groups" connectorGroups() synthesizes
// for ungrouped/spare pins) — used to populate Set-selection dropdowns, so
// only real sets are pickable there, not individual loose wires.
function namedSetsOnly(groups) {
  return groups.filter(g => g.key.startsWith("set:"));
}

function startHarnessCreation(fromConn, toConn) {
  const { existingHarness, effectiveFromConn, effectiveToConn, reroot } = resolveHarnessTarget(fromConn, toConn);

  const fromInst = getInstance(effectiveFromConn.instance_id);
  const toInst = getInstance(effectiveToConn.instance_id);
  const fromDevice = state.devices[fromInst.device_id];
  const toDevice = state.devices[toInst.device_id];
  const fromConnector = getConnector(fromDevice, effectiveFromConn.connector_id);
  const toConnector = getConnector(toDevice, effectiveToConn.connector_id);

  const hasSets = fromConnector.pins.some(p => p.set) || toConnector.pins.some(p => p.set);
  if (!hasSets) {
    addBranchAuto(existingHarness, effectiveFromConn, effectiveToConn, fromConnector, toConnector, reroot);
  } else {
    openConnectModal(existingHarness, effectiveFromConn, effectiveToConn, fromConnector, toConnector, reroot);
  }
  render();
}

// Simple case (no pin sets defined on either side): pair available,
// signal-compatible pins, same as before — no need to bother the user with a picker.
function addBranchAuto(existingHarness, fromConn, toConn, fromConnector, toConnector, reroot = null) {
  const usedKeys = usedPinKeys();
  const fromCtx = { instanceId: fromConn.instance_id, connectorId: fromConn.connector_id };
  const toCtx = { instanceId: toConn.instance_id, connectorId: toConn.connector_id };
  const pinPairs = pairAvailablePins(fromConnector.pins, toConnector.pins, usedKeys, fromCtx, toCtx);
  if (pinPairs.length === 0) {
    setStatus("No available/compatible pins left to connect");
    return;
  }
  const harness = commitBranch(existingHarness, fromConn, toConn, pinPairs, reroot);
  selectHarness(harness.id);
  setStatus(`${existingHarness ? "Added destination to" : "Created"} ${harness.label}: ${fromConnector.id} ↔ ${toConnector.id}`);
}

// ---------- Connect Sets modal ----------
// A live-editable table: one row per wire. Rows are rebuilt from a small data
// model (connectPickRows) on every change, which lets the Set dropdown span
// multiple rows (rowSpan) whenever consecutive rows share the same set —
// picking/changing that one dropdown updates every pin row under it at once.

const connectModal = document.getElementById("connect-modal");
const connectPickBodyEl = document.getElementById("connect-pick-body");
let connectModalState = null; // { existingHarness, fromConn, toConn, fromConnector, toConnector, fromGroups, toGroups, fromCtx, toCtx }
let connectPickRows = [];     // [{ id, fromSetKey, fromPinId, toSetKey, toPinId }]

// Loads (or reloads, when the Unit selector changes) which from/to connector
// pair the modal is targeting: computes available groups, seeds matching-set
// rows, and re-renders the pick table. Shared by both entry points below.
function applyConnectTarget(existingHarness, fromConn, toConn, fromConnector, toConnector) {
  const fromInst = getInstance(fromConn.instance_id);
  const toInst = getInstance(toConn.instance_id);
  const fromDevice = state.devices[fromInst.device_id];
  const toDevice = state.devices[toInst.device_id];
  const fromName = fromInst.label || fromDevice.name;
  const toName = toInst.label || toDevice.name;

  const usedKeys = usedPinKeys();
  const fromCtx = { instanceId: fromConn.instance_id, connectorId: fromConn.connector_id };
  const toCtx = { instanceId: toConn.instance_id, connectorId: toConn.connector_id };
  const fromGroups = availableGroups(fromConnector, fromCtx, usedKeys);
  const toGroups = availableGroups(toConnector, toCtx, usedKeys);
  connectModalState = { existingHarness, fromConn, toConn, fromConnector, toConnector, fromGroups, toGroups, fromCtx, toCtx };
  connectPickRows = [];

  document.getElementById("connect-modal-title").textContent =
    `Connect ${fromName}.${fromConnector.id} → ${toName}.${toConnector.id}`;
  document.getElementById("btn-create-connect").textContent = existingHarness ? "Add Wires" : "Create Harness";

  if (fromGroups.length === 0 || toGroups.length === 0) {
    setStatus("No available pins/sets left on one side — everything is already wired");
    renderPickTable();
    return;
  }

  // Auto-suggest a row per pin for groups whose names match exactly on both
  // sides (e.g. "Set 1" <-> "Set 1"); anything else is left for the user to
  // add manually via "+ Add Set". Skipped for a loopback (from and to are
  // the same connector) — every group would trivially "match itself" there,
  // including spare pins, which makes no sense to auto-pair; the user picks
  // both sides explicitly instead.
  const isLoopbackTarget = fromCtx.instanceId === toCtx.instanceId && fromCtx.connectorId === toCtx.connectorId;
  let addedAny = false;
  if (!isLoopbackTarget) {
    const seedUsed = usedPinKeys();
    for (const fg of fromGroups) {
      const match = toGroups.find(tg => tg.name.toLowerCase() === fg.name.toLowerCase());
      if (!match) continue;
      const pairs = pairPinsInGroups(fg, match, seedUsed, fromCtx, toCtx);
      for (const [fp, tp] of pairs) {
        seedUsed.add(pinKey(fromCtx.instanceId, fromCtx.connectorId, fp.id));
        seedUsed.add(pinKey(toCtx.instanceId, toCtx.connectorId, tp.id));
        connectPickRows.push({ id: genId(), fromSetKey: fg.key, fromPinId: fp.id, toSetKey: match.key, toPinId: tp.id });
        addedAny = true;
      }
    }
  }
  if (!addedAny) setStatus(isLoopbackTarget ? "Pick which pin/set loops to which on each side, then + Add Set" : "Pick a set on each side below and click + Add Set");

  renderPickTable();
}

// Entry point 1: clicking a source connector then a destination connector on
// the canvas — both ends are already fixed, so there's no Unit to pick.
function openConnectModal(existingHarness, fromConn, toConn, fromConnector, toConnector, reroot = null) {
  document.getElementById("connect-unit-row").classList.add("hidden");
  applyConnectTarget(existingHarness, fromConn, toConn, fromConnector, toConnector);
  connectModalState.reroot = reroot;  // applied only if wires are added
  connectModal.classList.remove("hidden");
}

// Entry point 2: "+ Add Set" in the drawer — the trunk side is fixed (it's
// this harness), but which existing destination to add wires to is picked
// via the Unit selector inside the modal.
function openAddSetModalForHarness(harness) {
  const fromConn = { instance_id: harness.from_instance, connector_id: harness.from_connector };
  const fromInst = getInstance(harness.from_instance);
  const fromConnector = getConnector(state.devices[fromInst.device_id], harness.from_connector);

  const unitRow = document.getElementById("connect-unit-row");
  const unitSelect = document.getElementById("connect-unit-select");
  unitSelect.innerHTML = "";
  for (const branch of harness.branches) {
    const toInst = getInstance(branch.to_instance);
    if (!toInst) continue;
    const toName = toInst.label || state.devices[toInst.device_id]?.name || "?";
    unitSelect.appendChild(new Option(`${toName}.${branch.to_connector}`, branch.id));
  }
  if (unitSelect.options.length === 0) {
    setStatus("This harness has no destinations yet — connect one from the canvas first.");
    return;
  }
  unitRow.classList.remove("hidden");

  function loadSelectedUnit() {
    const branch = harness.branches.find(b => b.id === unitSelect.value);
    const toConn = { instance_id: branch.to_instance, connector_id: branch.to_connector };
    const toConnector = getConnector(state.devices[getInstance(branch.to_instance).device_id], branch.to_connector);
    applyConnectTarget(harness, fromConn, toConn, fromConnector, toConnector);
  }
  unitSelect.onchange = loadSelectedUnit;
  loadSelectedUnit();

  connectModal.classList.remove("hidden");
}

function closeConnectModal() {
  connectModal.classList.add("hidden");
  connectModalState = null;
  connectPickRows = [];
  document.getElementById("connect-unit-row").classList.add("hidden");
}

// Pins already claimed by OTHER rows in this modal (per the data model),
// plus everything already wired elsewhere in the project — so no two rows
// (or an existing wire) can end up pointing at the same pin. For a loopback
// row (from/to are the same connector), `selfPinId` additionally excludes
// this row's OWN pin on the opposite side, so a pin can never loop to itself.
function pickRowsUsedKeys(ctx, side, excludeRowId, selfPinId) {
  const used = usedPinKeys();
  if (selfPinId) used.add(pinKey(ctx.instanceId, ctx.connectorId, selfPinId));
  for (const row of connectPickRows) {
    if (row.id === excludeRowId) continue;
    const pinId = side === "from" ? row.fromPinId : row.toPinId;
    if (pinId) used.add(pinKey(ctx.instanceId, ctx.connectorId, pinId));
  }
  return used;
}

function availablePinsForRow(groups, setKey, ctx, side, excludeRowId, keepPinId, selfPinId) {
  const group = groups.find(g => g.key === setKey);
  if (!group) return [];
  const used = pickRowsUsedKeys(ctx, side, excludeRowId, selfPinId);
  return group.pins.filter(p => p.id === keepPinId || !used.has(pinKey(ctx.instanceId, ctx.connectorId, p.id)));
}

function updateCreateConnectButton() {
  const btn = document.getElementById("btn-create-connect");
  if (!connectModalState) { btn.textContent = "Create Harness"; return; }
  const count = connectPickRows.filter(r => r.fromPinId && r.toPinId).length;
  const base = connectModalState.existingHarness ? "Add Wires" : "Create Harness";
  btn.textContent = count > 0 ? `${base} (${count} wire${count === 1 ? "" : "s"})` : base;
}

// Once every pin of a set is already used by a row in the table (or already
// wired elsewhere in the project), that set drops out of the "+ Add Set"
// dropdowns entirely — picking it again would have nothing left to add.
function refreshAddSetOptions() {
  const { fromGroups, toGroups, fromCtx, toCtx } = connectModalState;
  const usedKeys = usedPinKeys();
  for (const row of connectPickRows) {
    if (row.fromPinId) usedKeys.add(pinKey(fromCtx.instanceId, fromCtx.connectorId, row.fromPinId));
    if (row.toPinId) usedKeys.add(pinKey(toCtx.instanceId, toCtx.connectorId, row.toPinId));
  }

  function refill(select, groups, ctx) {
    const prevValue = select.value;
    select.innerHTML = "";
    for (const g of groups) {
      const stillAvailable = g.pins.some(p => !usedKeys.has(pinKey(ctx.instanceId, ctx.connectorId, p.id)));
      if (stillAvailable) select.appendChild(new Option(g.name, g.key));
    }
    if ([...select.options].some(o => o.value === prevValue)) select.value = prevValue;
  }

  refill(document.getElementById("add-set-from"), namedSetsOnly(fromGroups), fromCtx);
  refill(document.getElementById("add-set-to"), namedSetsOnly(toGroups), toCtx);
}

function renderPickTable() {
  const { fromGroups, toGroups, fromCtx, toCtx } = connectModalState;
  const sameConnector = fromCtx.instanceId === toCtx.instanceId && fromCtx.connectorId === toCtx.connectorId;
  refreshAddSetOptions();
  connectPickBodyEl.innerHTML = "";

  if (connectPickRows.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 7;
    td.className = "no-rows";
    td.textContent = "No wires yet — pick a set on each side below and click + Add Set.";
    tr.appendChild(td);
    connectPickBodyEl.appendChild(tr);
    updateCreateConnectButton();
    return;
  }

  // Consecutive rows sharing the same set key get one merged (rowSpan) Set
  // dropdown instead of repeating it — computed fresh from the array each
  // render, so add/remove/reassign always regroups correctly.
  function spanStarts(keyOf) {
    const starts = {};
    for (let i = 0; i < connectPickRows.length; i++) {
      if (i > 0 && keyOf(connectPickRows[i]) === keyOf(connectPickRows[i - 1])) continue;
      let j = i + 1;
      while (j < connectPickRows.length && keyOf(connectPickRows[j]) === keyOf(connectPickRows[i])) j++;
      starts[i] = j - i;
    }
    return starts;
  }
  const fromSpans = spanStarts(r => r.fromSetKey);
  const toSpans = spanStarts(r => r.toSetKey);

  function setSelectCell(groups, span, currentKey, onSelect) {
    const td = document.createElement("td");
    if (!span) return null;
    const sel = document.createElement("select");
    const options = namedSetsOnly(groups);
    // Keep the current selection choosable even if it's a loose pin from
    // before this row's set was last picked — just don't offer it anew.
    if (!options.some(g => g.key === currentKey)) {
      const current = groups.find(g => g.key === currentKey);
      if (current) options.push(current);
    }
    for (const g of options) sel.appendChild(new Option(g.name, g.key));
    sel.value = currentKey;
    sel.onchange = () => onSelect(sel.value);
    td.appendChild(sel);
    if (span > 1) td.rowSpan = span;
    return td;
  }

  connectPickRows.forEach((rowData, idx) => {
    const tr = document.createElement("tr");

    const fromSetTd = setSelectCell(fromGroups, fromSpans[idx], rowData.fromSetKey, (newKey) => {
      const span = fromSpans[idx];
      for (let k = idx; k < idx + span; k++) {
        connectPickRows[k].fromSetKey = newKey;
        connectPickRows[k].fromPinId = null;
      }
      renderPickTable();
    });
    if (fromSetTd) tr.appendChild(fromSetTd);

    const fromGroup = fromGroups.find(g => g.key === rowData.fromSetKey);
    const fromPinOptions = availablePinsForRow(fromGroups, rowData.fromSetKey, fromCtx, "from", rowData.id, rowData.fromPinId, sameConnector ? rowData.toPinId : null);
    if (!rowData.fromPinId && fromPinOptions.length > 0) rowData.fromPinId = fromPinOptions[0].id;
    const fromPin = fromGroup && fromGroup.pins.find(p => p.id === rowData.fromPinId);

    const fromSigTd = document.createElement("td");
    fromSigTd.className = "pick-signal";
    fromSigTd.textContent = (fromPin && fromPin.signal) || "—";
    tr.appendChild(fromSigTd);

    const fromPinTd = document.createElement("td");
    const fromPinSel = document.createElement("select");
    if (fromPinOptions.length === 0) {
      fromPinSel.appendChild(new Option("— none —", ""));
      fromPinSel.disabled = true;
    } else {
      for (const p of fromPinOptions) fromPinSel.appendChild(new Option(p.label, p.id));
      fromPinSel.value = rowData.fromPinId || "";
    }
    fromPinSel.onchange = () => { rowData.fromPinId = fromPinSel.value; renderPickTable(); };
    fromPinTd.appendChild(fromPinSel);
    tr.appendChild(fromPinTd);

    const toGroup = toGroups.find(g => g.key === rowData.toSetKey);
    const toPinOptions = availablePinsForRow(toGroups, rowData.toSetKey, toCtx, "to", rowData.id, rowData.toPinId, sameConnector ? rowData.fromPinId : null);
    if (!rowData.toPinId && toPinOptions.length > 0) rowData.toPinId = toPinOptions[0].id;
    const toPin = toGroup && toGroup.pins.find(p => p.id === rowData.toPinId);

    const toPinTd = document.createElement("td");
    const toPinSel = document.createElement("select");
    if (toPinOptions.length === 0) {
      toPinSel.appendChild(new Option("— none —", ""));
      toPinSel.disabled = true;
    } else {
      for (const p of toPinOptions) toPinSel.appendChild(new Option(p.label, p.id));
      toPinSel.value = rowData.toPinId || "";
    }
    toPinSel.onchange = () => { rowData.toPinId = toPinSel.value; renderPickTable(); };
    toPinTd.appendChild(toPinSel);
    tr.appendChild(toPinTd);

    const toSigTd = document.createElement("td");
    toSigTd.className = "pick-signal";
    toSigTd.textContent = (toPin && toPin.signal) || "—";
    tr.appendChild(toSigTd);

    const toSetTd = setSelectCell(toGroups, toSpans[idx], rowData.toSetKey, (newKey) => {
      const span = toSpans[idx];
      for (let k = idx; k < idx + span; k++) {
        connectPickRows[k].toSetKey = newKey;
        connectPickRows[k].toPinId = null;
      }
      renderPickTable();
    });
    if (toSetTd) tr.appendChild(toSetTd);

    const tdDel = document.createElement("td");
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "mapping-remove";
    delBtn.textContent = "✕";
    delBtn.onclick = () => { connectPickRows = connectPickRows.filter(r => r.id !== rowData.id); renderPickTable(); };
    tdDel.appendChild(delBtn);
    tr.appendChild(tdDel);

    connectPickBodyEl.appendChild(tr);
  });

  updateCreateConnectButton();
}

// "+ Add Set": explicitly pick which set on each side to add, rather than
// defaulting to the first set every time (which used to make every new row
// collide with — and merge into — whatever already sat in "Set 1").
document.getElementById("btn-add-mapping").onclick = () => {
  const { fromGroups, toGroups, fromCtx, toCtx } = connectModalState;
  const fromKey = document.getElementById("add-set-from").value;
  const toKey = document.getElementById("add-set-to").value;
  const fromGroup = fromGroups.find(g => g.key === fromKey);
  const toGroup = toGroups.find(g => g.key === toKey);
  if (!fromGroup || !toGroup) return;

  const usedKeys = usedPinKeys();
  for (const row of connectPickRows) {
    if (row.fromPinId) usedKeys.add(pinKey(fromCtx.instanceId, fromCtx.connectorId, row.fromPinId));
    if (row.toPinId) usedKeys.add(pinKey(toCtx.instanceId, toCtx.connectorId, row.toPinId));
  }

  const pairs = pairPinsInGroups(fromGroup, toGroup, usedKeys, fromCtx, toCtx);
  if (pairs.length === 0) {
    setStatus(`No available/compatible pins left between ${fromGroup.name} and ${toGroup.name}`);
    return;
  }
  for (const [fp, tp] of pairs) {
    connectPickRows.push({ id: genId(), fromSetKey: fromKey, fromPinId: fp.id, toSetKey: toKey, toPinId: tp.id });
  }
  renderPickTable();
};
document.getElementById("btn-cancel-connect").onclick = () => closeConnectModal();

document.getElementById("btn-create-connect").onclick = () => {
  const { existingHarness, fromConn, toConn, fromConnector, toConnector, reroot } = connectModalState;

  const pinPairs = [];
  for (const row of connectPickRows) {
    if (!row.fromPinId || !row.toPinId) continue;
    const fp = fromConnector.pins.find(p => p.id === row.fromPinId);
    const tp = toConnector.pins.find(p => p.id === row.toPinId);
    if (fp && tp) pinPairs.push([fp, tp]);
  }

  if (pinPairs.length === 0) {
    alert("Pick at least one pin on both sides for a wire.");
    return;
  }

  const harness = commitBranch(existingHarness, fromConn, toConn, pinPairs, reroot);
  closeConnectModal();
  selectHarness(harness.id);
  const totalWires = harness.branches.reduce((n, b) => n + b.connections.length, 0);
  setStatus(`${harness.label}: ${harness.branches.length} destination(s), ${totalWires} wire(s) total`);
};

function deleteHarness(harnessId) {
  state.project.harnesses = state.project.harnesses.filter(h => h.id !== harnessId);
  selectNone();
  render();
  renderHarnessList();
}

function deleteConnection(harness, branch, connId) {
  branch.connections = branch.connections.filter(c => c.id !== connId);
  if (branch.connections.length === 0) {
    harness.branches = harness.branches.filter(b => b.id !== branch.id);
  }
  if (harness.branches.length === 0) {
    deleteHarness(harness.id);
    return;
  }
  render();
  renderHarnessList();
  renderDrawer();
}

function deleteBranch(harness, branchId) {
  harness.branches = harness.branches.filter(b => b.id !== branchId);
  if (harness.branches.length === 0) {
    deleteHarness(harness.id);
    return;
  }
  render();
  renderProps();
  renderHarnessList();
  renderDrawer();
}

// ---------- Instance placement / deletion ----------

function placeDevice(deviceId, x, y) {
  const device = state.devices[deviceId];
  const { width, height } = deviceBoxSize(device);
  const instance = {
    instance_id: genId(),
    device_id: deviceId,
    device_version: device.version, // records which device version was used when placed
    x: Math.max(0, x - width / 2),
    y: Math.max(0, y - height / 2),
    label: "",
  };

  // Multiple instances of the same device would otherwise all show the same
  // default name (e.g. three unlabeled "DSUB-9 Receiving Unit"s) — number
  // them "(1)", "(2)", ... so they stay distinguishable everywhere a name is
  // shown. Only touches instances that haven't been given a custom label.
  const existing = state.project.instances.filter(i => i.device_id === deviceId);
  if (existing.length > 0) {
    if (existing.length === 1 && !existing[0].label) {
      existing[0].label = `${device.name} (1)`;
    }
    instance.label = `${device.name} (${existing.length + 1})`;
  }

  state.project.instances.push(instance);
  state.pendingPlaceDeviceId = null;
  document.querySelectorAll(".device-card").forEach(el => el.classList.remove("selected"));
  selectInstance(instance.instance_id);
  setStatus(`Placed ${instance.label || device.name}`);
}

function deleteInstance(instanceId) {
  state.project.instances = state.project.instances.filter(i => i.instance_id !== instanceId);
  const remaining = [];
  for (const harness of state.project.harnesses) {
    if (harness.from_instance === instanceId) continue; // trunk device removed: whole harness goes
    harness.branches = harness.branches.filter(b => b.to_instance !== instanceId);
    if (harness.branches.length > 0) remaining.push(harness);
  }
  state.project.harnesses = remaining;
  selectNone();
  render();
  renderHarnessList();
}

// ---------- Selection / properties panel ----------

function selectInstance(instanceId) {
  state.selectedInstance = instanceId;
  state.selectedHarness = null;
  render();
  renderProps();
  renderHarnessList();
  hideDrawer();
}

function selectHarness(harnessId) {
  state.selectedHarness = harnessId;
  state.selectedInstance = null;
  render();
  renderProps();
  renderHarnessList();
  renderDrawer();
}

function selectNone() {
  state.selectedInstance = null;
  state.selectedHarness = null;
  renderProps();
  renderHarnessList();
  hideDrawer();
}

function renderProps() {
  const body = document.getElementById("props-body");
  body.innerHTML = "";

  if (state.selectedInstance) {
    const inst = getInstance(state.selectedInstance);
    const device = state.devices[inst.device_id];

    body.appendChild(mkInput("Instance Label", inst.label || "", (v) => { inst.label = v; render(); }));

    const info = document.createElement("p");
    info.className = "hint";
    info.textContent = `${device.name} (${device.part_number || "no P/N"}) — ${device.connectors.length} connector(s)`;
    body.appendChild(info);

    const delBtn = document.createElement("button");
    delBtn.textContent = "Delete Instance";
    delBtn.className = "danger";
    delBtn.onclick = () => deleteInstance(inst.instance_id);
    body.appendChild(delBtn);
    return;
  }

  if (state.selectedHarness) {
    const harness = getHarness(state.selectedHarness);
    const fromInst = getInstance(harness.from_instance);
    const fromDevice = fromInst ? state.devices[fromInst.device_id] : null;
    const fromName = fromInst ? (fromInst.label || fromDevice.name) : "?";
    const totalWires = harness.branches.reduce((n, b) => n + b.connections.length, 0);

    body.appendChild(mkInput("Harness Label", harness.label || "", (v) => { harness.label = v; render(); renderHarnessList(); renderDrawer(); }));
    body.appendChild(mkInput("Trunk Connector Name", harness.from_harness_connector || "", (v) => { harness.from_harness_connector = v; render(); renderDrawer(); }));

    const info = document.createElement("p");
    info.className = "hint";
    info.textContent = `${fromName}.${harness.from_connector} — ${harness.branches.length} destination(s), ${totalWires} wire(s). Full pinout below.`;
    body.appendChild(info);

    body.appendChild(verifyCheckboxRow(
      `Verified by ${userName(fromDevice && fromDevice.responsible_user_id)} (${fromName})`,
      !!harness.from_verified,
      (checked) => { harness.from_verified = checked; }
    ));

    const branchLabel = document.createElement("label");
    branchLabel.textContent = "Destinations";
    body.appendChild(branchLabel);
    for (const branch of harness.branches) {
      const toInst = getInstance(branch.to_instance);
      if (!toInst) continue;
      const toDevice = state.devices[toInst.device_id];
      const toName = toInst.label || toDevice?.name || "?";
      const row = document.createElement("div");
      row.className = "branch-mini-row";
      const text = document.createElement("span");
      const isLoopbackBranch = branch.to_instance === harness.from_instance && branch.to_connector === harness.from_connector;
      const loopSuffix = isLoopbackBranch ? " ↻" : "";
      text.textContent = `${toName}.${branch.to_connector} (${branch.connections.length})${loopSuffix}`;
      const rmBtn = document.createElement("button");
      rmBtn.textContent = "✕";
      rmBtn.title = "Remove this destination";
      rmBtn.onclick = () => deleteBranch(harness, branch.id);
      row.appendChild(text);
      row.appendChild(rmBtn);
      body.appendChild(row);

      body.appendChild(verifyCheckboxRow(
        `Verified by ${userName(toDevice && toDevice.responsible_user_id)}`,
        !!branch.to_verified,
        (checked) => { branch.to_verified = checked; }
      ));
    }

    const delBtn = document.createElement("button");
    delBtn.textContent = "Delete Whole Harness";
    delBtn.className = "danger";
    delBtn.onclick = () => deleteHarness(harness.id);
    body.appendChild(delBtn);
    return;
  }

  const hint = document.createElement("p");
  hint.className = "hint";
  hint.textContent = "Select a device or harness on the canvas.";
  body.appendChild(hint);
}

function mkInput(labelText, value, onChange) {
  const label = document.createElement("label");
  label.textContent = labelText;
  const input = document.createElement("input");
  input.type = "text";
  input.value = value;
  input.oninput = () => onChange(input.value);
  label.appendChild(input);
  return label;
}

function verifyCheckboxRow(labelText, checked, onChange) {
  const label = document.createElement("label");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = checked;
  cb.onchange = () => onChange(cb.checked);
  label.appendChild(cb);
  label.appendChild(document.createTextNode(" " + labelText));
  return label;
}

function renderHarnessList() {
  const list = document.getElementById("harness-list");
  list.innerHTML = "";
  for (const harness of state.project.harnesses) {
    const fromInst = getInstance(harness.from_instance);
    if (!fromInst) continue;
    const row = document.createElement("div");
    row.className = "harness-row";
    if (harness.id === state.selectedHarness) row.style.background = "#eaf1fd";
    const fromName = fromInst.label || state.devices[fromInst.device_id]?.name || "?";
    const totalWires = harness.branches.reduce((n, b) => n + b.connections.length, 0);
    const destNames = harness.branches.map(b => {
      const toInst = getInstance(b.to_instance);
      return toInst ? (toInst.label || state.devices[toInst.device_id]?.name || "?") : "?";
    }).join(", ");
    row.innerHTML = `<div>${harness.label || "H"}: ${escapeHtml(fromName)}.${escapeHtml(harness.from_connector)} → ${escapeHtml(destNames)}</div><div class="h-count">${harness.branches.length} dest, ${totalWires} wire(s)</div>`;
    row.onclick = () => selectHarness(harness.id);
    list.appendChild(row);
  }
  if (state.project.harnesses.length === 0) {
    const hint = document.createElement("p");
    hint.className = "hint";
    hint.textContent = "No harnesses yet.";
    list.appendChild(hint);
  }
}

// ---------- Bottom drawer: dense pinout table ----------

function hideDrawer() {
  document.getElementById("drawer").classList.add("hidden");
}

function renderDrawer() {
  const harness = getHarness(state.selectedHarness);
  const drawer = document.getElementById("drawer");
  if (!harness) { drawer.classList.add("hidden"); return; }
  drawer.classList.remove("hidden");

  const fromInst = getInstance(harness.from_instance);
  const fromDevice = state.devices[fromInst.device_id];
  const fromConnector = getConnector(fromDevice, harness.from_connector);
  const fromName = fromInst.label || fromDevice.name;
  const totalWires = harness.branches.reduce((n, b) => n + b.connections.length, 0);
  const fromCtx = { instanceId: harness.from_instance, connectorId: harness.from_connector };
  const usedKeys = usedPinKeys();

  document.getElementById("drawer-title").textContent =
    `${harness.label || "Harness"} — ${fromName}.${harness.from_connector} (↔ ${harness.from_harness_connector}) · ${harness.branches.length} destination(s), ${totalWires} wires`;

  const tbody = document.getElementById("conn-table-body");
  tbody.innerHTML = "";

  // Sub-headers sit right above the Pin/To columns they describe. Text is
  // only rendered when it changes from whatever was shown last — a blank
  // cell means "still the same connector as above."
  let lastFromHeaderText = null;
  let lastToHeaderText = null;

  for (const branch of harness.branches) {
    const toInst = getInstance(branch.to_instance);
    if (!toInst) continue;
    const toDevice = state.devices[toInst.device_id];
    const toConnector = getConnector(toDevice, branch.to_connector);
    const toName = toInst.label || toDevice.name;
    const toCtx = { instanceId: branch.to_instance, connectorId: branch.to_connector };
    const isLoopback = branch.to_instance === harness.from_instance && branch.to_connector === harness.from_connector;

    const fromHeaderText = `${fromName}.${harness.from_connector}`;
    const toHeaderText = isLoopback ? "↻ Loop Back" : `${toName}.${branch.to_connector}`;

    const headerTr = document.createElement("tr");
    headerTr.className = "branch-header-row";

    const leadTd = document.createElement("td");
    leadTd.colSpan = 3; // Owner(from), Verify(from), Set(from)
    headerTr.appendChild(leadTd);

    const fromHeadTd = document.createElement("td");
    fromHeadTd.className = "sub-header-cell";
    if (fromHeaderText !== lastFromHeaderText) {
      fromHeadTd.innerHTML = `<strong>${escapeHtml(fromHeaderText)}</strong>`;
      lastFromHeaderText = fromHeaderText;
    }
    headerTr.appendChild(fromHeadTd);

    const toHeadTd = document.createElement("td");
    toHeadTd.className = "sub-header-cell";
    if (toHeaderText !== lastToHeaderText) {
      toHeadTd.innerHTML = `<strong>${escapeHtml(toHeaderText)}</strong>`;
      lastToHeaderText = toHeaderText;
    }
    headerTr.appendChild(toHeadTd);

    const trailTd = document.createElement("td");
    trailTd.colSpan = 6; // Set(to), Verify(to), Owner(to), Type, AWG, Length
    headerTr.appendChild(trailTd);

    const headerActionTd = document.createElement("td");
    const removeBranchBtn = document.createElement("button");
    removeBranchBtn.className = "conn-del";
    removeBranchBtn.textContent = "✕ destination";
    removeBranchBtn.title = "Remove this destination and its wires";
    removeBranchBtn.onclick = () => deleteBranch(harness, branch.id);
    headerActionTd.appendChild(removeBranchBtn);
    headerTr.appendChild(headerActionTd);
    tbody.appendChild(headerTr);

    const ordered = orderConnectionsForDisplay({ connections: branch.connections }, fromConnector);

    // Rows sharing the same set key sit adjacent (orderConnectionsForDisplay
    // already groups them) — merge their Set Name and Set Type cells into one
    // spanning cell each, instead of repeating per pin's row. Set Type is a
    // property of the whole set/pair, so changing it applies to every
    // connection in that group at once.
    const keyCounts = {};
    const keyMembers = {};
    ordered.forEach(item => {
      keyCounts[item.key] = (keyCounts[item.key] || 0) + 1;
      (keyMembers[item.key] = keyMembers[item.key] || []).push(item.conn);
    });
    let lastKey = null;

    ordered.forEach((item) => {
      const conn = item.conn;
      const isGroupStart = item.key !== lastKey;
      if (isGroupStart) lastKey = item.key;
      const tr = document.createElement("tr");

      const tdFromOwner = document.createElement("td");
      tdFromOwner.className = "conn-owner";
      tdFromOwner.textContent = userName(fromDevice && fromDevice.responsible_user_id);
      tr.appendChild(tdFromOwner);

      const tdFromVerify = document.createElement("td");
      const fromVerifyInput = document.createElement("input");
      fromVerifyInput.type = "checkbox";
      fromVerifyInput.checked = !!conn.from_verified;
      fromVerifyInput.title = `Verified by ${userName(fromDevice && fromDevice.responsible_user_id)}`;
      fromVerifyInput.onchange = () => { conn.from_verified = fromVerifyInput.checked; };
      tdFromVerify.appendChild(fromVerifyInput);
      tr.appendChild(tdFromVerify);

      if (isGroupStart) {
        const tdSet = document.createElement("td");
        const fromPinDef = fromConnector.pins.find(p => p.id === conn.from_pin);
        tdSet.textContent = (fromPinDef && fromPinDef.set) || "—";
        tdSet.className = "conn-set";
        tdSet.rowSpan = keyCounts[item.key];
        tr.appendChild(tdSet);
      }

      tr.appendChild(pinSelectCell(fromConnector, fromCtx, conn.from_pin, usedKeys, (v) => { conn.from_pin = v; }));

      if (isLoopback) {
        // No real destination device to show — just a jumper. Show one
        // merged cell spanning the set's rows with a vertical line, to
        // indicate this pin loops to the other pin(s) in its set.
        if (isGroupStart) {
          const tdLoop = document.createElement("td");
          tdLoop.colSpan = 4; // Pin(to), Set(to), Verify(to), Owner(to)
          tdLoop.className = "loop-indicator-cell";
          tdLoop.rowSpan = keyCounts[item.key];
          tdLoop.innerHTML = '<span class="loop-line" title="Loops to the other pin in this set"></span>';
          tr.appendChild(tdLoop);
        }
      } else {
        tr.appendChild(pinSelectCell(toConnector, toCtx, conn.to_pin, usedKeys, (v) => { conn.to_pin = v; }));

        const tdToSet = document.createElement("td");
        const toPinDef = toConnector.pins.find(p => p.id === conn.to_pin);
        tdToSet.textContent = (toPinDef && toPinDef.set) || "—";
        tdToSet.className = "conn-set";
        tr.appendChild(tdToSet);

        const tdToVerify = document.createElement("td");
        const toVerifyInput = document.createElement("input");
        toVerifyInput.type = "checkbox";
        toVerifyInput.checked = !!conn.to_verified;
        toVerifyInput.title = `Verified by ${userName(toDevice && toDevice.responsible_user_id)}`;
        toVerifyInput.onchange = () => { conn.to_verified = toVerifyInput.checked; };
        tdToVerify.appendChild(toVerifyInput);
        tr.appendChild(tdToVerify);

        const tdToOwner = document.createElement("td");
        tdToOwner.className = "conn-owner";
        tdToOwner.textContent = userName(toDevice && toDevice.responsible_user_id);
        tr.appendChild(tdToOwner);
      }

      if (isGroupStart) {
        const groupMembers = keyMembers[item.key];
        const tdType = document.createElement("td");
        const typeSelect = document.createElement("select");
        for (const [value, label] of WIRE_TYPES) typeSelect.appendChild(new Option(label, value));
        typeSelect.value = (groupMembers[0] && groupMembers[0].wire_type) || "none";
        typeSelect.onchange = () => {
          for (const member of groupMembers) member.wire_type = typeSelect.value;
        };
        tdType.rowSpan = keyCounts[item.key];
        tdType.appendChild(typeSelect);
        tr.appendChild(tdType);
      }

      const tdAwg = document.createElement("td");
      const awgInput = document.createElement("input");
      awgInput.type = "text";
      awgInput.setAttribute("list", "awg-list");
      awgInput.value = conn.awg || "";
      awgInput.oninput = () => { conn.awg = awgInput.value; };
      tdAwg.appendChild(awgInput);
      tr.appendChild(tdAwg);

      const tdLength = document.createElement("td");
      const lengthInput = document.createElement("input");
      lengthInput.type = "text";
      lengthInput.placeholder = "e.g. 1.5m";
      lengthInput.value = conn.length || "";
      lengthInput.oninput = () => { conn.length = lengthInput.value; };
      tdLength.appendChild(lengthInput);
      tr.appendChild(tdLength);

      const tdDel = document.createElement("td");
      const delBtn = document.createElement("button");
      delBtn.className = "conn-del";
      delBtn.textContent = "✕";
      delBtn.title = "Delete connection";
      delBtn.onclick = () => deleteConnection(harness, branch, conn.id);
      tdDel.appendChild(delBtn);
      tr.appendChild(tdDel);

      tbody.appendChild(tr);
    });
  }

  renderAddConnRow(harness);
}

// Pin dropdown for an existing connection's from/to cell: only lists pins
// that are available (not wired elsewhere) plus whichever pin is currently
// assigned here, so the field never loses its own selection.
function pinSelectCell(connector, ctx, selectedPinId, usedKeys, onChange) {
  const td = document.createElement("td");
  const select = document.createElement("select");
  for (const pin of connector.pins) {
    const isUsedElsewhere = usedKeys.has(pinKey(ctx.instanceId, ctx.connectorId, pin.id)) && pin.id !== selectedPinId;
    if (isUsedElsewhere) continue;
    const opt = document.createElement("option");
    opt.value = pin.id;
    opt.textContent = pin.signal ? `${pin.label} (${pin.signal})` : pin.label;
    if (pin.id === selectedPinId) opt.selected = true;
    select.appendChild(opt);
  }
  select.onchange = () => onChange(select.value);
  td.appendChild(select);
  return td;
}

// Same "Add Set" pattern as the Connect Sets popup: pick a branch, then an
// explicit set (or spare pin) on each side, and add it — rather than a
// single ad-hoc pin pair. A spare/ungrouped pin is just its own 1-pin group,
// so picking a lone pin still works the same way it always did.
// Opens the Connect Sets popup (with a Unit selector for which destination
// to add to) instead of picking sets inline in the drawer.
function renderAddConnRow(harness) {
  const container = document.getElementById("add-conn-row");
  container.innerHTML = "";
  if (harness.branches.length === 0) return;

  const addBtn = document.createElement("button");
  addBtn.textContent = "+ Add Set";
  addBtn.onclick = () => openAddSetModalForHarness(harness);
  container.appendChild(addBtn);
}

document.getElementById("btn-close-drawer").onclick = () => selectNone();

// ---------- CSV export of the harness table ----------
// One row per wire, in the same order as the table (sets kept together), with
// both ends spelled out so the file stands on its own in a spreadsheet. Uses
// the harness as it is on screen, including edits that aren't saved yet.

const CSV_COLUMNS = [
  "Harness", "Destination", "Loopback",
  "From device", "From connector", "From mating connector", "From pin", "From signal", "From set", "From owner", "From verified",
  "To device", "To connector", "To mating connector", "To pin", "To signal", "To set", "To owner", "To verified",
  "Wire type", "AWG", "Length",
];

function harnessCsvRows(harness) {
  const fromInst = getInstance(harness.from_instance);
  const fromDevice = state.devices[fromInst.device_id];
  const fromConnector = getConnector(fromDevice, harness.from_connector);
  const fromName = fromInst.label || fromDevice.name;
  const pinDef = (connector, pinId) => (connector && connector.pins.find(p => p.id === pinId)) || null;
  const wireTypeLabel = value => (WIRE_TYPES.find(([v]) => v === (value || "none")) || [null, value])[1];
  const yesNo = value => (value ? "yes" : "no");

  const rows = [];
  harness.branches.forEach((branch, branchIdx) => {
    const toInst = getInstance(branch.to_instance);
    if (!toInst) return;
    const toDevice = state.devices[toInst.device_id];
    const toConnector = getConnector(toDevice, branch.to_connector);
    const toName = toInst.label || toDevice.name;
    const isLoopback = branch.to_instance === harness.from_instance && branch.to_connector === harness.from_connector;

    for (const { conn } of orderConnectionsForDisplay({ connections: branch.connections }, fromConnector)) {
      const fp = pinDef(fromConnector, conn.from_pin);
      const tp = pinDef(toConnector, conn.to_pin);
      rows.push([
        harness.label || "Harness", branchIdx + 1, yesNo(isLoopback),
        fromName, harness.from_connector, harness.from_harness_connector || "",
        fp ? fp.label : conn.from_pin, fp ? fp.signal : "", fp ? fp.set : "",
        userName(fromDevice.responsible_user_id), yesNo(conn.from_verified),
        toName, branch.to_connector, isLoopback ? harness.from_harness_connector || "" : branch.to_harness_connector || "",
        tp ? tp.label : conn.to_pin, tp ? tp.signal : "", tp ? tp.set : "",
        userName(toDevice.responsible_user_id), yesNo(isLoopback ? conn.from_verified : conn.to_verified),
        wireTypeLabel(conn.wire_type), conn.awg || "", conn.length || "",
      ]);
    }
  });
  return rows;
}

function toCsv(rows) {
  const cell = value => {
    const s = value === null || value === undefined ? "" : String(value);
    return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return rows.map(r => r.map(cell).join(",")).join("\r\n") + "\r\n";
}

function downloadText(filename, text, mime) {
  // The BOM makes Excel read the file as UTF-8 (↔, ↻, accented names, ...).
  const blob = new Blob(["\ufeff" + text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.getElementById("btn-export-csv").onclick = () => {
  const harness = getHarness(state.selectedHarness);
  if (!harness) return;
  const rows = harnessCsvRows(harness);
  if (rows.length === 0) { setStatus("This harness has no wires to export yet"); return; }
  const safe = s => String(s).replace(/[\\/:*?"<>|]+/g, "_").trim();
  const projectName = document.getElementById("project-name").value || state.project.name || "Harness";
  downloadText(`${safe(projectName)} - ${safe(harness.label || "Harness")}.csv`, toCsv([CSV_COLUMNS, ...rows]), "text/csv;charset=utf-8");
  setStatus(`Exported ${rows.length} wire${rows.length === 1 ? "" : "s"} from ${harness.label || "harness"}`);
};

// ---------- Device library ----------

async function loadDeviceLibrary() {
  const res = await api("/api/devices");
  const list = await res.json();
  for (const d of list) state.devices[d.id] = d;

  const container = document.getElementById("device-list");
  container.innerHTML = "";
  for (const d of list) {
    const pinCount = d.connectors.reduce((n, c) => n + c.pins.length, 0);
    const card = document.createElement("div");
    card.className = "device-card";
    card.innerHTML = `
      <button type="button" class="dev-edit" title="Edit device">✎</button>
      <a class="dev-open" href="${d.url}" target="_blank" title="Open in Osmia">↗</a>
      <div class="dev-title">${escapeHtml(d.name)}</div>
      <div class="dev-sub">${d.connectors.length} connector(s), ${pinCount} pins${d.part_number ? " · " + escapeHtml(d.part_number) : ""}</div>
      <div class="dev-owner">Owner: ${escapeHtml(userName(d.responsible_user_id))}</div>
      <button type="button" class="dev-version-btn" title="Version history">v${d.version}</button>
    `;
    card.onclick = () => {
      document.querySelectorAll(".device-card").forEach(el => el.classList.remove("selected"));
      card.classList.add("selected");
      state.pendingPlaceDeviceId = d.id;
      setStatus(`Click the canvas to place "${d.name}"`);
    };
    card.querySelector(".dev-open").onclick = (e) => e.stopPropagation();
    card.querySelector(".dev-edit").onclick = (e) => {
      e.stopPropagation();
      openDeviceModal(d);
    };
    card.querySelector(".dev-version-btn").onclick = (e) => {
      e.stopPropagation();
      openVersionsModal("device", d.id, d.version);
    };
    container.appendChild(card);
  }
}

function userName(userId) {
  if (!userId) return "Unassigned";
  const u = state.users.find(u => u.id === userId);
  return u ? u.name : "Unknown";
}

async function ensureDevicesLoaded(ids) {
  for (const id of ids) {
    if (!state.devices[id]) {
      const res = await api(`/api/devices/${id}`);
      if (res.ok) state.devices[id] = await res.json();
    }
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

// ---------- New Device modal ----------

const deviceModal = document.getElementById("device-modal");
const deviceModalTitle = document.getElementById("device-modal-title");
const connectorBlocksEl = document.getElementById("connector-blocks");
let connectorCounter = 0;
let editingDeviceId = null;

function openDeviceModal(device) {
  editingDeviceId = device ? device.id : null;
  deviceModalTitle.textContent = device ? `Edit Device — ${device.name}` : "New Device";
  document.getElementById("dev-name").value = device ? device.name : "";
  document.getElementById("dev-part").value = device ? (device.part_number || "") : "";
  document.getElementById("dev-color").value = device ? (device.color || "#3b7dd8") : "#3b7dd8";
  const userSelect = document.getElementById("dev-user");
  userSelect.innerHTML = '<option value="">— unassigned —</option>';
  for (const u of state.users) userSelect.appendChild(new Option(u.name, u.id));
  userSelect.value = device ? (device.responsible_user_id || "") : "";
  document.getElementById("dev-origin").value = device ? (device.origin || "in_house") : "in_house";
  connectorBlocksEl.innerHTML = "";
  connectorCounter = 0;
  if (device) {
    for (const connector of device.connectors) {
      addConnectorBlock(connector.id, connector.side, connector.pins);
    }
  } else {
    addConnectorBlock("J01", "left");
    addConnectorBlock("J02", "right");
  }
  deviceModal.classList.remove("hidden");
}

function addConnectorBlock(defaultId, defaultSide, pins) {
  connectorCounter += 1;
  const block = document.createElement("div");
  block.className = "connector-block";
  block.innerHTML = `
    <div class="connector-block-header">
      <input type="text" class="conn-id" placeholder="Connector ID e.g. J01" value="${escapeHtml(defaultId || "J0" + connectorCounter)}">
      <select class="conn-side">
        <option value="left" ${defaultSide === "left" ? "selected" : ""}>Left side</option>
        <option value="right" ${defaultSide === "right" ? "selected" : ""}>Right side</option>
      </select>
      <button type="button" class="conn-remove">✕</button>
    </div>
    <div class="conn-pin-rows"></div>
    <div class="conn-pin-actions">
      <button type="button" class="conn-add-pin">+ Add Pin</button>
      <button type="button" class="conn-add-set">+ Add Pin Set</button>
    </div>
  `;
  block.querySelector(".conn-remove").onclick = () => block.remove();
  const pinRows = block.querySelector(".conn-pin-rows");
  block.querySelector(".conn-add-pin").onclick = () => {
    addPinRow(pinRows, "", "");
  };
  block.querySelector(".conn-add-set").onclick = () => {
    addPinSetBlock(pinRows, [{ label: "", signal: "" }, { label: "", signal: "" }], "");
  };
  if (pins && pins.length) {
    populatePinsIntoContainer(pinRows, pins);
  } else {
    addPinRow(pinRows, "1", "");
    addPinRow(pinRows, "2", "");
  }
  connectorBlocksEl.appendChild(block);
}

// A "pin set" groups related pins (e.g. a DSUB pair: pin 1 = PWR, pin 13 = GND)
// so they are edited and later displayed together instead of scattered by number.
function addPinSetBlock(container, pins, setLabel) {
  const block = document.createElement("div");
  block.className = "pin-set";
  block.innerHTML = `
    <div class="pin-set-header">
      <input type="text" class="set-label" placeholder="Set label (optional, e.g. Pair 1)" value="${escapeHtml(setLabel || "")}">
      <button type="button" class="set-add-pin">+ Pin</button>
      <button type="button" class="set-remove">✕ Remove Set</button>
    </div>
    <div class="pin-set-rows"></div>
  `;
  const rows = block.querySelector(".pin-set-rows");
  block.querySelector(".set-remove").onclick = () => block.remove();
  block.querySelector(".set-add-pin").onclick = () => addPinRow(rows, "", "");
  for (const pin of pins) addPinRow(rows, pin.label, pin.signal);
  container.appendChild(block);
}

// Rebuilds the editor UI from a saved pins array, re-grouping consecutive
// pins that share the same non-empty "set" value back into a pin-set block.
function populatePinsIntoContainer(container, pins) {
  let i = 0;
  while (i < pins.length) {
    const pin = pins[i];
    if (pin.set) {
      const group = [pin];
      let j = i + 1;
      while (j < pins.length && pins[j].set === pin.set) { group.push(pins[j]); j++; }
      addPinSetBlock(container, group, pin.set);
      i = j;
    } else {
      addPinRow(container, pin.label, pin.signal);
      i += 1;
    }
  }
}

// Walks a connector's pin-rows container (loose rows plus pin-set blocks, in
// DOM order) and flattens it back into a pins array with each pin's "set" key.
function collectPinsFromContainer(container) {
  const collected = [];
  let autoSetCounter = 0;
  for (const child of container.children) {
    if (child.classList.contains("pin-row")) {
      collected.push({ row: child, set: "" });
    } else if (child.classList.contains("pin-set")) {
      autoSetCounter += 1;
      const labelInput = child.querySelector(".set-label");
      const setId = labelInput.value.trim() || `set-${autoSetCounter}`;
      child.querySelectorAll(".pin-row").forEach(row => collected.push({ row, set: setId }));
    }
  }
  return collected.map((p, idx) => ({
    id: String(idx + 1),
    label: p.row.querySelector(".pin-label").value.trim() || String(idx + 1),
    signal: p.row.querySelector(".pin-signal").value.trim(),
    set: p.set,
  }));
}

function addPinRow(container, label, signal) {
  const row = document.createElement("div");
  row.className = "pin-row";
  row.innerHTML = `
    <input type="text" placeholder="Pin label" value="${escapeHtml(label || "")}" class="pin-label">
    <input type="text" placeholder="Signal (optional)" value="${escapeHtml(signal || "")}" class="pin-signal">
    <button type="button" class="pin-remove">✕</button>
  `;
  row.querySelector(".pin-remove").onclick = () => row.remove();
  container.appendChild(row);
}

document.getElementById("btn-new-device").onclick = () => openDeviceModal(null);
document.getElementById("btn-cancel-device").onclick = () => { deviceModal.classList.add("hidden"); editingDeviceId = null; };
document.getElementById("btn-add-connector").onclick = () => addConnectorBlock("J0" + (connectorCounter + 1), "left");

document.getElementById("btn-save-device").onclick = async () => {
  const name = document.getElementById("dev-name").value.trim();
  if (!name) { alert("Device needs a name."); return; }

  const blocks = [...connectorBlocksEl.querySelectorAll(".connector-block")];
  if (blocks.length === 0) { alert("Add at least one connector."); return; }

  const connectors = blocks.map((block, cidx) => {
    const id = block.querySelector(".conn-id").value.trim() || `J${cidx + 1}`;
    const side = block.querySelector(".conn-side").value;
    const pins = collectPinsFromContainer(block.querySelector(".conn-pin-rows"));
    return { id, side, pins };
  });

  if (connectors.some(c => c.pins.length === 0)) { alert("Every connector needs at least one pin."); return; }

  const device = {
    name,
    part_number: document.getElementById("dev-part").value.trim(),
    color: document.getElementById("dev-color").value,
    responsible_user_id: document.getElementById("dev-user").value || null,
    origin: document.getElementById("dev-origin").value,
    connectors,
  };
  if (editingDeviceId) device.id = editingDeviceId;

  const res = await api("/api/devices", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(device),
  });
  const saved = await res.json();
  state.devices[saved.id] = saved;
  deviceModal.classList.add("hidden");
  const wasEditing = !!editingDeviceId;
  editingDeviceId = null;
  await loadDeviceLibrary();
  if (wasEditing) {
    render();
    renderProps();
    renderHarnessList();
    renderDrawer();
  }
  setStatus(`Saved device "${saved.name}"`);
};

// ---------- Signal Rules modal (global signal-type compatibility) ----------

const signalRulesModal = document.getElementById("signal-rules-modal");
const signalRuleRowsEl = document.getElementById("signal-rule-rows");

async function loadSignalRules() {
  const res = await api("/api/signal-rules");
  const data = await res.json();
  state.signalRules = data.pairs || [];
}

function addRuleRow(sigA, sigB) {
  const row = document.createElement("div");
  row.className = "rule-row";
  row.innerHTML = `
    <input type="text" class="rule-a" placeholder="e.g. PWR" value="${escapeHtml(sigA || "")}">
    <span>↔</span>
    <input type="text" class="rule-b" placeholder="e.g. PWR" value="${escapeHtml(sigB || "")}">
    <button type="button" class="rule-remove">✕</button>
  `;
  row.querySelector(".rule-remove").onclick = () => row.remove();
  signalRuleRowsEl.appendChild(row);
}

function openSignalRulesModal() {
  signalRuleRowsEl.innerHTML = "";
  if (state.signalRules.length === 0) {
    addRuleRow("", "");
  } else {
    for (const [a, b] of state.signalRules) addRuleRow(a, b);
  }
  signalRulesModal.classList.remove("hidden");
}

document.getElementById("btn-signal-rules").onclick = openSignalRulesModal;
document.getElementById("btn-add-rule").onclick = () => addRuleRow("", "");
document.getElementById("btn-cancel-rules").onclick = () => signalRulesModal.classList.add("hidden");

document.getElementById("btn-save-rules").onclick = async () => {
  const pairs = [...signalRuleRowsEl.querySelectorAll(".rule-row")]
    .map(row => [row.querySelector(".rule-a").value.trim(), row.querySelector(".rule-b").value.trim()])
    .filter(([a, b]) => a && b);

  const res = await api("/api/signal-rules", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pairs }),
  });
  const saved = await res.json();
  state.signalRules = saved.pairs || [];
  signalRulesModal.classList.add("hidden");
  renderDrawer();
  setStatus("Signal rules saved");
};

// ---------- Project save / load ----------

async function refreshProjectSelect() {
  const res = await api("/api/projects");
  const list = await res.json();
  const select = document.getElementById("project-select");
  select.innerHTML = '<option value="">Load project…</option>';
  for (const p of list) {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    select.appendChild(opt);
  }
}

function updateProjectVersionBadge() {
  const badge = document.getElementById("project-version-badge");
  const versionsBtn = document.getElementById("btn-project-versions");
  if (state.project.id && state.project.version) {
    badge.textContent = `v${state.project.version}`;
    badge.classList.remove("hidden");
    versionsBtn.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
    versionsBtn.classList.add("hidden");
  }
}

document.getElementById("btn-new-project").onclick = () => {
  state.project = { id: null, name: "Untitled Harness", instances: [], harnesses: [] };
  document.getElementById("project-name").value = state.project.name;
  document.getElementById("project-select").value = "";
  updateProjectVersionBadge();
  selectNone();
  render();
  setStatus("New project");
};

document.getElementById("project-name").oninput = (e) => {
  state.project.name = e.target.value;
};

document.getElementById("btn-save-project").onclick = async () => {
  state.project.name = document.getElementById("project-name").value || "Untitled Harness";
  const res = await api("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.project),
  });
  const saved = await res.json();
  state.project = saved;
  await refreshProjectSelect();
  document.getElementById("project-select").value = saved.id;
  updateProjectVersionBadge();
  setStatus(`Project saved as v${saved.version}`);
};

document.getElementById("project-select").onchange = async (e) => {
  const id = e.target.value;
  if (!id) return;
  const res = await api(`/api/projects/${id}`);
  if (!res.ok) return;
  const project = await res.json();
  await ensureDevicesLoaded(project.instances.map(i => i.device_id));
  state.project = project;
  document.getElementById("project-name").value = project.name;
  updateProjectVersionBadge();
  selectNone();
  render();
  setStatus(`Loaded "${project.name}"`);
};

document.getElementById("btn-project-versions").onclick = () => {
  if (!state.project.id) return;
  openVersionsModal("project", state.project.id, state.project.version);
};

document.getElementById("btn-delete-project").onclick = async () => {
  if (!state.project.id) { setStatus("Nothing to delete"); return; }
  if (!confirm(`Delete project "${state.project.name}"? This deletes ALL of its versions and cannot be undone.`)) return;
  await api(`/api/projects/${state.project.id}`, { method: "DELETE" });
  state.project = { id: null, name: "Untitled Harness", instances: [], harnesses: [] };
  document.getElementById("project-name").value = state.project.name;
  await refreshProjectSelect();
  updateProjectVersionBadge();
  selectNone();
  render();
  setStatus("Project deleted");
};

// ---------- Users (no auth — a name registry for device ownership / verification) ----------

async function loadUsers() {
  const res = await api("/api/users");
  const data = await res.json();
  state.users = data.users || [];
}

function addUserRow(id, name) {
  const row = document.createElement("div");
  row.className = "rule-row";
  row.dataset.userId = id || genId();
  row.innerHTML = `
    <input type="text" class="user-name" placeholder="Name" value="${escapeHtml(name || "")}">
    <button type="button" class="rule-remove">✕</button>
  `;
  row.querySelector(".rule-remove").onclick = () => row.remove();
  document.getElementById("user-rows").appendChild(row);
}

function openUsersModal() {
  const container = document.getElementById("user-rows");
  container.innerHTML = "";
  if (state.users.length === 0) addUserRow(null, "");
  else for (const u of state.users) addUserRow(u.id, u.name);
  document.getElementById("users-modal").classList.remove("hidden");
}

document.getElementById("btn-users").onclick = () => window.open(OSMIA.usersUrl, "_blank");  // Osmia: users live in the Users module
document.getElementById("btn-add-user").onclick = () => addUserRow(null, "");
document.getElementById("btn-cancel-users").onclick = () => document.getElementById("users-modal").classList.add("hidden");

document.getElementById("btn-save-users").onclick = async () => {
  const rows = [...document.getElementById("user-rows").querySelectorAll(".rule-row")];
  const users = rows
    .map(row => ({ id: row.dataset.userId, name: row.querySelector(".user-name").value.trim() }))
    .filter(u => u.name);

  const res = await api("/api/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ users }),
  });
  const saved = await res.json();
  state.users = saved.users || [];
  document.getElementById("users-modal").classList.add("hidden");
  await loadDeviceLibrary();
  renderProps();
  setStatus("Users saved");
};

// ---------- Versions modal (shared by devices and projects) ----------

const versionsModal = document.getElementById("versions-modal");
let versionsModalState = null; // { kind: "device" | "project", id }

async function openVersionsModal(kind, id, currentVersion) {
  versionsModalState = { kind, id };
  document.getElementById("versions-modal-title").textContent = kind === "device" ? "Device Versions" : "Project Versions";
  const listEl = document.getElementById("versions-list");
  listEl.innerHTML = "<p class=\"hint\">Loading…</p>";
  versionsModal.classList.remove("hidden");

  const res = await api(`/api/${kind}s/${id}/versions`);
  const data = await res.json();
  const versions = (data.versions || []).slice().sort((a, b) => b - a);

  listEl.innerHTML = "";
  for (const v of versions) {
    const row = document.createElement("div");
    row.className = "version-row";
    const label = document.createElement("span");
    label.textContent = `v${v}`;
    if (v === currentVersion) {
      const tag = document.createElement("span");
      tag.className = "version-current";
      tag.textContent = "CURRENT";
      label.appendChild(tag);
      row.appendChild(label);
    } else {
      row.appendChild(label);
      const activateBtn = document.createElement("button");
      activateBtn.textContent = "Make Current";
      activateBtn.onclick = () => activateVersion(kind, id, v);
      row.appendChild(activateBtn);
    }
    listEl.appendChild(row);
  }
}

async function activateVersion(kind, id, version) {
  const res = await api(`/api/${kind}s/${id}/versions/${version}/activate`, { method: "POST" });
  if (!res.ok) { setStatus("Could not activate that version"); return; }
  const data = await res.json();

  if (kind === "device") {
    state.devices[id] = data;
    await loadDeviceLibrary();
    render();
    renderProps();
    renderHarnessList();
    renderDrawer();
  } else {
    await ensureDevicesLoaded(data.instances.map(i => i.device_id));
    state.project = data;
    document.getElementById("project-name").value = data.name;
    updateProjectVersionBadge();
    selectNone();
    render();
  }

  versionsModal.classList.add("hidden");
  setStatus(`${kind === "device" ? "Device" : "Project"} switched to v${version}`);
}

document.getElementById("btn-close-versions").onclick = () => versionsModal.classList.add("hidden");

// ---------- Init ----------

(async function init() {
  await loadSignalRules();
  await loadUsers();
  await loadDeviceLibrary();
  await refreshProjectSelect();
  render();
  renderHarnessList();
  const wanted = new URLSearchParams(location.search).get("project");
  if (wanted) {
    const select = document.getElementById("project-select");
    select.value = wanted;
    if (select.value === wanted) select.onchange({ target: select });
  }
})();

/**
 * PipShed — regime chips + ICT signal tree + chart fetch
 */

const PIP_SECTIONS = [
  {
    title: "Time",
    pills: [
      { key: "kz_london", label: "KZ London", layer: "regime" },
      { key: "kz_newyork", label: "KZ New York", layer: "regime" },
      { key: "kz_london_close", label: "KZ London Close", layer: "regime" },
      { key: "kz_asia", label: "KZ Asia", layer: "regime" },
    ],
  },
  {
    title: "Trend",
    pills: [
      { key: "ema9", label: "EMA 9", layer: "regime" },
      { key: "ema20", label: "EMA 20", layer: "regime" },
      { key: "ema50", label: "EMA 50", layer: "regime" },
      { key: "ema200", label: "EMA 200", layer: "regime" },
      { key: "ema_cross_9_20", label: "EMA Cross 9/20", layer: "both" },
      { key: "ema_cross_9_50", label: "EMA Cross 9/50", layer: "both" },
      { key: "ema_cross_50_200", label: "EMA Cross 50/200", layer: "both" },
    ],
  },
  {
    title: "Momentum",
    pills: [
      { key: "macd_zero", label: "MACD Zero", layer: "regime" },
      { key: "macd_cross", label: "MACD Cross", layer: "signal" },
      { key: "rsi", label: "RSI", layer: "signal" },
      { key: "stochastic", label: "Stochastic", layer: "signal" },
      { key: "cci", label: "CCI", layer: "signal" },
      { key: "williams_r", label: "Williams %R", layer: "signal" },
    ],
  },
  {
    title: "Volatility",
    pills: [
      { key: "bb_squeeze", label: "BB Squeeze", layer: "regime" },
      { key: "atr_filter", label: "ATR Filter", layer: "regime" },
      { key: "bb", label: "BB", layer: "signal" },
    ],
  },
  {
    title: "LIT",
    pills: [
      { key: "sweep", label: "Sweep", layer: "signal" },
      { key: "fvg", label: "FVG", layer: "signal" },
      { key: "bos", label: "BOS", layer: "signal" },
      { key: "order_block", label: "Order Block", layer: "signal" },
      { key: "smt", label: "SMT", layer: "signal" },
    ],
  },
  {
    title: "Candlestick",
    pills: [
      { key: "reversal", label: "Reversal", layer: "signal" },
      { key: "continuation", label: "Continuation", layer: "signal" },
      { key: "indecision", label: "Indecision", layer: "signal" },
    ],
  },
];

const state = {
  instrument: document.getElementById("instrument-select").value,
  timeframe: "5m",
  regime: [],
  tree: { nodes: {}, roots: [], activeNodeId: null },
  mainTab: "regime",
  windowSize: 50,
  windowIndex: 0,
  currentStart: 0,
  currentEnd: 50,
  showVolume: false,
  notional: 1000,
  loading: false,
  lastStats: {},
  _chartKey: null,
  candle_map: {},
  _candleMapLoaded: false,
};

const chartImg = document.getElementById("chart-img");
const equityCard = document.getElementById("equity-card");
const equityImg = document.getElementById("equity-img");
const placeholder = document.getElementById("chart-placeholder");
const tooltip = document.getElementById("tooltip");
const windowLabel = document.getElementById("window-label");
const errorBanner = document.getElementById("error-banner");
const trayRegime = document.getElementById("pill-tray-regime");
const traySignal = document.getElementById("pill-tray-signal");

let _equityObjectUrl = null;
let _pillChartDebounceTimer = null;
let _pillChartAbortController = null;
let _deleteConfirmAbort = null;

function generateId() {
  return "n" + Math.random().toString(36).slice(2, 10);
}

function _reindexTreeAddresses() {
  function walk(prefix, nodeId) {
    const node = state.tree.nodes[nodeId];
    if (!node) return;
    node.address = prefix.slice();
    node.children.forEach((childId, i) => {
      walk(prefix.concat(i), childId);
    });
  }
  state.tree.roots.forEach((rootId, i) => {
    walk([i], rootId);
  });
}

function addRootNode() {
  const id = generateId();
  const address = [state.tree.roots.length];
  state.tree.nodes[id] = {
    id,
    parentId: null,
    children: [],
    address,
    relationship: null,
    window: null,
    pills: [],
  };
  state.tree.roots.push(id);
  if (state.tree.roots.length === 1) {
    state.tree.activeNodeId = id;
  }
  renderTree();
  return id;
}

function addChild(nodeId) {
  const parent = state.tree.nodes[nodeId];
  if (!parent) return;
  const id = generateId();
  const address = parent.address.concat(parent.children.length);
  state.tree.nodes[id] = {
    id,
    parentId: nodeId,
    children: [],
    address,
    relationship: "then",
    window: 10,
    pills: [],
  };
  parent.children.push(id);
  renderTree();
  return id;
}

function addSibling(nodeId) {
  const node = state.tree.nodes[nodeId];
  if (!node) return;
  if (node.parentId == null) {
    const id = generateId();
    const address = [state.tree.roots.length];
    state.tree.nodes[id] = {
      id,
      parentId: null,
      children: [],
      address,
      relationship: null,
      window: null,
      pills: [],
    };
    state.tree.roots.push(id);
    renderTree();
    return id;
  }
  const parent = state.tree.nodes[node.parentId];
  if (!parent) return;
  const id = generateId();
  const address = parent.address.concat(parent.children.length);
  state.tree.nodes[id] = {
    id,
    parentId: node.parentId,
    children: [],
    address,
    relationship: node.relationship,
    window: node.window,
    pills: [],
  };
  parent.children.push(id);
  renderTree();
  return id;
}

function deleteNode(nodeId) {
  const node = state.tree.nodes[nodeId];
  if (!node) return;

  function collectIds(id) {
    const n = state.tree.nodes[id];
    if (!n) return [];
    let out = [id];
    for (const cid of n.children) out = out.concat(collectIds(cid));
    return out;
  }

  const toRemove = new Set(collectIds(nodeId));
  if (node.parentId == null) {
    const idx = state.tree.roots.indexOf(nodeId);
    if (idx >= 0) state.tree.roots.splice(idx, 1);
  } else {
    const par = state.tree.nodes[node.parentId];
    if (par) {
      const ci = par.children.indexOf(nodeId);
      if (ci >= 0) par.children.splice(ci, 1);
    }
  }
  for (const id of toRemove) {
    delete state.tree.nodes[id];
  }
  if (state.tree.activeNodeId != null && toRemove.has(state.tree.activeNodeId)) {
    state.tree.activeNodeId = state.tree.roots[0] ?? null;
  }
  _reindexTreeAddresses();
  renderTree();
}

function updateNode(nodeId, patch) {
  const n = state.tree.nodes[nodeId];
  if (!n || !patch || typeof patch !== "object") return;
  if (Object.prototype.hasOwnProperty.call(patch, "pills")) n.pills = patch.pills;
  if (Object.prototype.hasOwnProperty.call(patch, "relationship")) n.relationship = patch.relationship;
  if (Object.prototype.hasOwnProperty.call(patch, "window")) n.window = patch.window;
  renderTree();
}

const TREE_COLORS = [
  ["#185FA5", "#378ADD", "#85B7EB", "#B5D4F4"],
  ["#534AB7", "#7F77DD", "#AFA9EC", "#CECBF6"],
  ["#993C1D", "#D85A30", "#F0997B", "#F5C4B3"],
  ["#0F6E56", "#1D9E75", "#5DCAA5", "#9FE1CB"],
  ["#854F0B", "#BA7517", "#EF9F27", "#FAC775"],
];

const TREE_TEXT_DARK = ["#042C53", "#26215C", "#4A1E0E", "#0A3D30", "#4A3506"];

const TREE_REL_LABEL_STYLES = [
  { bg: "#E6F1FB", color: "#042C53" },
  { bg: "#EEEDFE", color: "#26215C" },
  { bg: "#FAECE7", color: "#4A1B0C" },
  { bg: "#E1F5EE", color: "#04342C" },
  { bg: "#FAEEDA", color: "#412402" },
];

function initSignalTreePanel() {
  const sg = document.getElementById("signal-graph");
  if (!sg || sg.dataset.treePanelInit === "1") return;
  sg.dataset.treePanelInit = "1";
  sg.innerHTML = `
    <div id="signal-tree-layers" class="signal-tree-layers" aria-hidden="false"></div>
    <div id="signal-tree-canvas">
      <div id="signal-tree-canvas-inner" class="signal-tree-canvas-inner"></div>
    </div>
  `;
}

function rootIndexForNode(nodeId) {
  let id = nodeId;
  for (let guard = 0; guard < 4096; guard++) {
    const n = state.tree.nodes[id];
    if (!n) return 0;
    if (n.parentId == null) {
      const idx = state.tree.roots.indexOf(id);
      return idx >= 0 ? idx : 0;
    }
    id = n.parentId;
  }
  return 0;
}

function assignTreeYIndices() {
  const yById = {};
  let leafY = 0;

  function postOrder(nodeId) {
    const node = state.tree.nodes[nodeId];
    if (!node) return;
    if (!node.children.length) {
      yById[nodeId] = leafY++;
      return;
    }
    for (const cid of node.children) postOrder(cid);
    const ys = node.children.map(cid => yById[cid]).filter(v => Number.isFinite(v));
    yById[nodeId] = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : leafY++;
  }

  for (const rid of state.tree.roots) postOrder(rid);
  return yById;
}

function treeMaxDepth() {
  let m = 0;
  for (const id of Object.keys(state.tree.nodes)) {
    const n = state.tree.nodes[id];
    if (!n?.address?.length) continue;
    m = Math.max(m, n.address.length - 1);
  }
  return m;
}

function formatAddressLabel(addr) {
  if (!addr || !addr.length) return "()";
  return "(" + addr.join(",") + ")";
}

function getNodeGeom(nodeId) {
  const yById = assignTreeYIndices();
  const node = state.tree.nodes[nodeId];
  if (!node) return { left: 0, top: 0 };
  const depth = node.address?.length ? node.address.length - 1 : 0;
  const yIdx = yById[nodeId] ?? 0;
  return { left: depth * 140, top: yIdx * 80 };
}

function closeNodeSheet() {
  const s = document.getElementById("node-sheet");
  if (s) s.remove();
}

function openNodeSheet(nodeId) {
  closeNodeSheet();
  const node = state.tree.nodes[nodeId];
  if (!node) return;
  const isRoot = node.address.length === 1;
  const sheet = document.createElement("div");
  sheet.id = "node-sheet";
  sheet.className = "node-sheet";
  sheet.dataset.editNodeId = nodeId;
  sheet.innerHTML = `
    <div class="node-sheet__header">
      <span class="node-sheet__title">Node ${formatAddressLabel(node.address)}</span>
      <button type="button" class="node-sheet__close">✕</button>
    </div>
    <div class="node-sheet__row">
      <label class="node-sheet__label">Relationship</label>
      <div class="node-sheet__toggle ${isRoot ? "node-sheet__toggle--disabled" : ""}">
        <button type="button" class="node-sheet__rel-btn ${node.relationship === "then" ? "active" : ""}" data-rel="then">then</button>
        <button type="button" class="node-sheet__rel-btn ${node.relationship === "with" ? "active" : ""}" data-rel="with">with</button>
      </div>
    </div>
    <div class="node-sheet__row">
      <label class="node-sheet__label">Window</label>
      <div class="node-sheet__stepper ${isRoot ? "node-sheet__stepper--disabled" : ""}">
        <button type="button" class="node-sheet__step-btn" data-delta="-1">−</button>
        <span class="node-sheet__step-val">${node.window ?? "—"}</span>
        <button type="button" class="node-sheet__step-btn" data-delta="1">+</button>
      </div>
    </div>
  `;
  document.body.appendChild(sheet);
  sheet.querySelector(".node-sheet__close").addEventListener("click", closeNodeSheet);
  if (!isRoot) {
    sheet.querySelectorAll(".node-sheet__rel-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        updateNode(nodeId, { relationship: btn.dataset.rel });
        renderTree();
        sheet.querySelectorAll(".node-sheet__rel-btn").forEach(b =>
          b.classList.toggle("active", b.dataset.rel === btn.dataset.rel)
        );
      });
    });
    sheet.querySelectorAll(".node-sheet__step-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const cur = state.tree.nodes[nodeId];
        if (!cur) return;
        const current = cur.window ?? 10;
        const next = Math.max(1, current + parseInt(btn.dataset.delta, 10));
        updateNode(nodeId, { window: next });
        const valEl = sheet.querySelector(".node-sheet__step-val");
        if (valEl) valEl.textContent = String(next);
      });
    });
  }
}

function showDeleteConfirm(nodeId) {
  if (_deleteConfirmAbort) {
    _deleteConfirmAbort.abort();
    _deleteConfirmAbort = null;
  }
  document.querySelectorAll(".tree-delete-confirm").forEach(el => el.remove());
  const node = state.tree.nodes[nodeId];
  if (!node) return;
  const pills = Array.isArray(node.pills) ? node.pills : [];
  const label = pills.length ? pills.join(" + ") : "(empty)";
  const inner = document.getElementById("signal-tree-canvas-inner");
  if (!inner) return;

  const pop = document.createElement("div");
  pop.className = "tree-delete-confirm";
  pop.innerHTML = `
    <div class="tree-delete-confirm__msg"></div>
    <div class="tree-delete-confirm__btns">
      <button type="button" class="tree-delete-confirm__cancel">Cancel</button>
      <button type="button" class="tree-delete-confirm__ok">Delete</button>
    </div>
  `;
  pop.querySelector(".tree-delete-confirm__msg").textContent =
    `Delete ${label} and all children?`;

  const geom = getNodeGeom(nodeId);
  pop.style.left = `${geom.left + 10}px`;
  pop.style.top = `${geom.top - 70}px`;
  inner.appendChild(pop);

  _deleteConfirmAbort = new AbortController();
  const ac = _deleteConfirmAbort;
  const dismissPop = () => {
    if (pop.isConnected) pop.remove();
    ac.abort();
    if (_deleteConfirmAbort === ac) _deleteConfirmAbort = null;
  };

  pop.querySelector(".tree-delete-confirm__cancel").addEventListener("click", dismissPop);
  pop.querySelector(".tree-delete-confirm__ok").addEventListener("click", () => {
    dismissPop();
    const sheet = document.getElementById("node-sheet");
    if (sheet && sheet.dataset.editNodeId === nodeId) closeNodeSheet();
    deleteNode(nodeId);
  });

  setTimeout(() => {
    document.addEventListener(
      "click",
      e => {
        if (pop.isConnected && !pop.contains(e.target)) dismissPop();
      },
      { capture: true, signal: ac.signal }
    );
  }, 0);
}

function renderTree() {
  const inner = document.getElementById("signal-tree-canvas-inner");
  const layersEl = document.getElementById("signal-tree-layers");
  if (!inner || !layersEl) {
    updatePillTrayLabel();
    return;
  }

  inner.innerHTML = "";
  layersEl.innerHTML = "";

  const maxDepth = treeMaxDepth();
  for (let d = 0; d <= maxDepth; d++) {
    const lab = document.createElement("span");
    lab.className = "signal-tree-layer-label";
    lab.textContent = `layer ${d + 1}`;
    lab.style.left = `${d * 140 + 20}px`;
    layersEl.appendChild(lab);
  }

  const yById = assignTreeYIndices();
  const colWidth = 140;
  const rowHeight = 80;

  const orderedIds = [];
  function walkCollect(id) {
    if (!state.tree.nodes[id]) return;
    orderedIds.push(id);
    for (const cid of state.tree.nodes[id].children) walkCollect(cid);
  }
  for (const rid of state.tree.roots) walkCollect(rid);

  function nodeGeom(nodeId) {
    const node = state.tree.nodes[nodeId];
    if (!node) return null;
    const depth = node.address?.length ? node.address.length - 1 : 0;
    const yIdx = yById[nodeId] ?? 0;
    const left = depth * colWidth;
    const top = yIdx * rowHeight;
    const centerY = top + 30;
    return { left, top, centerY, depth, node };
  }

  function appendConnectorEl(styles) {
    const el = document.createElement("div");
    el.className = "tree-connector";
    el.style.position = "absolute";
    Object.assign(el.style, styles);
    el.style.background = "#B4B2A9";
    inner.appendChild(el);
  }

  for (const parentId of orderedIds) {
    const parent = state.tree.nodes[parentId];
    if (!parent?.children?.length) continue;
    const pGeom = nodeGeom(parentId);
    if (!pGeom) continue;

    const childLayouts = parent.children
      .map(cid => {
        const g = nodeGeom(cid);
        return g ? { id: cid, ...g } : null;
      })
      .filter(Boolean)
      .sort((a, b) => a.centerY - b.centerY);

    if (!childLayouts.length) continue;

    const parentLeft = pGeom.left;
    const parentCentreY = pGeom.centerY;

    appendConnectorEl({
      left: `${parentLeft + 100}px`,
      top: `${parentCentreY - 1}px`,
      width: "20px",
      height: "1.5px",
    });

    const topChildCentreY = childLayouts[0].centerY;
    const bottomChildCentreY = childLayouts[childLayouts.length - 1].centerY;
    const spineH = bottomChildCentreY - topChildCentreY;

    appendConnectorEl({
      left: `${parentLeft + 120}px`,
      top: `${topChildCentreY}px`,
      width: "1.5px",
      height: `${Math.max(0, spineH)}px`,
    });

    for (let i = 0; i < childLayouts.length; i++) {
      const cl = childLayouts[i];
      const childCentreY = cl.centerY;
      appendConnectorEl({
        left: `${parentLeft + 124}px`,
        top: `${childCentreY - 1}px`,
        width: "16px",
        height: "1.5px",
      });

      const childNode = state.tree.nodes[cl.id];
      const rel = childNode?.relationship;
      if (
        childNode &&
        childNode.parentId != null &&
        rel != null &&
        String(rel).length > 0
      ) {
        const rIdx = rootIndexForNode(cl.id) % 5;
        const rs = TREE_REL_LABEL_STYLES[rIdx];
        const relEl = document.createElement("div");
        relEl.className = "tree-rel-label";
        relEl.style.position = "absolute";
        relEl.style.left = `${parentLeft + 124}px`;
        relEl.style.top = `${childCentreY - 9}px`;
        relEl.style.zIndex = "3";
        relEl.style.background = rs.bg;
        relEl.style.color = rs.color;
        relEl.textContent = String(rel);
        inner.appendChild(relEl);
      }
    }

    for (let i = 0; i < childLayouts.length - 1; i++) {
      const mid = (childLayouts[i].centerY + childLayouts[i + 1].centerY) / 2;
      const orEl = document.createElement("div");
      orEl.className = "tree-or-badge";
      orEl.style.position = "absolute";
      orEl.style.left = `${parentLeft + 128}px`;
      orEl.style.top = `${mid - 7}px`;
      orEl.textContent = "OR";
      inner.appendChild(orEl);
    }
  }

  if (state.tree.roots.length > 1) {
    for (let i = 0; i < state.tree.roots.length - 1; i++) {
      const r1 = state.tree.roots[i];
      const r2 = state.tree.roots[i + 1];
      const y1 = yById[r1] * 80 + 30;
      const y2 = yById[r2] * 80 + 30;
      appendConnectorEl({
        left: "15px",
        top: `${y1}px`,
        width: "1.5px",
        height: `${y2 - y1}px`,
      });
      const rootOrEl = document.createElement("div");
      rootOrEl.className = "tree-or-badge";
      rootOrEl.textContent = "OR";
      rootOrEl.style.position = "absolute";
      rootOrEl.style.left = "4px";
      rootOrEl.style.top = `${(y1 + y2) / 2 - 7}px`;
      inner.appendChild(rootOrEl);
    }
  }

  for (const nodeId of orderedIds) {
    const node = state.tree.nodes[nodeId];
    if (!node) continue;
    const depth = node.address?.length ? node.address.length - 1 : 0;
    const col = depth;
    const yIdx = yById[nodeId] ?? 0;

    const rootIdx = rootIndexForNode(nodeId) % 5;
    const shade = Math.min(depth, 3);
    const stripe = TREE_COLORS[rootIdx][shade];
    const textColor = depth <= 1 ? "#fff" : TREE_TEXT_DARK[rootIdx];

    const el = document.createElement("div");
    el.className = "tree-node" + (state.tree.activeNodeId === nodeId ? " tree-node--active" : "");
    el.dataset.id = nodeId;
    el.setAttribute("role", "button");
    el.tabIndex = 0;
    el.style.left = `${col * colWidth}px`;
    el.style.top = `${yIdx * rowHeight}px`;
    el.style.borderLeft = `3px solid ${stripe}`;
    el.style.background = state.tree.activeNodeId === nodeId ? stripe : "#f5f5f5";
    el.style.color = state.tree.activeNodeId === nodeId ? textColor : "#212121";
    if (state.tree.activeNodeId === nodeId) {
      el.style.border = `1px solid ${stripe}`;
    } else {
      el.style.border = "1px solid #e0e0e0";
    }

    const pillsWrap = document.createElement("div");
    pillsWrap.className = "tree-node-pills";
    const pills = Array.isArray(node.pills) ? node.pills : [];
    pills.forEach(pk => {
      const wrap = document.createElement("span");
      wrap.style.display = "inline-flex";
      wrap.style.alignItems = "center";
      wrap.style.gap = "2px";
      wrap.style.marginRight = "4px";

      const chip = document.createElement("span");
      chip.className = "tree-node-pill-chip";
      chip.textContent = pillLabel(pk);
      chip.style.color = "inherit";

      const rm = document.createElement("button");
      rm.type = "button";
      rm.textContent = "×";
      rm.title = "Remove pill";
      rm.style.cssText =
        "padding:0 1px;margin:0;min-width:12px;border:none;background:rgba(0,0,0,0.12);border-radius:2px;cursor:pointer;font-size:9px;line-height:1;color:inherit;";
      rm.addEventListener("click", e => {
        e.stopPropagation();
        const cur = state.tree.nodes[nodeId];
        const curPills = Array.isArray(cur?.pills) ? cur.pills : [];
        updateNode(nodeId, { pills: curPills.filter(p => p !== pk) });
        renderTree();
        fetchChart();
      });

      wrap.appendChild(chip);
      wrap.appendChild(rm);
      pillsWrap.appendChild(wrap);
    });

    const addr = document.createElement("span");
    addr.className = "tree-node-address";
    addr.textContent = formatAddressLabel(node.address);
    addr.style.color = "inherit";
    addr.style.opacity = "0.8";

    el.appendChild(pillsWrap);
    el.appendChild(addr);

    const addChildBtn = document.createElement("button");
    addChildBtn.type = "button";
    addChildBtn.className = "tree-node-btn tree-node-btn--right";
    addChildBtn.textContent = "+";
    addChildBtn.title = "Add child";
    addChildBtn.addEventListener("click", e => {
      e.stopPropagation();
      const newId = addChild(nodeId);
      if (!newId) return;
      state.tree.activeNodeId = newId;
      renderTree();
      openNodeSheet(newId);
    });
    el.appendChild(addChildBtn);

    const addSibBtn = document.createElement("button");
    addSibBtn.type = "button";
    addSibBtn.className = "tree-node-btn tree-node-btn--bottom";
    addSibBtn.textContent = "+";
    addSibBtn.title = "Add OR branch";
    addSibBtn.addEventListener("click", e => {
      e.stopPropagation();
      const newId = addSibling(nodeId);
      if (!newId) return;
      state.tree.activeNodeId = newId;
      renderTree();
      openNodeSheet(newId);
    });
    el.appendChild(addSibBtn);

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "tree-node-delete";
    delBtn.textContent = "×";
    delBtn.title = "Delete node";
    delBtn.addEventListener("click", e => {
      e.stopPropagation();
      showDeleteConfirm(nodeId);
    });
    el.appendChild(delBtn);

    el.addEventListener("click", e => {
      e.stopPropagation();
      state.tree.activeNodeId = nodeId;
      renderTree();
    });
    el.addEventListener("keydown", e => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      state.tree.activeNodeId = nodeId;
      renderTree();
    });

    inner.appendChild(el);
  }

  const totalNodes = orderedIds.length;
  inner.style.minWidth = `${maxDepth * colWidth + 220}px`;
  inner.style.minHeight = `${totalNodes * rowHeight + 40}px`;

  updatePillTrayLabel();
}

function pillLabel(key) {
  for (const sec of PIP_SECTIONS) {
    const p = sec.pills.find(x => x.key === key);
    if (p) return p.label;
  }
  return key;
}

function updatePillTrayLabel() {
  const trayLab = document.getElementById("pill-tray-label");
  if (!trayLab) return;
  if (state.tree.activeNodeId && state.tree.nodes[state.tree.activeNodeId]) {
    const n = state.tree.nodes[state.tree.activeNodeId];
    trayLab.textContent = `Adding to node ${formatAddressLabel(n.address)}`;
  } else {
    trayLab.textContent = "Select a tree node to add pills";
  }
}

function pillDisabled(layer) {
  if (state.mainTab === "regime" && layer === "signal") return true;
  if (state.mainTab === "signal" && layer === "regime") return true;
  return false;
}

function pillActive(key) {
  if (state.mainTab === "regime") return state.regime.includes(key);
  const node = state.tree.activeNodeId ? state.tree.nodes[state.tree.activeNodeId] : null;
  if (!node) return false;
  return Array.isArray(node.pills) && node.pills.includes(key);
}

function renderPillTray(container) {
  if (!container) return;
  container.innerHTML = "";
  for (const sec of PIP_SECTIONS) {
    const block = document.createElement("div");
    block.className = "pill-section";
    const t = document.createElement("div");
    t.className = "pill-section-title";
    t.textContent = sec.title;
    block.appendChild(t);
    const row = document.createElement("div");
    row.className = "pill-row";
    for (const def of sec.pills) {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "pill pill--" + def.layer;
      pill.textContent = def.label;
      pill.dataset.key = def.key;
      if (pillActive(def.key)) pill.classList.add("active");
      if (pillDisabled(def.layer)) pill.classList.add("pill--disabled");
      pill.addEventListener("click", () => onPillClick(def));
      row.appendChild(pill);
    }
    block.appendChild(row);
    container.appendChild(block);
  }
}

function renderAllPillTrays() {
  renderPillTray(trayRegime);
  renderPillTray(traySignal);
}

function onPillClick(def) {
  if (pillDisabled(def.layer)) return;
  if (state.mainTab === "regime") {
    const i = state.regime.indexOf(def.key);
    if (i >= 0) state.regime.splice(i, 1);
    else state.regime.push(def.key);
    renderAllPillTrays();
    scheduleFetchChartAfterPillChange();
    return;
  }
  if (state.mainTab === "signal") {
    const nid = state.tree.activeNodeId;
    if (!nid || !state.tree.nodes[nid]) return;
    const node = state.tree.nodes[nid];
    const pl = Array.isArray(node.pills) ? node.pills.slice() : [];
    const ix = pl.indexOf(def.key);
    if (ix >= 0) pl.splice(ix, 1);
    else if (pl.length < 4) pl.push(def.key);
    updateNode(nid, { pills: pl });
    renderAllPillTrays();
    renderTree();
    scheduleFetchChartAfterPillChange();
  }
}

function setMainTab(tab) {
  state.mainTab = tab;
  document.querySelectorAll(".main-tab").forEach(b => {
    const on = b.dataset.mainTab === tab;
    b.classList.toggle("active", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.getElementById("panel-regime").classList.toggle("active", tab === "regime");
  document.getElementById("panel-regime").toggleAttribute("hidden", tab !== "regime");
  document.getElementById("panel-signal").classList.toggle("active", tab === "signal");
  document.getElementById("panel-signal").toggleAttribute("hidden", tab !== "signal");
  document.getElementById("panel-results").classList.toggle("active", tab === "results");
  document.getElementById("panel-results").toggleAttribute("hidden", tab !== "results");
  if (tab === "signal") {
    initSignalTreePanel();
    renderTree();
  }
  renderAllPillTrays();
}

function buildBody() {
  return {
    instrument: state.instrument,
    timeframe: state.timeframe,
    regime: state.regime.slice(),
    signal_tree: JSON.parse(JSON.stringify(state.tree)),
    window_size: state.windowSize,
    window_index: state.windowIndex,
    show_volume: state.showVolume,
    notional: state.notional,
  };
}

function hideEquityCard() {
  if (equityCard) equityCard.style.display = "none";
  if (_equityObjectUrl) {
    URL.revokeObjectURL(_equityObjectUrl);
    _equityObjectUrl = null;
  }
}

async function loadEquityImage(cacheKey) {
  if (!equityImg || !equityCard) return;
  if (cacheKey == null || cacheKey === "") {
    hideEquityCard();
    return;
  }
  try {
    const path = "/equity_image/" + String(cacheKey).replace(/\//g, "%2F");
    const resp = await fetch(path);
    if (!resp.ok) {
      hideEquityCard();
      return;
    }
    const blob = await resp.blob();
    if (_equityObjectUrl) {
      URL.revokeObjectURL(_equityObjectUrl);
      _equityObjectUrl = null;
    }
    _equityObjectUrl = URL.createObjectURL(blob);
    equityImg.src = _equityObjectUrl;
    equityCard.style.display = "block";
    equityImg.style.display = "block";
  } catch (_) {
    hideEquityCard();
  }
}

function scheduleFetchChartAfterPillChange() {
  if (_pillChartDebounceTimer != null) {
    clearTimeout(_pillChartDebounceTimer);
    _pillChartDebounceTimer = null;
  }
  if (_pillChartAbortController != null) {
    try {
      _pillChartAbortController.abort();
    } catch (_) {}
    _pillChartAbortController = null;
  }
  _pillChartDebounceTimer = setTimeout(() => {
    _pillChartDebounceTimer = null;
    const ac = new AbortController();
    _pillChartAbortController = ac;
    fetchChart(null, { signal: ac.signal, fromPillDebounce: true }).finally(() => {
      if (_pillChartAbortController === ac) _pillChartAbortController = null;
    });
  }, 300);
}

async function fetchChart(nav = null, options = {}) {
  const signal = options.signal;
  const fromPillDebounce = options.fromPillDebounce === true;
  if (state.loading && !fromPillDebounce) return;
  state.loading = true;
  showLoading();

  const body = buildBody();
  let url = "/chart";
  if (nav === "next") {
    url = "/next_window";
    body.current_start = state.currentStart;
    body.current_end = state.currentEnd;
  } else if (nav === "prev") {
    url = "/prev_window";
    body.current_start = state.currentStart;
    body.current_end = state.currentEnd;
  } else if (nav === "shift_left" || nav === "shift_right") {
    url = "/shift_window";
    body.direction = nav === "shift_left" ? "left" : "right";
    body.current_start = state.currentStart;
    body.current_end = state.currentEnd;
  }

  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: signal || undefined,
    });
    if (!resp.ok) {
      showError(`Server error ${resp.status}`);
      return;
    }
    const data = await resp.json();
    if (!data || typeof data !== "object") {
      showError("Invalid server response");
      return;
    }
    if (data.error) {
      showError(data.error);
      return;
    }
    applyChartData(data);
  } catch (err) {
    if (err.name === "AbortError") {
      hideLoading();
      return;
    }
    showError("Network error: " + err.message);
  } finally {
    state.loading = false;
  }
}

function applyChartData(data) {
  hideError();

  if (data.cache_key) {
    chartImg.src = "/chart_image/" + data.cache_key.replace(/\//g, "%2F");
    chartImg.style.display = "block";
    placeholder.style.display = "none";
  } else if (data.image_base64 && typeof data.image_base64 === "string") {
    chartImg.src = "data:image/png;base64," + data.image_base64;
    chartImg.style.display = "block";
    placeholder.style.display = "none";
  } else {
    chartImg.style.display = "none";
    placeholder.textContent = "Chart unavailable";
    placeholder.style.display = "flex";
  }

  if (data.equity_cache_key) {
    void loadEquityImage(data.equity_cache_key);
  } else {
    hideEquityCard();
  }

  state.candle_map = {};
  state._chartKey = data.cache_key || null;
  state._candleMapLoaded = false;

  const wi = data.window_info || {};
  windowLabel.textContent = `Window ${wi.current || 1} / ${wi.total || 1}`;

  if (data.current_start !== undefined && data.current_end !== undefined) {
    state.currentStart = data.current_start;
    state.currentEnd = data.current_end;
  }
  state.windowIndex = Math.max(0, (wi.current || 1) - 1);

  const s = data.stats || {};
  state.lastStats = s;

  const wr = s.win_rate != null ? (s.win_rate * 100).toFixed(1) + "%" : "—";
  const exp = s.expectancy != null ? (s.expectancy >= 0 ? "+" : "") + s.expectancy.toFixed(2) + "R" : "—";
  const avgPip = s.avg_pip_pnl != null ? String(s.avg_pip_pnl) : "—";

  document.getElementById("res-wr").textContent = wr;
  document.getElementById("res-exp").textContent = exp;
  document.getElementById("res-trades").textContent = s.total_signals ?? "—";
  document.getElementById("res-avg-pip").textContent = avgPip;

  hideLoading();
}

chartImg.addEventListener("click", e => {
  const rect = chartImg.getBoundingClientRect();
  const scaleX = 1600 / rect.width;
  const scaleY = 900 / rect.height;
  const px = (e.clientX - rect.left) * scaleX;
  const py = (rect.bottom - e.clientY) * scaleY;

  let bestKey = null;
  let bestDist = Infinity;
  for (const [ts, info] of Object.entries(state.candle_map)) {
    const dx = Math.abs(info.x - px);
    const dy = Math.abs((info.y_high + info.y_low) / 2 - py);
    const dist = dx * 2 + dy;
    if (dx < 40 && dist < bestDist) {
      bestDist = dist;
      bestKey = ts;
    }
  }

  if (!bestKey) {
    tooltip.style.display = "none";
    return;
  }

  const info = state.candle_map[bestKey];
  let label = bestKey.replace("T", " ").replace(/\.\d+.*/, "").replace("+00:00", "");
  tooltip.innerHTML = `<strong>${label}</strong><br>${info.annotation ?? ""}`;
  tooltip.style.display = "block";

  const wrapRect = document.getElementById("chart-wrapper").getBoundingClientRect();
  let tx = e.clientX - wrapRect.left + 10;
  let ty = e.clientY - wrapRect.top - 10;
  if (tx + 230 > wrapRect.width) tx = e.clientX - wrapRect.left - 230;
  if (ty + 60 > wrapRect.height) ty = e.clientY - wrapRect.top - 60;
  tooltip.style.left = tx + "px";
  tooltip.style.top = ty + "px";
});

document.getElementById("chart-wrapper").addEventListener("click", e => {
  if (e.target !== chartImg) tooltip.style.display = "none";
});

async function _ensureCandleMapLoaded() {
  if (state._candleMapLoaded || !state._chartKey) return;
  state._candleMapLoaded = true;
  try {
    const resp = await fetch("/candle_map/" + state._chartKey.replace(/\//g, "%2F"));
    if (resp.ok) state.candle_map = await resp.json();
  } catch (_) {}
}

chartImg.addEventListener("mousemove", _ensureCandleMapLoaded);
chartImg.addEventListener("touchstart", _ensureCandleMapLoaded, { passive: true });

function showLoading() {
  placeholder.style.display = "flex";
  placeholder.innerHTML = '<div class="spinner"></div><span>Loading chart…</span>';
  chartImg.style.opacity = "0.3";
}

function hideLoading() {
  placeholder.style.display = "none";
  chartImg.style.opacity = "1";
}

function showError(msg) {
  placeholder.style.display = "none";
  chartImg.style.opacity = "1";
  errorBanner.style.display = "block";
  errorBanner.textContent = "Error: " + msg;
  state.loading = false;
}

function hideError() {
  errorBanner.style.display = "none";
  hideLoading();
}

document.querySelectorAll(".main-tab").forEach(btn => {
  btn.addEventListener("click", () => setMainTab(btn.dataset.mainTab));
});

document.querySelectorAll(".tf-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.classList.contains("active")) return;
    document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.timeframe = btn.dataset.tf;
    state.windowIndex = 0;
    fetchChart();
  });
});

document.getElementById("instrument-select").addEventListener("change", e => {
  state.instrument = e.target.value;
  state.windowIndex = 0;
  fetchChart();
});

document.querySelectorAll(".size-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.classList.contains("active")) return;
    document.querySelectorAll(".size-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    state.windowSize = parseInt(btn.dataset.size, 10);
    state.windowIndex = 0;
    fetchChart();
  });
});

document.getElementById("btn-prev").addEventListener("click", () => {
  if (state.windowIndex <= 0) return;
  fetchChart("prev");
});
document.getElementById("btn-next").addEventListener("click", () => {
  fetchChart("next");
});
document.getElementById("btn-shift-left").addEventListener("click", () => {
  fetchChart("shift_left");
});
document.getElementById("btn-shift-right").addEventListener("click", () => {
  fetchChart("shift_right");
});

document.getElementById("vol-toggle").addEventListener("change", e => {
  state.showVolume = e.target.checked;
  fetchChart();
});

(function _initNotional() {
  const ni = document.getElementById("notional-input");
  let v = parseInt(ni.value, 10);
  if (!Number.isFinite(v)) v = 1000;
  v = Math.min(1000000, Math.max(100, v));
  ni.value = String(v);
  state.notional = v;
})();
document.getElementById("notional-input").addEventListener("change", e => {
  let v = parseInt(e.target.value, 10);
  if (!Number.isFinite(v)) v = 1000;
  v = Math.min(1000000, Math.max(100, v));
  e.target.value = String(v);
  state.notional = v;
  fetchChart();
});

initSignalTreePanel();
addRootNode();
setMainTab("regime");
fetchChart();

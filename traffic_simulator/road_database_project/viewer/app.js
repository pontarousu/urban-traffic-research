const DATASETS = {
  tokyo_core_small: {
    label: "Tokyo core small",
    basePath: "../output/prototype_tokyo_core_small"
  },
  tokyo_station: {
    label: "Tokyo station",
    basePath: "../output/prototype_tokyo_station"
  }
};

const MODE_CONFIG = {
  osm: {
    layers: ["osm_roads"],
    legend: [{ label: "OSM roads", color: "#7b8794" }]
  },
  geometry: {
    layers: ["geometry_edges"],
    legend: [{ label: "Geometry edges", color: "#2563eb" }]
  },
  topology: {
    layers: ["topology_edges", "topology_nodes"],
    legend: [
      { label: "Topology edges", color: "#111827" },
      { label: "Topology nodes", color: "#dc2626" }
    ]
  },
  overlay: {
    layers: ["geometry_edges", "topology_nodes"],
    legend: [
      { label: "Geometry edges", color: "#2563eb" },
      { label: "Topology nodes", color: "#dc2626" }
    ]
  },
  directed: {
    layers: ["directed_edges"],
    legend: [{ label: "Directed edges", color: "#0f766e" }]
  },
  intersections: {
    layers: ["topology_edges", "topology_nodes", "intersections"],
    legend: [
      { label: "Topology edges", color: "#cbd5e1" },
      { label: "Intersection", color: "#dc2626" },
      { label: "Dead end", color: "#2563eb" },
      { label: "Direction change", color: "#ca8a04" },
      { label: "Attribute boundary", color: "#7c3aed" }
    ]
  },
  direction_changes: {
    layers: ["topology_edges", "topology_nodes"],
    legend: [
      { label: "Topology edges", color: "#d1d5db" },
      { label: "Direction change", color: "#ca8a04" }
    ]
  },
  approaches: {
    layers: ["intersection_approaches", "intersections"],
    legend: [
      { label: "Incoming", color: "#2563eb" },
      { label: "Outgoing", color: "#16a34a" },
      { label: "Intersections", color: "#111827" }
    ]
  },
  restrictions: {
    layers: ["topology_edges", "turn_relations", "intersections"],
    legend: [
      { label: "Topology edges", color: "#d1d5db" },
      { label: "OSM restricted turns", color: "#e11d48" },
      { label: "Intersections", color: "#111827" }
    ]
  },
  analysis: {
    layers: ["analysis_segments"],
    legend: [
      { label: "motorway / trunk", color: "#b91c1c" },
      { label: "primary / secondary", color: "#ea580c" },
      { label: "tertiary", color: "#ca8a04" },
      { label: "local roads", color: "#4b5563" }
    ]
  },
  components: {
    layers: ["topology_edges", "excluded_topology_edges"],
    legend: [
      { label: "Canonical component", color: "#111827" },
      { label: "Excluded components", color: "#ef4444" }
    ]
  }
};

const canvas = document.querySelector("#map-canvas");
const context = canvas.getContext("2d");
const datasetSelect = document.querySelector("#dataset-select");
const modeGrid = document.querySelector("#mode-grid");
const summaryStats = document.querySelector("#summary-stats");
const legend = document.querySelector("#legend");
const fitViewButton = document.querySelector("#fit-view");
const statusText = document.querySelector("#status-text");
const showShortestInput = document.querySelector("#show-shortest");
const showLongestInput = document.querySelector("#show-longest");

const state = {
  datasetKey: datasetSelect.value,
  mode: "osm",
  cache: new Map(),
  summary: null,
  bounds: null,
  viewBounds: null,
  drag: null
};

initialize().catch((error) => {
  console.error(error);
  statusText.textContent = "初期化に失敗しました";
});

async function initialize() {
  resizeCanvas();
  window.addEventListener("resize", () => {
    resizeCanvas();
    draw();
  });
  datasetSelect.addEventListener("change", handleDatasetChange);
  modeGrid.addEventListener("click", handleModeClick);
  fitViewButton.addEventListener("click", fitToBounds);
  showShortestInput.addEventListener("change", draw);
  showLongestInput.addEventListener("change", draw);
  canvas.addEventListener("wheel", handleWheel, { passive: false });
  canvas.addEventListener("pointerdown", handlePointerDown);
  canvas.addEventListener("pointermove", handlePointerMove);
  canvas.addEventListener("pointerup", handlePointerUp);
  canvas.addEventListener("pointercancel", handlePointerUp);

  await loadDataset(state.datasetKey);
  await setMode(state.mode);
}

async function handleDatasetChange(event) {
  state.datasetKey = event.target.value;
  state.cache.clear();
  await loadDataset(state.datasetKey);
  await setMode(state.mode);
}

async function handleModeClick(event) {
  const button = event.target.closest("button[data-mode]");
  if (!button) {
    return;
  }
  await setMode(button.dataset.mode);
}

async function loadDataset(datasetKey) {
  const dataset = DATASETS[datasetKey];
  statusText.textContent = `${dataset.label} を読み込み中`;
  const response = await fetch(`${dataset.basePath}/summary.json`);
  state.summary = await response.json();
  state.bounds = null;
  state.viewBounds = null;
  renderSummary();
}

async function setMode(mode) {
  state.mode = mode;
  for (const button of modeGrid.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.mode === mode);
  }
  renderLegend();
  await Promise.all(MODE_CONFIG[mode].layers.map(loadLayer));
  fitToBounds();
}

async function loadLayer(layerName) {
  const cacheKey = `${state.datasetKey}:${layerName}`;
  if (state.cache.has(cacheKey)) {
    return state.cache.get(cacheKey);
  }
  const dataset = DATASETS[state.datasetKey];
  statusText.textContent = `${dataset.label} / ${layerName} を読み込み中`;
  const response = await fetch(`${dataset.basePath}/${layerName}.geojson`);
  const geojson = await response.json();
  state.cache.set(cacheKey, geojson);
  return geojson;
}

function getLayer(layerName) {
  return state.cache.get(`${state.datasetKey}:${layerName}`);
}

function fitToBounds() {
  state.bounds = computeVisibleBounds();
  state.viewBounds = state.bounds ? padBounds(state.bounds, 0.04) : null;
  draw();
}

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(rect.width * ratio);
  canvas.height = Math.round(rect.height * ratio);
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
}

function draw() {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  context.clearRect(0, 0, width, height);
  if (!state.viewBounds) {
    return;
  }

  drawGrid(width, height);
  let modeDetail = "";

  if (state.mode === "osm") {
    drawLineLayer(getLayer("osm_roads"), "#7b8794", 1.1);
  } else if (state.mode === "geometry") {
    drawLineLayer(getLayer("geometry_edges"), "#2563eb", 1.2);
  } else if (state.mode === "topology") {
    drawLineLayer(getLayer("topology_edges"), "#111827", 1.2);
    drawPointLayer(getLayer("topology_nodes"), "#dc2626", 2.3);
  } else if (state.mode === "overlay") {
    drawLineLayer(getLayer("geometry_edges"), "#2563eb", 1.1);
    drawPointLayer(getLayer("topology_nodes"), "#dc2626", 2.1);
  } else if (state.mode === "directed") {
    drawLineLayer(getLayer("directed_edges"), "#0f766e", 1.1, true);
  } else if (state.mode === "intersections") {
    drawLineLayer(getLayer("topology_edges"), "#cbd5e1", 0.9);
    drawTopologyNodesByType(getLayer("topology_nodes"));
    drawPointLayer(getLayer("intersections"), "#dc2626", 1.8);
  } else if (state.mode === "direction_changes") {
    drawLineLayer(getLayer("topology_edges"), "#d1d5db", 0.8);
    const count = drawDirectionChangeLayer(getLayer("topology_nodes"));
    modeDetail = `: ${count}`;
  } else if (state.mode === "approaches") {
    drawApproachLayer(getLayer("intersection_approaches"));
    drawPointLayer(getLayer("intersections"), "#111827", 1.4);
  } else if (state.mode === "restrictions") {
    drawLineLayer(getLayer("topology_edges"), "#d1d5db", 0.75);
    drawPointLayer(getLayer("intersections"), "#111827", 1.1);
    drawRestrictionLayer(getLayer("turn_relations"));
  } else if (state.mode === "analysis") {
    drawAnalysisLayer(getLayer("analysis_segments"));
  } else if (state.mode === "components") {
    drawLineLayer(getLayer("topology_edges"), "#111827", 1.2);
    drawLineLayer(getLayer("excluded_topology_edges"), "#ef4444", 1.4);
  }

  if (state.mode !== "direction_changes") {
    drawExtremeEdges();
  }
  statusText.textContent = `${DATASETS[state.datasetKey].label} / ${state.mode}${modeDetail}`;
}

function drawGrid(width, height) {
  context.strokeStyle = "#edf1f4";
  context.lineWidth = 1;
  for (let index = 1; index < 5; index += 1) {
    const x = width * index / 5;
    const y = height * index / 5;
    context.beginPath();
    context.moveTo(x, 0);
    context.lineTo(x, height);
    context.stroke();
    context.beginPath();
    context.moveTo(0, y);
    context.lineTo(width, y);
    context.stroke();
  }
}

function drawLineLayer(layer, color, lineWidth, withArrows = false) {
  if (!layer) {
    return;
  }
  context.strokeStyle = color;
  context.lineWidth = lineWidth;
  context.lineJoin = "round";
  context.lineCap = "round";
  for (const feature of layer.features) {
    const coordinates = feature.geometry.coordinates;
    drawLineString(coordinates);
    if (withArrows) {
      drawArrow(coordinates, color);
    }
  }
}

function drawAnalysisLayer(layer) {
  if (!layer) {
    return;
  }
  for (const feature of layer.features) {
    context.strokeStyle = analysisColor(feature.properties.road_type);
    context.lineWidth = 1.25;
    drawLineString(feature.geometry.coordinates);
  }
}

function drawApproachLayer(layer) {
  if (!layer) {
    return;
  }
  for (const feature of layer.features) {
    const isIncoming = feature.properties.approach_type === "incoming";
    const color = isIncoming ? "#2563eb" : "#16a34a";
    context.strokeStyle = color;
    context.lineWidth = 0.9;
    drawLineString(feature.geometry.coordinates);
    drawArrow(feature.geometry.coordinates, color);
  }
}

function drawRestrictionLayer(layer) {
  if (!layer) {
    return;
  }
  for (const feature of layer.features) {
    const [x, y] = project(feature.geometry.coordinates);
    context.fillStyle = "#e11d48";
    context.strokeStyle = "#ffffff";
    context.lineWidth = 1.2;
    context.beginPath();
    context.arc(x, y, 3.8, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  }
}

function drawPointLayer(layer, color, radius) {
  if (!layer) {
    return;
  }
  context.fillStyle = color;
  for (const feature of layer.features) {
    const [x, y] = project(feature.geometry.coordinates);
    context.beginPath();
    context.arc(x, y, radius, 0, Math.PI * 2);
    context.fill();
  }
}

function drawTopologyNodesByType(layer) {
  if (!layer) {
    return;
  }
  for (const feature of layer.features) {
    const nodeType = feature.properties.node_type;
    const [x, y] = project(feature.geometry.coordinates);
    context.fillStyle = nodeTypeColor(nodeType);
    context.beginPath();
    context.arc(x, y, nodeType === "intersection" ? 2.0 : 3.0, 0, Math.PI * 2);
    context.fill();
  }
}

function drawDirectionChangeLayer(layer) {
  if (!layer) {
    return 0;
  }
  let count = 0;
  for (const feature of layer.features) {
    if (feature.properties.node_type !== "direction_change") {
      continue;
    }
    count += 1;
    const [x, y] = project(feature.geometry.coordinates);
    context.fillStyle = "#ca8a04";
    context.strokeStyle = "#ffffff";
    context.lineWidth = 1.6;
    context.beginPath();
    context.arc(x, y, 4.8, 0, Math.PI * 2);
    context.fill();
    context.stroke();
  }
  return count;
}

function drawExtremeEdges() {
  const topologyLayer = getLayer("topology_edges");
  if (!topologyLayer || !state.summary) {
    return;
  }
  const featuresById = new Map(
    topologyLayer.features.map((feature) => [feature.properties.topology_edge_id, feature])
  );

  if (showShortestInput.checked) {
    const shortestId = state.summary.edge_length_meter.shortest_top10[0]?.topology_edge_id;
    const shortestFeature = featuresById.get(shortestId);
    if (shortestFeature) {
      context.strokeStyle = "#db2777";
      context.lineWidth = 3;
      drawLineString(shortestFeature.geometry.coordinates);
    }
  }

  if (showLongestInput.checked) {
    const longestId = state.summary.edge_length_meter.longest_top10[0]?.topology_edge_id;
    const longestFeature = featuresById.get(longestId);
    if (longestFeature) {
      context.strokeStyle = "#7c3aed";
      context.lineWidth = 3;
      drawLineString(longestFeature.geometry.coordinates);
    }
  }
}

function drawLineString(coordinates) {
  coordinates.forEach((coordinate, index) => {
    const [x, y] = project(coordinate);
    if (index === 0) {
      context.beginPath();
      context.moveTo(x, y);
    } else {
      context.lineTo(x, y);
    }
  });
  context.stroke();
}

function drawArrow(coordinates, color) {
  if (coordinates.length < 2) {
    return;
  }
  const middleIndex = Math.max(1, Math.floor(coordinates.length / 2));
  const start = project(coordinates[middleIndex - 1]);
  const end = project(coordinates[middleIndex]);
  const segmentLength = Math.hypot(end[0] - start[0], end[1] - start[1]);
  if (segmentLength < 18) {
    return;
  }
  const angle = Math.atan2(end[1] - start[1], end[0] - start[0]);
  const arrowX = (start[0] + end[0]) / 2;
  const arrowY = (start[1] + end[1]) / 2;
  const arrowSize = Math.min(6, Math.max(3, segmentLength * 0.18));
  context.fillStyle = color;
  context.beginPath();
  context.moveTo(arrowX, arrowY);
  context.lineTo(
    arrowX - arrowSize * Math.cos(angle - Math.PI / 6),
    arrowY - arrowSize * Math.sin(angle - Math.PI / 6)
  );
  context.lineTo(
    arrowX - arrowSize * Math.cos(angle + Math.PI / 6),
    arrowY - arrowSize * Math.sin(angle + Math.PI / 6)
  );
  context.closePath();
  context.fill();
}

function handleWheel(event) {
  if (!state.viewBounds) {
    return;
  }
  event.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const cursorX = event.clientX - rect.left;
  const cursorY = event.clientY - rect.top;
  const anchor = unproject([cursorX, cursorY]);
  const scale = event.deltaY < 0 ? 0.82 : 1.22;
  state.viewBounds = scaleBoundsAround(state.viewBounds, anchor, scale);
  draw();
}

function handlePointerDown(event) {
  if (!state.viewBounds) {
    return;
  }
  canvas.setPointerCapture(event.pointerId);
  canvas.classList.add("dragging");
  state.drag = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    startBounds: { ...state.viewBounds }
  };
}

function handlePointerMove(event) {
  if (!state.drag || event.pointerId !== state.drag.pointerId) {
    return;
  }
  const deltaX = event.clientX - state.drag.startX;
  const deltaY = event.clientY - state.drag.startY;
  state.viewBounds = panBounds(state.drag.startBounds, deltaX, deltaY);
  draw();
}

function handlePointerUp(event) {
  if (!state.drag || event.pointerId !== state.drag.pointerId) {
    return;
  }
  canvas.releasePointerCapture(event.pointerId);
  canvas.classList.remove("dragging");
  state.drag = null;
}

function computeVisibleBounds() {
  const layers = MODE_CONFIG[state.mode].layers
    .map(getLayer)
    .filter(Boolean);
  if (layers.length === 0) {
    return null;
  }
  const bounds = {
    minLon: Infinity,
    minLat: Infinity,
    maxLon: -Infinity,
    maxLat: -Infinity
  };
  for (const layer of layers) {
    for (const feature of layer.features) {
      const coordinates = flattenCoordinates(feature.geometry);
      for (const [lon, lat] of coordinates) {
        bounds.minLon = Math.min(bounds.minLon, lon);
        bounds.minLat = Math.min(bounds.minLat, lat);
        bounds.maxLon = Math.max(bounds.maxLon, lon);
        bounds.maxLat = Math.max(bounds.maxLat, lat);
      }
    }
  }
  return bounds;
}

function flattenCoordinates(geometry) {
  if (geometry.type === "Point") {
    return [geometry.coordinates];
  }
  return geometry.coordinates;
}

function padBounds(bounds, ratio) {
  const lonPadding = Math.max(1e-9, (bounds.maxLon - bounds.minLon) * ratio);
  const latPadding = Math.max(1e-9, (bounds.maxLat - bounds.minLat) * ratio);
  return {
    minLon: bounds.minLon - lonPadding,
    minLat: bounds.minLat - latPadding,
    maxLon: bounds.maxLon + lonPadding,
    maxLat: bounds.maxLat + latPadding
  };
}

function project([lon, lat]) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const lonRatio = (lon - state.viewBounds.minLon) / (state.viewBounds.maxLon - state.viewBounds.minLon);
  const latRatio = (lat - state.viewBounds.minLat) / (state.viewBounds.maxLat - state.viewBounds.minLat);
  return [
    lonRatio * width,
    height - latRatio * height
  ];
}

function unproject([x, y]) {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  const lonRatio = x / width;
  const latRatio = 1 - y / height;
  return [
    state.viewBounds.minLon + lonRatio * (state.viewBounds.maxLon - state.viewBounds.minLon),
    state.viewBounds.minLat + latRatio * (state.viewBounds.maxLat - state.viewBounds.minLat)
  ];
}

function scaleBoundsAround(bounds, [anchorLon, anchorLat], scale) {
  return {
    minLon: anchorLon + (bounds.minLon - anchorLon) * scale,
    minLat: anchorLat + (bounds.minLat - anchorLat) * scale,
    maxLon: anchorLon + (bounds.maxLon - anchorLon) * scale,
    maxLat: anchorLat + (bounds.maxLat - anchorLat) * scale
  };
}

function panBounds(bounds, deltaX, deltaY) {
  const lonPerPixel = (bounds.maxLon - bounds.minLon) / canvas.clientWidth;
  const latPerPixel = (bounds.maxLat - bounds.minLat) / canvas.clientHeight;
  const lonShift = -deltaX * lonPerPixel;
  const latShift = deltaY * latPerPixel;
  return {
    minLon: bounds.minLon + lonShift,
    minLat: bounds.minLat + latShift,
    maxLon: bounds.maxLon + lonShift,
    maxLat: bounds.maxLat + latShift
  };
}

function renderSummary() {
  const counts = state.summary.counts;
  const connectivity = state.summary.connectivity;
  const turnRestrictions = state.summary.turn_restrictions ?? {};
  const items = [
    ["OSM nodes", counts.raw_osm_node_count],
    ["Selected ways", counts.selected_osm_way_count],
    ["All topology edges", counts.all_topology_edge_count],
    ["Topology nodes", counts.topology_node_count],
    ["Intersections", counts.intersection_count],
    ["Topology edges", counts.topology_edge_count],
    ["Excluded edges", counts.excluded_topology_edge_count],
    ["Directed edges", counts.directed_edge_count],
    ["Approaches", counts.intersection_approach_count],
    ["Turn restrictions", counts.turn_relation_count],
    ["Applied restrictions", turnRestrictions.applied_restriction_relation_count ?? 0],
    ["Components", connectivity.component_count],
    ["Largest component", `${(connectivity.largest_component_edge_ratio * 100).toFixed(2)}%`]
  ];
  summaryStats.innerHTML = items
    .map(([label, value]) => `<dt>${label}</dt><dd>${formatValue(value)}</dd>`)
    .join("");
}

function renderLegend() {
  legend.innerHTML = MODE_CONFIG[state.mode].legend
    .map(
      (item) => `
        <li>
          <span class="swatch" style="background:${item.color}"></span>
          <span>${item.label}</span>
        </li>
      `
    )
    .join("");
}

function analysisColor(roadType) {
  if (["motorway", "motorway_link", "trunk", "trunk_link"].includes(roadType)) {
    return "#b91c1c";
  }
  if (["primary", "primary_link", "secondary", "secondary_link"].includes(roadType)) {
    return "#ea580c";
  }
  if (["tertiary", "tertiary_link"].includes(roadType)) {
    return "#ca8a04";
  }
  return "#4b5563";
}

function nodeTypeColor(nodeType) {
  if (nodeType === "intersection") {
    return "#dc2626";
  }
  if (nodeType === "dead_end") {
    return "#2563eb";
  }
  if (nodeType === "direction_change") {
    return "#ca8a04";
  }
  if (nodeType === "attribute_boundary") {
    return "#7c3aed";
  }
  return "#6b7280";
}

function formatValue(value) {
  return typeof value === "number" ? value.toLocaleString("ja-JP") : value;
}

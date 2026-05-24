const SAMPLE_CONFIGS = [
  {
    id: "tokyo-core-300obs-midflow-5min",
    label: "東京中心部 / 300観測点 / 5分拡張",
    renderUrl: "./data/current/tokyo_core_small_render_map.json",
    playbackUrl: "./data/benchmarks/tokyo_core_small_realdata_osm_300obs_midflow_5min_playback.json"
  },
  {
    id: "tokyo-core-300obs-allday",
    label: "東京中心部 / 300観測点 / 24時間",
    renderUrl: "./data/current/tokyo_core_small_render_map.json",
    playbackUrl: "./data/current/tokyo_core_small_realdata_osm_300obs_allday_playback.json"
  }
];

const roadsCanvas = document.querySelector("#roads-canvas");
const carsCanvas = document.querySelector("#cars-canvas");
const mapStage = document.querySelector("#map-stage");
const sampleSelect = document.querySelector("#sample-select");
const loadSampleButton = document.querySelector("#load-sample");
const playbackFileInput = document.querySelector("#playback-file");
const scenarioFileInput = document.querySelector("#scenario-file");
const playToggleButton = document.querySelector("#play-toggle");
const restartButton = document.querySelector("#restart-playback");
const speedSelect = document.querySelector("#speed-select");
const showObservationsInput = document.querySelector("#show-observations");
const timeline = document.querySelector("#timeline");
const scenarioStatus = document.querySelector("#scenario-status");
const scenarioTitle = document.querySelector("#scenario-title");
const scenarioDescription = document.querySelector("#scenario-description");
const summary = document.querySelector("#summary");
const timelineCurrent = document.querySelector("#timeline-current");
const timelineEnd = document.querySelector("#timeline-end");
const playbackBadge = document.querySelector("#playback-badge");
const frameStats = document.querySelector("#frame-stats");

let scenarioData = null;
let playbackData = null;
let preparedState = null;
let animationState = {
  isPlaying: false,
  playbackRate: Number(speedSelect.value),
  currentTimeMin: 0,
  lastAnimationMs: null
};

bootstrap();

function bootstrap() {
  populateSampleSelect();
  bindEvents();
  attemptInitialLoad();
}

function populateSampleSelect() {
  sampleSelect.innerHTML = SAMPLE_CONFIGS
    .map((sample) => `<option value="${sample.id}">${sample.label}</option>`)
    .join("");
}

function bindEvents() {
  loadSampleButton.addEventListener("click", async () => {
    const sample = SAMPLE_CONFIGS.find((item) => item.id === sampleSelect.value);
    if (!sample) {
      return;
    }

    await loadSample(sample);
  });

  playbackFileInput.addEventListener("change", async (event) => {
    const [file] = event.target.files ?? [];
    if (!file) {
      return;
    }

    try {
      const playback = JSON.parse(await file.text());
      playbackData = playback;
      setScenarioStatus(`playback JSON を読み込みました: ${file.name}`);
    } catch (error) {
      console.error(error);
      setScenarioStatus(`playback JSON の解析に失敗しました: ${error.message}`);
      return;
    }

    try {
      maybeApplyLoadedData();
    } catch (error) {
      console.error(error);
      setScenarioStatus(`playback JSON の適用に失敗しました: ${error.message}`);
    }
  });

  scenarioFileInput.addEventListener("change", async (event) => {
    const [file] = event.target.files ?? [];
    if (!file) {
      return;
    }

    try {
      scenarioData = JSON.parse(await file.text());
      setScenarioStatus(`scenario/render JSON を読み込みました: ${file.name}`);
    } catch (error) {
      console.error(error);
      setScenarioStatus(`scenario/render JSON の解析に失敗しました: ${error.message}`);
      return;
    }

    try {
      maybeApplyLoadedData();
    } catch (error) {
      console.error(error);
      setScenarioStatus(`scenario/render JSON の適用に失敗しました: ${error.message}`);
    }
  });

  playToggleButton.addEventListener("click", () => {
    if (!preparedState) {
      return;
    }

    animationState.isPlaying = !animationState.isPlaying;
    animationState.lastAnimationMs = null;
    syncPlaybackButton();
  });

  restartButton.addEventListener("click", () => {
    if (!preparedState) {
      return;
    }

    animationState.currentTimeMin = preparedState.playback.meta.start_time_min;
    animationState.lastAnimationMs = null;
    renderPlayback();
  });

  speedSelect.addEventListener("change", () => {
    animationState.playbackRate = Number(speedSelect.value);
  });

  showObservationsInput.addEventListener("change", () => {
    if (!preparedState) {
      return;
    }

    drawStaticMap();
    renderPlayback();
  });

  timeline.addEventListener("input", () => {
    if (!preparedState) {
      return;
    }

    animationState.currentTimeMin = Number(timeline.value);
    animationState.lastAnimationMs = null;
    renderPlayback();
  });

  window.addEventListener("resize", () => {
    if (!preparedState) {
      return;
    }

    resizeCanvases();
    drawStaticMap();
    renderPlayback();
  });

  requestAnimationFrame(tickPlayback);
}

async function attemptInitialLoad() {
  const sample = SAMPLE_CONFIGS[0];
  if (!sample) {
    setScenarioStatus("サンプル設定がありません。");
    return;
  }

  await loadSample(sample, false);
}

async function loadSample(sample, showFailure = true) {
  try {
    const [scenarioResponse, playbackResponse] = await Promise.all([
      fetch(sample.renderUrl),
      fetch(sample.playbackUrl)
    ]);

    if (!scenarioResponse.ok || !playbackResponse.ok) {
      throw new Error(`HTTP ${scenarioResponse.status}/${playbackResponse.status}`);
    }

    scenarioData = await scenarioResponse.json();
    playbackData = await playbackResponse.json();
    applyPreparedData(sample.label);
    setScenarioStatus(`${sample.label} を読み込みました。`);
  } catch (error) {
    console.error(error);
    if (showFailure) {
      setScenarioStatus("サンプルの読み込みに失敗しました。ローカル JSON を選択してください。");
    } else {
      setScenarioStatus("自動読込に失敗しました。サンプル読込またはローカル JSON を使ってください。");
    }
  }
}

function maybeApplyLoadedData() {
  if (!playbackData) {
    return;
  }

  if (!scenarioData) {
    setScenarioStatus(
      "playback は読み込めました。次に scenario/render JSON として data/current/tokyo_core_small_render_map.json を選択してください。"
    );
    return;
  }

  applyPreparedData("ローカル JSON");
}

function applyPreparedData(sourceLabel) {
  preparedState = prepareState(scenarioData, playbackData, sourceLabel);
  animationState.currentTimeMin = preparedState.playback.meta.start_time_min;
  animationState.isPlaying = false;
  animationState.lastAnimationMs = null;
  syncPlaybackButton();
  updateTextSummary();
  resizeCanvases();
  drawStaticMap();
  renderPlayback();
}

function prepareState(scenario, playback, sourceLabel) {
  if (!playback?.frames || !Array.isArray(playback.frames)) {
    throw new Error("playback JSON に frames 配列がありません。");
  }

  const frames = playback.frames.map((frame) => ({
    ...frame,
    carMap: null
  }));
  const viewBox = normalizeViewBox(
    playback.view_box ?? scenario.meta?.view_box ?? computeScenarioViewBox(scenario)
  );
  const roads = extractRoads(scenario);
  if (roads.length === 0) {
    throw new Error("scenario/render JSON に描画可能な roads がありません。");
  }
  const roadGeometryById = buildRoadGeometryById(roads);
  const wayLookup = normalizeWayLookup(playback.way_lookup);
  const roadGeometryByWayIndex = wayLookup.map((wayRecord) => {
    const baseGeometry = roadGeometryById.get(wayRecord.id);
    if (!baseGeometry) {
      return null;
    }
    return {
      ...baseGeometry,
      actualLengthMeter: wayRecord.actualLengthMeter
    };
  });

  return {
    sourceLabel,
    scenario,
    playback: {
      ...playback,
      frames
    },
    roads,
    observations: playback.observations ?? [],
    viewBox,
    camera: null,
    carRecordFormat: playback.meta?.car_record_format ?? "view_xy_v1",
    roadGeometryByWayIndex
  };
}

function resizeCanvases() {
  const rect = mapStage.getBoundingClientRect();
  const pixelRatio = window.devicePixelRatio || 1;
  const width = Math.max(320, Math.floor(rect.width));
  const height = Math.max(320, Math.floor(rect.height));

  roadsCanvas.width = Math.floor(width * pixelRatio);
  roadsCanvas.height = Math.floor(height * pixelRatio);
  carsCanvas.width = Math.floor(width * pixelRatio);
  carsCanvas.height = Math.floor(height * pixelRatio);
  roadsCanvas.style.width = `${width}px`;
  roadsCanvas.style.height = `${height}px`;
  carsCanvas.style.width = `${width}px`;
  carsCanvas.style.height = `${height}px`;

  preparedState.camera = buildCamera(preparedState.viewBox, width, height, pixelRatio);
}

function buildCamera(viewBox, widthCssPx, heightCssPx, pixelRatio) {
  const [minX, minY, viewWidth, viewHeight] = viewBox;
  const scale = Math.min(widthCssPx / viewWidth, heightCssPx / viewHeight);
  const offsetX = (widthCssPx - viewWidth * scale) / 2;
  const offsetY = (heightCssPx - viewHeight * scale) / 2;

  return {
    minX,
    minY,
    scale,
    offsetX,
    offsetY,
    widthCssPx,
    heightCssPx,
    pixelRatio
  };
}

function drawStaticMap() {
  const context = roadsCanvas.getContext("2d");
  const { camera, roads, observations } = preparedState;

  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, roadsCanvas.width, roadsCanvas.height);
  context.fillStyle = "#f8f8f6";
  context.fillRect(0, 0, roadsCanvas.width, roadsCanvas.height);
  context.scale(camera.pixelRatio, camera.pixelRatio);

  context.lineCap = "round";
  context.lineJoin = "round";

  roads.forEach((way) => {
    context.beginPath();
    way.shapePoints.forEach((point, index) => {
      const projected = projectPoint(point.view_x, point.view_y, camera);
      if (index === 0) {
        context.moveTo(projected.x, projected.y);
      } else {
        context.lineTo(projected.x, projected.y);
      }
    });
    context.strokeStyle = isStrongRoad(way.roadType) ? "#c6c6c4" : "#d4d4d2";
    context.lineWidth = isStrongRoad(way.roadType) ? 1.7 : 1.1;
    context.stroke();
  });

  if (showObservationsInput.checked) {
    observations.forEach((observation) => {
      const projected = projectPoint(observation.view_x, observation.view_y, camera);
      const radius = observation.total_volume >= 400 ? 3.2 : 2.2;
      context.beginPath();
      context.arc(projected.x, projected.y, radius, 0, Math.PI * 2);
      context.fillStyle = "rgba(193, 112, 52, 0.72)";
      context.fill();
    });
  }
}

function renderPlayback() {
  if (!preparedState) {
    return;
  }

  const context = carsCanvas.getContext("2d");
  const { camera } = preparedState;
  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, carsCanvas.width, carsCanvas.height);
  context.scale(camera.pixelRatio, camera.pixelRatio);

  const framePair = findFramePair(animationState.currentTimeMin);
  const renderCars = interpolateCars(
    framePair.currentFrame,
    framePair.nextFrame,
    framePair.mixRatio
  );

  renderCars.forEach((car) => {
    const projected = projectPoint(car.x, car.y, camera);
    context.beginPath();
    context.arc(projected.x, projected.y, 1.8, 0, Math.PI * 2);
    context.fillStyle = car.speedKmh >= 40 ? "#e05a47" : "#d8892b";
    context.fill();
  });

  timeline.value = String(animationState.currentTimeMin);
  timelineCurrent.textContent = formatTimeMin(animationState.currentTimeMin);
  timelineEnd.textContent = formatTimeMin(preparedState.playback.meta.end_time_min);
  playbackBadge.textContent = `${formatTimeMin(animationState.currentTimeMin)} / ${preparedState.sourceLabel}`;
  frameStats.textContent = `active cars: ${framePair.currentFrame.active_car_count.toLocaleString()} / max ${preparedState.playback.summary.max_active_cars.toLocaleString()}`;
}

function tickPlayback(timestampMs) {
  if (preparedState && animationState.isPlaying) {
    if (animationState.lastAnimationMs !== null) {
      const elapsedMs = timestampMs - animationState.lastAnimationMs;
      animationState.currentTimeMin += elapsedMs * animationState.playbackRate / 60000;
      if (animationState.currentTimeMin >= preparedState.playback.meta.end_time_min) {
        animationState.currentTimeMin = preparedState.playback.meta.end_time_min;
        animationState.isPlaying = false;
        syncPlaybackButton();
      }
      renderPlayback();
    }

    animationState.lastAnimationMs = timestampMs;
  } else {
    animationState.lastAnimationMs = timestampMs;
  }

  requestAnimationFrame(tickPlayback);
}

function findFramePair(timeMin) {
  const frames = preparedState.playback.frames;
  if (frames.length === 0) {
    return { currentFrame: { active_car_count: 0, cars: [], carMap: new Map() }, nextFrame: null, mixRatio: 0 };
  }

  if (timeMin <= frames[0].time_min) {
    ensureFrameCarMap(frames[0]);
    return { currentFrame: frames[0], nextFrame: frames[0], mixRatio: 0 };
  }

  const lastFrame = frames[frames.length - 1];
  if (timeMin >= lastFrame.time_min) {
    ensureFrameCarMap(lastFrame);
    return { currentFrame: lastFrame, nextFrame: lastFrame, mixRatio: 0 };
  }

  let low = 0;
  let high = frames.length - 1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (frames[mid].time_min <= timeMin) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }

  const currentFrame = frames[Math.max(0, low - 1)];
  const nextFrame = frames[Math.min(frames.length - 1, low)];
  ensureFrameCarMap(currentFrame);
  ensureFrameCarMap(nextFrame);

  const denominator = nextFrame.time_min - currentFrame.time_min;
  const mixRatio = denominator > 0 ? clamp((timeMin - currentFrame.time_min) / denominator, 0, 1) : 0;
  return { currentFrame, nextFrame, mixRatio };
}

function ensureFrameCarMap(frame) {
  if (frame.carMap) {
    return;
  }

  frame.carMap = new Map(frame.cars.map((car) => [car[0], car]));
}

function interpolateCars(currentFrame, nextFrame, mixRatio) {
  if (preparedState.carRecordFormat === "way_position_v2") {
    return interpolateCarsOnRoadGeometry(currentFrame, nextFrame, mixRatio);
  }

  if (!nextFrame || currentFrame === nextFrame) {
    return currentFrame.cars.map((car) => ({
      id: car[0],
      x: car[1],
      y: car[2],
      speedKmh: car[3]
    }));
  }

  return currentFrame.cars.map((car) => {
    const nextCar = nextFrame.carMap.get(car[0]);
    if (!nextCar) {
      return {
        id: car[0],
        x: car[1],
        y: car[2],
        speedKmh: car[3]
      };
    }

    return {
      id: car[0],
      x: car[1] + (nextCar[1] - car[1]) * mixRatio,
      y: car[2] + (nextCar[2] - car[2]) * mixRatio,
      speedKmh: car[3] + (nextCar[3] - car[3]) * mixRatio
    };
  });
}

function interpolateCarsOnRoadGeometry(currentFrame, nextFrame, mixRatio) {
  if (!nextFrame || currentFrame === nextFrame) {
    return currentFrame.cars
      .map((car) => buildRenderedCarFromWayRecord(car))
      .filter(Boolean);
  }

  return currentFrame.cars
    .map((car) => {
      const nextCar = nextFrame.carMap.get(car[0]);
      if (!nextCar) {
        return buildRenderedCarFromWayRecord(car);
      }

      if (car[1] !== nextCar[1]) {
        return mixRatio < 0.5
          ? buildRenderedCarFromWayRecord(car)
          : buildRenderedCarFromWayRecord(nextCar);
      }

      const wayGeometry = preparedState.roadGeometryByWayIndex[car[1]];
      if (!wayGeometry) {
        return null;
      }

      const interpolatedPositionMeter = car[2] + (nextCar[2] - car[2]) * mixRatio;
      const point = interpolatePointOnWayGeometry(wayGeometry, interpolatedPositionMeter);
      return {
        id: car[0],
        x: point.x,
        y: point.y,
        speedKmh: car[3] + (nextCar[3] - car[3]) * mixRatio
      };
    })
    .filter(Boolean);
}

function buildRenderedCarFromWayRecord(car) {
  const wayGeometry = preparedState.roadGeometryByWayIndex[car[1]];
  if (!wayGeometry) {
    return null;
  }

  const point = interpolatePointOnWayGeometry(wayGeometry, car[2]);
  return {
    id: car[0],
    x: point.x,
    y: point.y,
    speedKmh: car[3]
  };
}

function updateTextSummary() {
  const { scenario, playback, observations, sourceLabel } = preparedState;
  const summaryData = playback.summary;
  const matchingSummary = scenario.meta?.matching_summary ?? null;

  scenarioTitle.textContent = playback.meta.title;
  scenarioDescription.textContent = [
    `${sourceLabel}`,
    `${observations.length.toLocaleString()} 観測点`,
    `${summaryData.request_window_count.toLocaleString()} request`,
    `${formatDurationMin(playback.meta.end_time_min - playback.meta.start_time_min)}`,
    `fill_rate ${formatRate(summaryData.fill_rate)}`
  ].join(" / ");

  summary.innerHTML = `
    <div><strong>道路数:</strong> ${preparedState.roads.length.toLocaleString()}</div>
    <div><strong>車両総数:</strong> ${summaryData.cars_total.toLocaleString()}</div>
    <div><strong>最大同時走行:</strong> ${summaryData.max_active_cars.toLocaleString()}</div>
    <div><strong>目標通過台数:</strong> ${summaryData.total_target_count.toLocaleString()}</div>
    <div><strong>実通過台数:</strong> ${summaryData.total_assigned_count.toLocaleString()}</div>
    <div><strong>request fail:</strong> ${summaryData.total_failed_count.toLocaleString()}</div>
    <div><strong>観測点マッチ率:</strong> ${formatMatchingSummary(matchingSummary)}</div>
  `;

  timeline.min = String(playback.meta.start_time_min);
  timeline.max = String(playback.meta.end_time_min);
}

function formatMatchingSummary(matchingSummary) {
  if (!matchingSummary) {
    return "--";
  }

  const matched = matchingSummary.matched_observation_count ?? 0;
  const candidates = matchingSummary.candidate_observation_count ?? 0;
  return `${matched.toLocaleString()} / ${candidates.toLocaleString()}`;
}

function syncPlaybackButton() {
  playToggleButton.textContent = animationState.isPlaying ? "停止" : "再生";
}

function projectPoint(x, y, camera) {
  return {
    x: (x - camera.minX) * camera.scale + camera.offsetX,
    y: (y - camera.minY) * camera.scale + camera.offsetY
  };
}

function isStrongRoad(roadType) {
  return ["motorway", "trunk", "primary", "secondary"].includes(roadType);
}

function computeScenarioViewBox(scenario) {
  const normalized = normalizeViewBox(scenario.meta?.view_box);
  if (normalized) {
    return normalized;
  }

  const points = [];
  extractRoads(scenario).forEach((way) => {
    way.shapePoints.forEach((point) => points.push(point));
  });

  const minX = Math.min(...points.map((point) => point.view_x));
  const maxX = Math.max(...points.map((point) => point.view_x));
  const minY = Math.min(...points.map((point) => point.view_y));
  const maxY = Math.max(...points.map((point) => point.view_y));
  const width = maxX - minX;
  const height = maxY - minY;
  const padding = Math.max(width, height) * 0.03;
  return [minX - padding, minY - padding, width + padding * 2, height + padding * 2];
}

function normalizeViewBox(viewBox) {
  if (Array.isArray(viewBox) && viewBox.length === 4) {
    return viewBox;
  }

  if (
    viewBox &&
    Number.isFinite(viewBox.x_min) &&
    Number.isFinite(viewBox.y_min) &&
    Number.isFinite(viewBox.x_max) &&
    Number.isFinite(viewBox.y_max)
  ) {
    return [
      viewBox.x_min,
      viewBox.y_min,
      viewBox.x_max - viewBox.x_min,
      viewBox.y_max - viewBox.y_min
    ];
  }

  return null;
}

function extractRoads(data) {
  if (Array.isArray(data.roads)) {
    return data.roads
      .map((way) => ({
        id: way.id,
        roadType: way.road_type,
        laneCount: way.lane_count,
        shapePoints: (way.shape_points ?? []).map((point) => ({
          view_x: point.view_x,
          view_y: point.view_y
        }))
      }))
      .filter((way) => way.shapePoints.length >= 2);
  }

  return (data.graph?.ways ?? [])
    .map((way) => ({
      id: way.id,
      roadType: way.road_type,
      laneCount: way.lane_count,
      shapePoints: (way.shape_points ?? []).map((point) => ({
        view_x: point.view_x,
        view_y: point.view_y
      }))
    }))
    .filter((way) => way.shapePoints.length >= 2);
}

function buildRoadGeometryById(roads) {
  const roadGeometryById = new Map();

  roads.forEach((road) => {
    const segments = [];
    let cumulativeMeter = 0;

    for (let index = 0; index < road.shapePoints.length - 1; index += 1) {
      const start = road.shapePoints[index];
      const end = road.shapePoints[index + 1];
      const segmentLength = Math.hypot(end.view_x - start.view_x, end.view_y - start.view_y);
      if (segmentLength <= 1e-9) {
        continue;
      }

      const startMeter = cumulativeMeter;
      cumulativeMeter += segmentLength;
      segments.push({
        startX: start.view_x,
        startY: start.view_y,
        endX: end.view_x,
        endY: end.view_y,
        startMeter,
        endMeter: cumulativeMeter,
        lengthMeter: segmentLength
      });
    }

    if (segments.length === 0) {
      return;
    }

    roadGeometryById.set(road.id, {
      displayLengthMeter: cumulativeMeter,
      actualLengthMeter: cumulativeMeter,
      segments
    });
  });

  return roadGeometryById;
}

function normalizeWayLookup(wayLookup) {
  if (!Array.isArray(wayLookup)) {
    return [];
  }

  return wayLookup
    .map((wayRecord) => {
      if (!Array.isArray(wayRecord) || wayRecord.length < 2) {
        return null;
      }

      return {
        id: String(wayRecord[0]),
        actualLengthMeter: Number.isFinite(wayRecord[1]) ? wayRecord[1] : 0
      };
    })
    .filter(Boolean);
}

function interpolatePointOnWayGeometry(wayGeometry, positionMeterOnWay) {
  const targetRatio =
    wayGeometry.actualLengthMeter > 0
      ? clamp(positionMeterOnWay / wayGeometry.actualLengthMeter, 0, 1)
      : 0;
  const targetDisplayMeter = targetRatio * wayGeometry.displayLengthMeter;

  for (const segment of wayGeometry.segments) {
    if (targetDisplayMeter <= segment.endMeter) {
      const localRatio =
        segment.lengthMeter > 0
          ? (targetDisplayMeter - segment.startMeter) / segment.lengthMeter
          : 0;
      return {
        x: segment.startX + (segment.endX - segment.startX) * localRatio,
        y: segment.startY + (segment.endY - segment.startY) * localRatio
      };
    }
  }

  const lastSegment = wayGeometry.segments[wayGeometry.segments.length - 1];
  return {
    x: lastSegment.endX,
    y: lastSegment.endY
  };
}

function formatTimeMin(timeMin) {
  const totalSeconds = Math.max(0, Math.round(timeMin * 60));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatDurationMin(durationMin) {
  if (!Number.isFinite(durationMin) || durationMin <= 0) {
    return "--";
  }

  const roundedMinutes = Math.round(durationMin);
  const hours = Math.floor(roundedMinutes / 60);
  const minutes = roundedMinutes % 60;
  if (hours === 0) {
    return `${minutes}分`;
  }
  if (minutes === 0) {
    return `${hours}時間`;
  }
  return `${hours}時間${minutes}分`;
}

function formatRate(value) {
  if (!Number.isFinite(value)) {
    return "--";
  }

  return `${(value * 100).toFixed(2)}%`;
}

function clamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

function setScenarioStatus(message) {
  scenarioStatus.textContent = message;
}

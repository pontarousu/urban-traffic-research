/**
 * 交通シミュレーションの基盤。
 *
 * 現時点では以下を担当する。
 * - RequestWindow の生成
 * - Way の混雑状態と速度の更新
 * - request score の計算
 * - 最短時間経路の計算
 * - 車の予約、生成、通過判定、消滅
 * - 1 ステップ更新
 */

/**
 * @typedef {Object} NodeRecord
 * @property {string} id
 * @property {number} lat
 * @property {number} lon
 * @property {number} view_x
 * @property {number} view_y
 * @property {string[]} connected_way_ids
 * @property {{from_way_id: string, to_way_id: string, allowed: boolean}[]} turn_permissions
 */

/**
 * @typedef {Object} ShapePoint
 * @property {number} lat
 * @property {number} lon
 * @property {number} view_x
 * @property {number} view_y
 */

/**
 * @typedef {Object} WayRecord
 * @property {string} id
 * @property {string | undefined} osm_way_id
 * @property {string} from_node_id
 * @property {string} to_node_id
 * @property {ShapePoint[]} shape_points
 * @property {string | undefined} road_type
 * @property {number} lane_count
 * @property {number} length_meter
 * @property {number | undefined} speed_limit_kmh
 * @property {number} storage_capacity_cars
 */

/**
 * @typedef {Object} TrafficVolumeRecord
 * @property {number} time_min
 * @property {number} volume_5min
 */

/**
 * @typedef {Object} ObservationPointRecord
 * @property {string} id
 * @property {number} lat
 * @property {number} lon
 * @property {number} view_x
 * @property {number} view_y
 * @property {string} matched_way_id
 * @property {number} matched_position_ratio
 * @property {TrafficVolumeRecord[]} traffic_volume
 */

/**
 * @typedef {Object} SimulationConfig
 * @property {number} random_seed
 * @property {number} time_step_sec
 * @property {number} request_horizon_min
 * @property {number} request_window_min
 * @property {boolean} u_turn_allowed
 * @property {boolean | undefined} enable_standby
 * @property {number | undefined} standby_horizon_min
 * @property {number | undefined} standby_total_time_limit_min
 * @property {number | undefined} standby_score_threshold
 * @property {number | undefined} unassigned_fail_limit
 * @property {{type: string, travel_decay_a: number, slack_decay_b: number}} score_model
 * @property {{enabled?: boolean, mode?: "summary" | "sample" | "full", sample_size?: number}} logging
 */

/**
 * @typedef {Object} ScenarioInput
 * @property {{scenario_id?: string, scenario_name?: string, start_time_min?: number}} meta
 * @property {{nodes: NodeRecord[], ways: WayRecord[]}} graph
 * @property {ObservationPointRecord[]} observation_points
 * @property {SimulationConfig} simulation_config
 */

/**
 * @typedef {Object} RequestWindow
 * @property {string} id
 * @property {string} observation_point_id
 * @property {string} matched_way_id
 * @property {number} time_min
 * @property {number} window_start_min
 * @property {number} window_end_min
 * @property {number} target_count
 * @property {number} assigned_count
 * @property {number} reserved_count
 * @property {number} failed_count
 */

/**
 * @typedef {Object} CarState
 * @property {string} id
 * @property {number} birth_time_min
 * @property {string} current_way_id
 * @property {number} position_meter_on_way
 * @property {number} current_speed_mps
 * @property {string | null} reserved_request_window_id
 * @property {"assigned" | "unassigned"} assignment_state
 * @property {string | null} soft_target_request_window_id
 * @property {number} unassigned_elapsed_min
 * @property {number} reservation_fail_count
 * @property {string[]} route_way_ids
 * @property {number} route_index
 * @property {"active" | "retired"} status
 */

/**
 * @typedef {Object} WayRuntimeState
 * @property {string} way_id
 * @property {number} current_car_count
 * @property {number} occupancy_ratio
 * @property {number} free_speed_kmh
 * @property {number} current_speed_kmh
 * @property {number} current_speed_mps
 * @property {number} dynamic_flow_rate_cars_per_min
 */

/**
 * @typedef {Object} LogEvent
 * @property {string} event_type
 * @property {number} time_min
 * @property {string | null} car_id
 * @property {string | null} way_id
 * @property {number | null} position_meter_on_way
 * @property {string | null} node_id
 * @property {string | null} request_window_id
 * @property {number | null} value
 */

/**
 * @typedef {Object} SimulationIndexes
 * @property {Map<string, NodeRecord>} nodes_by_id
 * @property {Map<string, WayRecord>} ways_by_id
 * @property {Map<string, ObservationPointRecord>} observations_by_id
 * @property {Map<string, RequestWindow>} requests_by_id
 * @property {Map<string, RequestWindow[]>} requests_by_observation_id
 * @property {Map<string, ObservationPointRecord[]>} observations_by_way_id
 * @property {Map<string, string[]>} outgoing_way_ids_by_node
 * @property {Map<string, string[]>} incoming_way_ids_by_node
 * @property {Map<string, {x_meter: number, y_meter: number}>} node_meter_positions_by_id
 * @property {Map<string, {x_meter: number, y_meter: number}>} observation_meter_positions_by_id
 * @property {Map<string, string[]>} observation_ids_by_grid_cell
 * @property {Map<string, string[]>} node_ids_by_grid_cell
 * @property {number} observation_grid_cell_size_meter
 */

/**
 * @typedef {Object} SimulationRuntime
 * @property {number} now_min
 * @property {CarState[]} cars
 * @property {CarState[]} active_cars
 * @property {RequestWindow[]} request_windows
 * @property {Map<string, WayRuntimeState>} way_states 車が存在するWayだけの状態
 * @property {SimulationIndexes} indexes
 * @property {LogEvent[]} event_logs
 * @property {Map<string, number>} event_counters
 * @property {boolean} logging_enabled
 * @property {"summary" | "sample" | "full"} logging_mode
 * @property {number} logging_sample_size
 * @property {number} random_seed
 * @property {number} next_car_sequence
 * @property {number} candidate_request_start_index
 * @property {number} candidate_request_end_index
 * @property {RequestWindow[]} candidate_request_windows
 * @property {Map<string, RequestWindow[]>} candidate_requests_by_observation_id
 * @property {Map<string, RequestWindow[]>} priority_request_by_observation_id
 * @property {number} max_candidate_speed_kmh
 * @property {number} max_request_target_count
 * @property {Map<string, string[]>} nearby_observation_ids_cache_by_node
 * @property {Map<string, number>} cell_need_by_grid_cell
 * @property {Map<string, number>} car_count_by_grid_cell
 * @property {Map<string, number>} spawn_credit_by_grid_cell
 * @property {Map<string, {travel_time_min: number, route_way_ids: string[]}>} route_plan_cache
 * @property {Map<string, ShortestPathTree>} shortest_path_trees_by_target_way_id
 */

/**
 * @typedef {Object} ShortestPathTree
 * @property {string} target_way_id
 * @property {string} target_from_node_id
 * @property {Map<string, number>} distance_min_by_node
 * @property {Map<string, string>} next_way_id_by_node
 */

const LARGE_ROAD_TYPES = new Set(["trunk", "primary", "secondary"]);
const EPSILON_METER = 1e-6;
const PRIORITY_REQUEST_LIMIT = 3;
const EPSILON_TIME_MIN = 1e-7;
const EPSILON_SCORE = 1e-12;
const OBSERVATION_GRID_CELL_SIZE_METER = 1000;
const DEFAULT_UNASSIGNED_HORIZON_MIN = 25;
const DEFAULT_GRID_CAR_WEIGHT = 1;
const ARTERIAL_BONUS_SCORE = 0.35;
const SEMI_ARTERIAL_BONUS_SCORE = 0.15;

/**
 * RequestWindow の一覧を作る。
 *
 * @param {ObservationPointRecord[]} observationPoints
 * @param {number} requestWindowMin
 * @returns {RequestWindow[]}
 */
export function buildRequestWindows(observationPoints, requestWindowMin = 5) {
  const requestWindows = [];

  observationPoints.forEach((observationPoint) => {
    observationPoint.traffic_volume.forEach((record, index) => {
      requestWindows.push({
        id: `${observationPoint.id}__${record.time_min}__${index}`,
        observation_point_id: observationPoint.id,
        matched_way_id: observationPoint.matched_way_id,
        time_min: record.time_min,
        window_start_min: record.time_min - requestWindowMin,
        window_end_min: record.time_min,
        target_count: record.volume_5min,
        assigned_count: 0,
        reserved_count: 0,
        failed_count: 0
      });
    });
  });

  requestWindows.sort((left, right) => left.time_min - right.time_min || left.id.localeCompare(right.id));
  return requestWindows;
}

/**
 * ある時刻における累積目標台数を返す。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} nowMin
 * @returns {number}
 */
export function computeTargetCumulative(requestWindow, nowMin) {
  const windowLength = requestWindow.window_end_min - requestWindow.window_start_min;
  if (windowLength <= 0) {
    return requestWindow.target_count;
  }

  const elapsedRatio = clamp(
    (nowMin - requestWindow.window_start_min) / windowLength,
    0,
    1
  );

  return requestWindow.target_count * elapsedRatio;
}

/**
 * ある時刻における不足台数を返す。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} nowMin
 * @returns {number}
 */
export function computeEffectiveDeficit(requestWindow, nowMin) {
  const targetCumulative = computeTargetCumulative(requestWindow, nowMin);
  return Math.max(
    0,
    targetCumulative - requestWindow.assigned_count - requestWindow.reserved_count
  );
}

/**
 * 不足率を 0〜1 で返す。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} nowMin
 * @returns {number}
 */
export function computeDeficitRatio(requestWindow, nowMin) {
  if (requestWindow.target_count <= 0) {
    return 0;
  }

  return clamp(
    computeEffectiveDeficit(requestWindow, nowMin) / requestWindow.target_count,
    0,
    1
  );
}

/**
 * request 窓のスロット間隔を分で返す。
 *
 * @param {RequestWindow} requestWindow
 * @returns {number}
 */
export function computeRequestSlotIntervalMin(requestWindow) {
  if (requestWindow.target_count <= 0) {
    return Number.POSITIVE_INFINITY;
  }

  const windowLength = requestWindow.window_end_min - requestWindow.window_start_min;
  if (windowLength <= 0) {
    return Number.POSITIVE_INFINITY;
  }

  return windowLength / requestWindow.target_count;
}

/**
 * 指定時刻までに本来埋まっていてほしい整数台数を返す。
 *
 * 各台は 5 分窓内に等間隔に置かれたスロットとして扱う。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} timeMin
 * @returns {number}
 */
export function computeDueCountAtTime(requestWindow, timeMin) {
  if (requestWindow.target_count <= 0) {
    return 0;
  }

  const slotIntervalMin = computeRequestSlotIntervalMin(requestWindow);
  if (!Number.isFinite(slotIntervalMin) || slotIntervalMin <= 0) {
    return requestWindow.target_count;
  }

  const rawCount =
    (timeMin - requestWindow.window_start_min) / slotIntervalMin + 0.5;

  return clamp(
    Math.floor(rawCount),
    0,
    requestWindow.target_count
  );
}

/**
 * 指定到達時刻までに追加で必要な予約台数を返す。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} arrivalTimeMin
 * @returns {number}
 */
export function computeNeededReservationCountAtArrival(requestWindow, arrivalTimeMin) {
  const dueCount = computeDueCountAtTime(requestWindow, arrivalTimeMin);
  return Math.max(
    0,
    dueCount - requestWindow.assigned_count - requestWindow.reserved_count
  );
}

/**
 * 同一 observation 内で、この request が到達時点の優先窓候補か返す。
 *
 * 近い時間窓を独立に埋めすぎないよう、同じ observation では
 * 最も早い未充足窓から最大3件だけを予約・生成対象にする。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} arrivalTimeMin
 * @param {SimulationRuntime} runtime
 * @returns {boolean}
 */
export function isPriorityRequestForObservation(requestWindow, arrivalTimeMin, runtime) {
  const priorityRequests =
    runtime.priority_request_by_observation_id.get(requestWindow.observation_point_id) ?? [];
  const matchedPriorityRequest = priorityRequests.find(
    (priorityRequest) => priorityRequest.id === requestWindow.id
  ) ?? null;

  if (!matchedPriorityRequest) {
    return false;
  }

  return (
    canRequestAcceptArrival(matchedPriorityRequest, arrivalTimeMin) &&
    computeNeededReservationCountAtArrival(matchedPriorityRequest, arrivalTimeMin) >= 1
  );
}

/**
 * ある observation の優先 request 群を更新する。
 *
 * 優先 request は「現在時刻で有効かつ未充足な最も早い窓」から最大3件とする。
 *
 * @param {string} observationId
 * @param {SimulationRuntime} runtime
 */
function refreshPriorityRequestForObservation(observationId, runtime) {
  const requestWindows =
    runtime.candidate_requests_by_observation_id.get(observationId) ??
    runtime.indexes.requests_by_observation_id.get(observationId) ??
    [];

  const priorityRequests = requestWindows
    .filter((requestWindow) => (
      requestWindow.window_end_min >= runtime.now_min - EPSILON_TIME_MIN &&
      requestWindow.assigned_count + requestWindow.reserved_count < requestWindow.target_count
    ))
    .slice(0, PRIORITY_REQUEST_LIMIT);

  runtime.priority_request_by_observation_id.set(observationId, priorityRequests);
}

/**
 * 全 observation の優先 request 一覧を再構築する。
 *
 * @param {SimulationRuntime} runtime
 */
function rebuildPriorityRequestCache(runtime) {
  const priorityRequestByObservationId = new Map();

  runtime.candidate_requests_by_observation_id.forEach((requestWindows, observationId) => {
    const priorityRequests = requestWindows
      .filter((requestWindow) => (
        requestWindow.window_end_min >= runtime.now_min - EPSILON_TIME_MIN &&
        requestWindow.assigned_count + requestWindow.reserved_count < requestWindow.target_count
      ))
      .slice(0, PRIORITY_REQUEST_LIMIT);

    priorityRequestByObservationId.set(observationId, priorityRequests);
  });

  runtime.priority_request_by_observation_id = priorityRequestByObservationId;
}

/**
 * 優先 request を順に処理する。
 *
 * @param {SimulationRuntime} runtime
 * @param {(requestWindow: RequestWindow) => void} callback
 */
function forEachPriorityRequest(runtime, callback) {
  runtime.priority_request_by_observation_id.forEach((requestWindows) => {
    requestWindows.forEach((requestWindow) => {
      callback(requestWindow);
    });
  });
}

/**
 * 緯度経度を局所平面メートル座標へ変換する。
 *
 * @param {number} lat
 * @param {number} lon
 * @param {number} anchorLat
 * @param {number} anchorLon
 * @returns {{x_meter: number, y_meter: number}}
 */
function projectLonLatToLocalMeter(lat, lon, anchorLat, anchorLon) {
  const earthRadiusMeter = 6371000;
  const toRadian = Math.PI / 180;
  const meanLatRad = ((lat + anchorLat) / 2) * toRadian;

  return {
    x_meter: (lon - anchorLon) * toRadian * earthRadiusMeter * Math.cos(meanLatRad),
    y_meter: (lat - anchorLat) * toRadian * earthRadiusMeter
  };
}

/**
 * グリッドセルのキーを返す。
 *
 * @param {number} gridX
 * @param {number} gridY
 * @returns {string}
 */
function buildGridCellKey(gridX, gridY) {
  return `${gridX},${gridY}`;
}

/**
 * Way の自由速度を決める。
 *
 * @param {WayRecord} way
 * @returns {number}
 */
export function resolveFreeSpeedKmh(way) {
  if (Number.isFinite(way.speed_limit_kmh) && way.speed_limit_kmh > 0) {
    return way.speed_limit_kmh;
  }

  if (LARGE_ROAD_TYPES.has(way.road_type ?? "")) {
    return 60;
  }

  return 30;
}

/**
 * 簡略 BPR により現在速度を計算する。
 *
 * @param {number} freeSpeedKmh
 * @param {number} currentCarCount
 * @param {number} storageCapacityCars
 * @param {number} minSpeedKmh
 * @param {number} alpha
 * @param {number} beta
 * @returns {{occupancy_ratio: number, current_speed_kmh: number, current_speed_mps: number}}
 */
export function computeWaySpeedState(
  freeSpeedKmh,
  currentCarCount,
  storageCapacityCars,
  minSpeedKmh = 3,
  alpha = 2.0,
  beta = 4.0
) {
  const safeCapacity = Math.max(1, storageCapacityCars);
  const occupancyRatio = Math.max(0, currentCarCount / safeCapacity);
  const currentSpeedKmh = Math.max(
    minSpeedKmh,
    freeSpeedKmh / (1 + alpha * occupancyRatio ** beta)
  );

  return {
    occupancy_ratio: occupancyRatio,
    current_speed_kmh: currentSpeedKmh,
    current_speed_mps: currentSpeedKmh * 1000 / 3600
  };
}

/**
 * lane 数と現在速度から処理率を求める。
 *
 * @param {number} laneCount
 * @param {number} currentSpeedKmh
 * @returns {number}
 */
export function computeDynamicFlowRateCarsPerMin(laneCount, currentSpeedKmh) {
  const speedMetersPerMin = currentSpeedKmh * 1000 / 60;
  return Math.max(0, laneCount * speedMetersPerMin / 4);
}

/**
 * 車が存在する Way の実行時状態を更新する。
 *
 * @param {Map<string, WayRecord>} waysById
 * @param {CarState[]} cars
 * @returns {Map<string, WayRuntimeState>}
 */
export function updateWayRuntimeStates(waysById, cars) {
  const activeCarCountByWayId = new Map();
  cars.forEach((car) => {
    if (car.status !== "active") {
      return;
    }

    activeCarCountByWayId.set(
      car.current_way_id,
      (activeCarCountByWayId.get(car.current_way_id) ?? 0) + 1
    );
  });

  const wayStates = new Map();

  activeCarCountByWayId.forEach((currentCarCount, wayId) => {
    const way = waysById.get(wayId);
    if (!way) {
      return;
    }

    wayStates.set(way.id, buildWayRuntimeState(way, currentCarCount));
  });

  return wayStates;
}

/**
 * インデックスを作る。
 *
 * @param {ScenarioInput} scenario
 * @param {RequestWindow[]} requestWindows
 * @returns {SimulationIndexes}
 */
export function buildSimulationIndexes(scenario, requestWindows) {
  const nodesById = new Map();
  const waysById = new Map();
  const observationsById = new Map();
  const requestsById = new Map();
  const requestsByObservationId = new Map();
  const observationsByWayId = new Map();
  const outgoingWayIdsByNode = new Map();
  const incomingWayIdsByNode = new Map();
  const nodeMeterPositionsById = new Map();
  const observationMeterPositionsById = new Map();
  const observationIdsByGridCell = new Map();
  const nodeIdsByGridCell = new Map();

  const allLatitudes = [];
  const allLongitudes = [];
  scenario.graph.nodes.forEach((node) => {
    if (Number.isFinite(node.lat) && Number.isFinite(node.lon)) {
      allLatitudes.push(node.lat);
      allLongitudes.push(node.lon);
    }
  });
  scenario.observation_points.forEach((observation) => {
    if (Number.isFinite(observation.lat) && Number.isFinite(observation.lon)) {
      allLatitudes.push(observation.lat);
      allLongitudes.push(observation.lon);
    }
  });
  const anchorLat = allLatitudes.length > 0
    ? (Math.min(...allLatitudes) + Math.max(...allLatitudes)) / 2
    : 0;
  const anchorLon = allLongitudes.length > 0
    ? (Math.min(...allLongitudes) + Math.max(...allLongitudes)) / 2
    : 0;

  scenario.graph.nodes.forEach((node) => {
    nodesById.set(node.id, node);
    outgoingWayIdsByNode.set(node.id, []);
    incomingWayIdsByNode.set(node.id, []);
    const meterPosition = projectLonLatToLocalMeter(node.lat, node.lon, anchorLat, anchorLon);
    nodeMeterPositionsById.set(node.id, meterPosition);
    const gridX = Math.floor(meterPosition.x_meter / OBSERVATION_GRID_CELL_SIZE_METER);
    const gridY = Math.floor(meterPosition.y_meter / OBSERVATION_GRID_CELL_SIZE_METER);
    const gridCellKey = buildGridCellKey(gridX, gridY);
    if (!nodeIdsByGridCell.has(gridCellKey)) {
      nodeIdsByGridCell.set(gridCellKey, []);
    }
    nodeIdsByGridCell.get(gridCellKey).push(node.id);
  });

  scenario.graph.ways.forEach((way) => {
    waysById.set(way.id, way);
    if (!outgoingWayIdsByNode.has(way.from_node_id)) {
      outgoingWayIdsByNode.set(way.from_node_id, []);
    }
    if (!incomingWayIdsByNode.has(way.to_node_id)) {
      incomingWayIdsByNode.set(way.to_node_id, []);
    }
    outgoingWayIdsByNode.get(way.from_node_id).push(way.id);
    incomingWayIdsByNode.get(way.to_node_id).push(way.id);
  });

  scenario.observation_points.forEach((observation) => {
    observationsById.set(observation.id, observation);
    if (!observationsByWayId.has(observation.matched_way_id)) {
      observationsByWayId.set(observation.matched_way_id, []);
    }
    observationsByWayId.get(observation.matched_way_id).push(observation);

    const meterPosition = projectLonLatToLocalMeter(
      observation.lat,
      observation.lon,
      anchorLat,
      anchorLon
    );
    observationMeterPositionsById.set(observation.id, meterPosition);

    const gridX = Math.floor(meterPosition.x_meter / OBSERVATION_GRID_CELL_SIZE_METER);
    const gridY = Math.floor(meterPosition.y_meter / OBSERVATION_GRID_CELL_SIZE_METER);
    const gridCellKey = buildGridCellKey(gridX, gridY);
    if (!observationIdsByGridCell.has(gridCellKey)) {
      observationIdsByGridCell.set(gridCellKey, []);
    }
    observationIdsByGridCell.get(gridCellKey).push(observation.id);
  });

  observationsByWayId.forEach((observations) => {
    observations.sort((left, right) => left.matched_position_ratio - right.matched_position_ratio);
  });

  requestWindows.forEach((requestWindow) => {
    requestsById.set(requestWindow.id, requestWindow);
    if (!requestsByObservationId.has(requestWindow.observation_point_id)) {
      requestsByObservationId.set(requestWindow.observation_point_id, []);
    }
    requestsByObservationId.get(requestWindow.observation_point_id).push(requestWindow);
  });

  requestsByObservationId.forEach((requests) => {
    requests.sort((left, right) => left.time_min - right.time_min || left.id.localeCompare(right.id));
  });

  return {
    nodes_by_id: nodesById,
    ways_by_id: waysById,
    observations_by_id: observationsById,
    requests_by_id: requestsById,
    requests_by_observation_id: requestsByObservationId,
    observations_by_way_id: observationsByWayId,
    outgoing_way_ids_by_node: outgoingWayIdsByNode,
    incoming_way_ids_by_node: incomingWayIdsByNode,
    node_meter_positions_by_id: nodeMeterPositionsById,
    observation_meter_positions_by_id: observationMeterPositionsById,
    observation_ids_by_grid_cell: observationIdsByGridCell,
    node_ids_by_grid_cell: nodeIdsByGridCell,
    observation_grid_cell_size_meter: OBSERVATION_GRID_CELL_SIZE_METER
  };
}

/**
 * 実行時状態の空箱を作る。
 *
 * @param {ScenarioInput} scenario
 * @returns {SimulationRuntime}
 */
export function createSimulationRuntime(scenario) {
  const requestWindowMin = scenario.simulation_config.request_window_min ?? 5;
  const requestWindows = buildRequestWindows(
    scenario.observation_points,
    requestWindowMin
  );
  const indexes = buildSimulationIndexes(scenario, requestWindows);
  const maxCandidateSpeedKmh = scenario.graph.ways.reduce((maxSpeedKmh, way) => (
    Math.max(maxSpeedKmh, resolveFreeSpeedKmh(way))
  ), 0);
  const maxRequestTargetCount = requestWindows.reduce((maxTargetCount, requestWindow) => (
    Math.max(maxTargetCount, requestWindow.target_count)
  ), 0);
  const loggingConfig = scenario.simulation_config.logging ?? {};
  const loggingEnabled = loggingConfig.enabled !== false;
  const loggingMode = loggingEnabled ? (loggingConfig.mode ?? "summary") : "summary";
  const loggingSampleSize = Math.max(1, loggingConfig.sample_size ?? 200);

  return {
    now_min: scenario.meta.start_time_min ?? 0,
    cars: [],
    active_cars: [],
    request_windows: requestWindows,
    way_states: new Map(),
    indexes,
    event_logs: [],
    event_counters: new Map(),
    logging_enabled: loggingEnabled,
    logging_mode: loggingMode,
    logging_sample_size: loggingSampleSize,
    random_seed: scenario.simulation_config.random_seed,
    next_car_sequence: 1,
    candidate_request_start_index: 0,
    candidate_request_end_index: 0,
    candidate_request_windows: [],
    candidate_requests_by_observation_id: new Map(),
    priority_request_by_observation_id: new Map(),
    max_candidate_speed_kmh: maxCandidateSpeedKmh,
    max_request_target_count: maxRequestTargetCount,
    nearby_observation_ids_cache_by_node: new Map(),
    cell_need_by_grid_cell: new Map(),
    car_count_by_grid_cell: new Map(),
    spawn_credit_by_grid_cell: new Map(),
    route_plan_cache: new Map(),
    shortest_path_trees_by_target_way_id: new Map()
  };
}

/**
 * request score を返す。
 *
 * @param {CarState} car
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {number}
 */
export function computeScoreRequest(car, requestWindow, scenario, runtime) {
  if (car.status !== "active" || car.reserved_request_window_id !== null) {
    return 0;
  }

  const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
  if (!currentWay || !isCarAtNode(car, currentWay)) {
    return 0;
  }

  if (
    isRequestOutsideStraightDistanceReach(
      currentWay.to_node_id,
      requestWindow,
      scenario,
      runtime
    )
  ) {
    return 0;
  }

  const routePlan = computeRoutePlanFromNodeToRequest(
    currentWay.to_node_id,
    requestWindow,
    scenario,
    runtime
  );
  const travelTimeMin = routePlan.travel_time_min;

  return computeScoreRequestFromTravelTimeMin(
    requestWindow,
    travelTimeMin,
    scenario,
    runtime
  );
}

/**
 * 緯度経度から球面距離をメートルで返す。
 *
 * @param {number} lat1
 * @param {number} lon1
 * @param {number} lat2
 * @param {number} lon2
 * @returns {number}
 */
function haversineMeter(lat1, lon1, lat2, lon2) {
  if (
    !Number.isFinite(lat1) ||
    !Number.isFinite(lon1) ||
    !Number.isFinite(lat2) ||
    !Number.isFinite(lon2)
  ) {
    return Number.POSITIVE_INFINITY;
  }

  const earthRadiusMeter = 6371000;
  const toRadian = Math.PI / 180;
  const deltaLat = (lat2 - lat1) * toRadian;
  const deltaLon = (lon2 - lon1) * toRadian;
  const lat1Rad = lat1 * toRadian;
  const lat2Rad = lat2 * toRadian;
  const a =
    Math.sin(deltaLat / 2) ** 2 +
    Math.cos(lat1Rad) * Math.cos(lat2Rad) * Math.sin(deltaLon / 2) ** 2;

  return earthRadiusMeter * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/**
 * request の締切までに直線距離で到達不能なら true を返す。
 *
 * これは経路探索前の安全な枝刈りであり、直線で届かない候補だけを除外する。
 *
 * @param {string} sourceNodeId
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {boolean}
 */
function isRequestOutsideStraightDistanceReach(sourceNodeId, requestWindow, scenario, runtime) {
  const sourceNode = runtime.indexes.nodes_by_id.get(sourceNodeId);
  const observation = runtime.indexes.observations_by_id.get(requestWindow.observation_point_id);
  if (!sourceNode || !observation) {
    return false;
  }

  const requestHorizonMin = scenario.simulation_config.request_horizon_min ?? 20;
  const remainingTimeMin = requestWindow.window_end_min - runtime.now_min;
  const timeBudgetMin = Math.min(requestHorizonMin, remainingTimeMin);
  if (timeBudgetMin <= 0) {
    return true;
  }

  const straightDistanceMeter = haversineMeter(
    sourceNode.lat,
    sourceNode.lon,
    observation.lat,
    observation.lon
  );
  if (!Number.isFinite(straightDistanceMeter)) {
    return false;
  }

  const maxReachableDistanceMeter =
    runtime.max_candidate_speed_kmh * 1000 * timeBudgetMin / 60;

  return straightDistanceMeter > maxReachableDistanceMeter + EPSILON_METER;
}

/**
 * 指定ノードから時間 horizon 内で届きうる observation id 候補を返す。
 *
 * グリッドは候補検索の索引としてのみ使い、最後の可否判定は既存の直線距離条件で行う。
 *
 * @param {string} sourceNodeId
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {string[]}
 */
function collectNearbyObservationIdsForNode(sourceNodeId, scenario, runtime) {
  const requestHorizonMin = scenario.simulation_config.request_horizon_min ?? 20;
  return collectNearbyObservationIdsForNodeWithinHorizon(
    sourceNodeId,
    requestHorizonMin,
    runtime.nearby_observation_ids_cache_by_node,
    runtime
  );
}

/**
 * 指定ノードから指定 horizon 内で届きうる observation id 候補を返す。
 *
 * @param {string} sourceNodeId
 * @param {number} horizonMin
 * @param {Map<string, string[]>} cacheByNode
 * @param {SimulationRuntime} runtime
 * @returns {string[]}
 */
function collectNearbyObservationIdsForNodeWithinHorizon(sourceNodeId, horizonMin, cacheByNode, runtime) {
  const cachedObservationIds = cacheByNode.get(sourceNodeId);
  if (cachedObservationIds) {
    return cachedObservationIds;
  }

  const sourcePosition = runtime.indexes.node_meter_positions_by_id.get(sourceNodeId);
  if (!sourcePosition) {
    const observationIds = [];
    runtime.priority_request_by_observation_id.forEach((requestWindows, observationId) => {
      if (requestWindows.length > 0) {
        observationIds.push(observationId);
      }
    });
    cacheByNode.set(sourceNodeId, observationIds);
    return observationIds;
  }

  const maxReachableDistanceMeter =
    runtime.max_candidate_speed_kmh * 1000 * horizonMin / 60;
  const cellSizeMeter = runtime.indexes.observation_grid_cell_size_meter;
  const minGridX = Math.floor((sourcePosition.x_meter - maxReachableDistanceMeter) / cellSizeMeter);
  const maxGridX = Math.floor((sourcePosition.x_meter + maxReachableDistanceMeter) / cellSizeMeter);
  const minGridY = Math.floor((sourcePosition.y_meter - maxReachableDistanceMeter) / cellSizeMeter);
  const maxGridY = Math.floor((sourcePosition.y_meter + maxReachableDistanceMeter) / cellSizeMeter);
  const seenObservationIds = new Set();

  for (let gridX = minGridX; gridX <= maxGridX; gridX += 1) {
    for (let gridY = minGridY; gridY <= maxGridY; gridY += 1) {
      const gridCellKey = buildGridCellKey(gridX, gridY);
      const observationIds = runtime.indexes.observation_ids_by_grid_cell.get(gridCellKey) ?? [];
      observationIds.forEach((observationId) => {
        if (seenObservationIds.has(observationId)) {
          return;
        }
        seenObservationIds.add(observationId);
      });
    }
  }

  const observationIds = Array.from(seenObservationIds);
  cacheByNode.set(sourceNodeId, observationIds);
  return observationIds;
}

/**
 * 到達所要時間から request score を返す。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} travelTimeMin
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {number}
 */
function computeScoreRequestFromTravelTimeMin(requestWindow, travelTimeMin, scenario, runtime) {
  if (!Number.isFinite(travelTimeMin)) {
    return 0;
  }

  const requestHorizonMin = scenario.simulation_config.request_horizon_min ?? 20;
  if (travelTimeMin > requestHorizonMin) {
    return 0;
  }

  const slackMin = requestWindow.window_end_min - runtime.now_min - travelTimeMin;
  if (slackMin < 0) {
    return 0;
  }

  const deficitRatio = computeDeficitRatio(requestWindow, runtime.now_min);
  if (deficitRatio <= 0) {
    return 0;
  }

  const scoreModel = scenario.simulation_config.score_model;
  const travelDecay = Math.exp(-scoreModel.travel_decay_a * travelTimeMin);
  const slackDecay = Math.exp(-scoreModel.slack_decay_b * slackMin);

  return clamp(deficitRatio * travelDecay * slackDecay, 0, 1);
}

/**
 * 直線距離から作る到達時間下限を分で返す。
 *
 * @param {string} sourceNodeId
 * @param {string} observationId
 * @param {SimulationRuntime} runtime
 * @returns {number}
 */
function computeStraightLineLowerBoundTravelTimeMin(sourceNodeId, observationId, runtime) {
  const sourcePosition = runtime.indexes.node_meter_positions_by_id.get(sourceNodeId);
  const observationPosition = runtime.indexes.observation_meter_positions_by_id.get(observationId);
  if (!sourcePosition || !observationPosition) {
    return 0;
  }

  const maxCandidateSpeedMpm = runtime.max_candidate_speed_kmh * 1000 / 60;
  if (!Number.isFinite(maxCandidateSpeedMpm) || maxCandidateSpeedMpm <= 0) {
    return Number.POSITIVE_INFINITY;
  }

  const deltaXMeter = sourcePosition.x_meter - observationPosition.x_meter;
  const deltaYMeter = sourcePosition.y_meter - observationPosition.y_meter;
  const straightDistanceMeter = Math.hypot(deltaXMeter, deltaYMeter);

  return straightDistanceMeter / maxCandidateSpeedMpm;
}

/**
 * source node から request へ向かう厳密 score の安全な上限値を返す。
 *
 * `travel_decay_a > slack_decay_b` のときだけ、直線距離由来の到達時間下限を使って
 * 厳密 score の上限として扱える。
 *
 * @param {string} sourceNodeId
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {number}
 */
function computeScoreUpperBoundForRequestFromNode(sourceNodeId, requestWindow, scenario, runtime) {
  const deficitRatio = computeDeficitRatio(requestWindow, runtime.now_min);
  if (deficitRatio <= 0) {
    return 0;
  }

  const remainingTimeMin = requestWindow.window_end_min - runtime.now_min;
  if (remainingTimeMin <= 0) {
    return 0;
  }

  const scoreModel = scenario.simulation_config.score_model;
  const travelWeight = scoreModel.travel_decay_a - scoreModel.slack_decay_b;
  if (travelWeight <= 0) {
    return 1;
  }

  const lowerBoundTravelMin = computeStraightLineLowerBoundTravelTimeMin(
    sourceNodeId,
    requestWindow.observation_point_id,
    runtime
  );
  if (!Number.isFinite(lowerBoundTravelMin)) {
    return 0;
  }

  const remainingDecay = Math.exp(-scoreModel.slack_decay_b * remainingTimeMin);
  const travelDecayUpperBound = Math.exp(-travelWeight * lowerBoundTravelMin);

  return clamp(deficitRatio * remainingDecay * travelDecayUpperBound, 0, 1);
}

/**
 * 車のおおまかなメートル座標を返す。
 *
 * 1km グリッド需要計画では厳密な shape 補間までは不要なので、
 * Way の始終点 node 間を線形補間した位置で近似する。
 *
 * @param {CarState} car
 * @param {SimulationRuntime} runtime
 * @returns {{x_meter: number, y_meter: number} | null}
 */
function estimateCarMeterPosition(car, runtime) {
  const way = runtime.indexes.ways_by_id.get(car.current_way_id);
  if (!way) {
    return null;
  }

  const fromPosition = runtime.indexes.node_meter_positions_by_id.get(way.from_node_id);
  const toPosition = runtime.indexes.node_meter_positions_by_id.get(way.to_node_id);
  if (!fromPosition || !toPosition) {
    return null;
  }

  const ratio = way.length_meter > 0
    ? clamp(car.position_meter_on_way / way.length_meter, 0, 1)
    : 0;

  return {
    x_meter: fromPosition.x_meter + (toPosition.x_meter - fromPosition.x_meter) * ratio,
    y_meter: fromPosition.y_meter + (toPosition.y_meter - fromPosition.y_meter) * ratio
  };
}

/**
 * メートル座標からグリッドセルキーを返す。
 *
 * @param {{x_meter: number, y_meter: number}} meterPosition
 * @returns {string}
 */
function buildGridCellKeyFromMeterPosition(meterPosition) {
  const gridX = Math.floor(meterPosition.x_meter / OBSERVATION_GRID_CELL_SIZE_METER);
  const gridY = Math.floor(meterPosition.y_meter / OBSERVATION_GRID_CELL_SIZE_METER);
  return buildGridCellKey(gridX, gridY);
}

/**
 * ある node が属するグリッドセルキーを返す。
 *
 * @param {string} nodeId
 * @param {SimulationRuntime} runtime
 * @returns {string | null}
 */
function getGridCellKeyForNode(nodeId, runtime) {
  const nodePosition = runtime.indexes.node_meter_positions_by_id.get(nodeId);
  if (!nodePosition) {
    return null;
  }

  return buildGridCellKeyFromMeterPosition(nodePosition);
}

/**
 * 各グリッドセル内の現在車両数を返す。
 *
 * @param {SimulationRuntime} runtime
 * @returns {Map<string, number>}
 */
function buildCarCountByGridCell(runtime) {
  const carCountByGridCell = new Map();

  runtime.active_cars.forEach((car) => {
    const meterPosition = estimateCarMeterPosition(car, runtime);
    if (!meterPosition) {
      return;
    }

    const gridCellKey = buildGridCellKeyFromMeterPosition(meterPosition);
    carCountByGridCell.set(
      gridCellKey,
      (carCountByGridCell.get(gridCellKey) ?? 0) + 1
    );
  });

  return carCountByGridCell;
}

/**
 * 各グリッドセルの将来需要量と need を返す。
 *
 * need は
 *
 * future_request_mass(25分) - alpha * current_car_count
 *
 * で定義する。
 *
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {Map<string, number>}
 */
function buildCellNeedByGridCell(scenario, runtime) {
  if (runtime.car_count_by_grid_cell.size === 0) {
    runtime.car_count_by_grid_cell = buildCarCountByGridCell(runtime);
  }

  const futureRequestMassByGridCell = new Map();
  const planningHorizonMin = scenario.simulation_config.standby_horizon_min ?? DEFAULT_UNASSIGNED_HORIZON_MIN;
  const latestRelevantTimeMin = runtime.now_min + planningHorizonMin + EPSILON_TIME_MIN;

  for (
    let index = runtime.candidate_request_start_index;
    index < runtime.request_windows.length;
    index += 1
  ) {
    const requestWindow = runtime.request_windows[index];
    if (requestWindow.time_min > latestRelevantTimeMin) {
      break;
    }
    if (requestWindow.window_end_min < runtime.now_min - EPSILON_TIME_MIN) {
      continue;
    }

    const outstandingCount = Math.max(
      0,
      requestWindow.target_count - requestWindow.assigned_count - requestWindow.reserved_count
    );
    if (outstandingCount <= 0) {
      continue;
    }

    const observationPosition =
      runtime.indexes.observation_meter_positions_by_id.get(requestWindow.observation_point_id);
    if (!observationPosition) {
      continue;
    }

    const gridCellKey = buildGridCellKeyFromMeterPosition(observationPosition);
    futureRequestMassByGridCell.set(
      gridCellKey,
      (futureRequestMassByGridCell.get(gridCellKey) ?? 0) + outstandingCount
    );
  }

  const cellNeedByGridCell = new Map();
  const allGridCellKeys = new Set([
    ...futureRequestMassByGridCell.keys(),
    ...runtime.car_count_by_grid_cell.keys()
  ]);

  allGridCellKeys.forEach((gridCellKey) => {
    const futureRequestMass = futureRequestMassByGridCell.get(gridCellKey) ?? 0;
    const currentCarCount = runtime.car_count_by_grid_cell.get(gridCellKey) ?? 0;
    const cellNeed = futureRequestMass - DEFAULT_GRID_CAR_WEIGHT * currentCarCount;
    cellNeedByGridCell.set(gridCellKey, cellNeed);
  });

  return cellNeedByGridCell;
}

/**
 * 幹線道路か返す。
 *
 * @param {WayRecord} way
 * @returns {boolean}
 */
function isArterialWay(way) {
  return (
    LARGE_ROAD_TYPES.has(way.road_type ?? "") ||
    way.road_type === "motorway" ||
    way.lane_count >= 3
  );
}

/**
 * 準幹線道路か返す。
 *
 * @param {WayRecord} way
 * @returns {boolean}
 */
function isSemiArterialWay(way) {
  return (
    way.road_type === "tertiary" && way.lane_count >= 2
  );
}

/**
 * 保留車の次の Way を返す。
 *
 * 個別 request を直接追わず、1km グリッド need と幹線ボーナスで次方向を選ぶ。
 *
 * @param {WayRecord} currentWay
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {{score: number, next_way_id: string | null}}
 */
function chooseBestUnassignedWay(currentWay, scenario, runtime) {
  if (runtime.cell_need_by_grid_cell.size === 0) {
    runtime.cell_need_by_grid_cell = buildCellNeedByGridCell(scenario, runtime);
  }

  const currentNodeId = currentWay.to_node_id;
  const outgoingWayIds = runtime.indexes.outgoing_way_ids_by_node.get(currentNodeId) ?? [];
  let bestScore = Number.NEGATIVE_INFINITY;
  let bestNextWayId = null;

  outgoingWayIds.forEach((nextWayId) => {
    const nextWay = runtime.indexes.ways_by_id.get(nextWayId);
    if (!nextWay) {
      return;
    }
    if (
      scenario.simulation_config.u_turn_allowed === false &&
      nextWay.to_node_id === currentWay.from_node_id
    ) {
      return;
    }

    const targetGridCellKey = getGridCellKeyForNode(nextWay.to_node_id, runtime);
    const cellNeed = targetGridCellKey
      ? (runtime.cell_need_by_grid_cell.get(targetGridCellKey) ?? 0)
      : 0;
    const arterialBonus = isArterialWay(nextWay)
      ? ARTERIAL_BONUS_SCORE
      : (isSemiArterialWay(nextWay) ? SEMI_ARTERIAL_BONUS_SCORE : 0);
    const score = cellNeed + arterialBonus;

    if (
      score > bestScore + EPSILON_SCORE ||
      (
        Math.abs(score - bestScore) <= EPSILON_SCORE &&
        bestNextWayId !== null &&
        nextWay.id.localeCompare(bestNextWayId) < 0
      )
    ) {
      bestScore = score;
      bestNextWayId = nextWay.id;
    }
  });

  return {
    score: bestScore,
    next_way_id: bestNextWayId
  };
}

/**
 * 指定 node から新車をどの Way へ出すか返す。
 *
 * @param {string} nodeId
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {{score: number, next_way_id: string | null}}
 */
function chooseBestSpawnWayFromNode(nodeId, scenario, runtime) {
  if (runtime.cell_need_by_grid_cell.size === 0) {
    runtime.cell_need_by_grid_cell = buildCellNeedByGridCell(scenario, runtime);
  }

  const outgoingWayIds = runtime.indexes.outgoing_way_ids_by_node.get(nodeId) ?? [];
  let bestScore = Number.NEGATIVE_INFINITY;
  let bestNextWayId = null;

  outgoingWayIds.forEach((nextWayId) => {
    const nextWay = runtime.indexes.ways_by_id.get(nextWayId);
    if (!nextWay) {
      return;
    }

    const targetGridCellKey = getGridCellKeyForNode(nextWay.to_node_id, runtime);
    const cellNeed = targetGridCellKey
      ? (runtime.cell_need_by_grid_cell.get(targetGridCellKey) ?? 0)
      : 0;
    const arterialBonus = isArterialWay(nextWay)
      ? ARTERIAL_BONUS_SCORE
      : (isSemiArterialWay(nextWay) ? SEMI_ARTERIAL_BONUS_SCORE : 0);
    const score = cellNeed + arterialBonus;

    if (
      score > bestScore + EPSILON_SCORE ||
      (
        Math.abs(score - bestScore) <= EPSILON_SCORE &&
        bestNextWayId !== null &&
        nextWay.id.localeCompare(bestNextWayId) < 0
      )
    ) {
      bestScore = score;
      bestNextWayId = nextWay.id;
    }
  });

  return {
    score: bestScore,
    next_way_id: bestNextWayId
  };
}

/**
 * 生成セル内で最も有望な node と Way を返す。
 *
 * @param {string} gridCellKey
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {{node_id: string | null, next_way_id: string | null, score: number}}
 */
function chooseSpawnNodeAndWayForGridCell(gridCellKey, scenario, runtime) {
  const nodeIds = runtime.indexes.node_ids_by_grid_cell.get(gridCellKey) ?? [];
  let bestNodeId = null;
  let bestNextWayId = null;
  let bestScore = Number.NEGATIVE_INFINITY;

  nodeIds.forEach((nodeId) => {
    const wayChoice = chooseBestSpawnWayFromNode(nodeId, scenario, runtime);
    if (!wayChoice.next_way_id) {
      return;
    }

    if (
      wayChoice.score > bestScore + EPSILON_SCORE ||
      (
        Math.abs(wayChoice.score - bestScore) <= EPSILON_SCORE &&
        bestNodeId !== null &&
        nodeId.localeCompare(bestNodeId) < 0
      )
    ) {
      bestNodeId = nodeId;
      bestNextWayId = wayChoice.next_way_id;
      bestScore = wayChoice.score;
    }
  });

  return {
    node_id: bestNodeId,
    next_way_id: bestNextWayId,
    score: bestScore
  };
}

/**
 * 最小優先度キュー。
 *
 * ダイクストラ法で次に確定すべきノードを高速に取り出すために使う。
 */
class MinPriorityQueue {
  constructor() {
    this.items = [];
  }

  /**
   * 要素を追加する。
   *
   * @param {number} priority
   * @param {string} value
   */
  push(priority, value) {
    this.items.push({ priority, value });
    this.bubbleUp(this.items.length - 1);
  }

  /**
   * 最小優先度の要素を取り出す。
   *
   * @returns {{priority: number, value: string} | null}
   */
  pop() {
    if (this.items.length === 0) {
      return null;
    }

    const root = this.items[0];
    const tail = this.items.pop();
    if (this.items.length > 0 && tail) {
      this.items[0] = tail;
      this.bubbleDown(0);
    }

    return root;
  }

  /**
   * 空かどうかを返す。
   *
   * @returns {boolean}
   */
  isEmpty() {
    return this.items.length === 0;
  }

  /**
   * 追加した要素を上に移動する。
   *
   * @param {number} index
   */
  bubbleUp(index) {
    let currentIndex = index;
    while (currentIndex > 0) {
      const parentIndex = Math.floor((currentIndex - 1) / 2);
      if (this.items[parentIndex].priority <= this.items[currentIndex].priority) {
        break;
      }

      [this.items[parentIndex], this.items[currentIndex]] =
        [this.items[currentIndex], this.items[parentIndex]];
      currentIndex = parentIndex;
    }
  }

  /**
   * 取り出し後の根を下に移動する。
   *
   * @param {number} index
   */
  bubbleDown(index) {
    let currentIndex = index;
    while (true) {
      const leftIndex = currentIndex * 2 + 1;
      const rightIndex = currentIndex * 2 + 2;
      let smallestIndex = currentIndex;

      if (
        leftIndex < this.items.length &&
        this.items[leftIndex].priority < this.items[smallestIndex].priority
      ) {
        smallestIndex = leftIndex;
      }

      if (
        rightIndex < this.items.length &&
        this.items[rightIndex].priority < this.items[smallestIndex].priority
      ) {
        smallestIndex = rightIndex;
      }

      if (smallestIndex === currentIndex) {
        break;
      }

      [this.items[currentIndex], this.items[smallestIndex]] =
        [this.items[smallestIndex], this.items[currentIndex]];
      currentIndex = smallestIndex;
    }
  }
}

/**
 * 最短時間経路の Way 列を返す。
 *
 * @param {string} sourceNodeId
 * @param {string} targetWayId
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {string[]}
 */
export function findShortestTimeRouteWayIds(sourceNodeId, targetWayId, scenario, runtime) {
  const targetWay = runtime.indexes.ways_by_id.get(targetWayId);
  if (!targetWay) {
    return [];
  }

  if (sourceNodeId === targetWay.from_node_id) {
    return [targetWay.id];
  }

  const distances = new Map([[sourceNodeId, 0]]);
  const previousNode = new Map();
  const previousWay = new Map();
  const visited = new Set();
  const queue = new MinPriorityQueue();
  queue.push(0, sourceNodeId);

  while (!queue.isEmpty()) {
    const nextItem = queue.pop();
    if (!nextItem) {
      break;
    }

    const currentNodeId = nextItem.value;
    const currentDistance = nextItem.priority;
    if (visited.has(currentNodeId)) {
      continue;
    }

    const knownDistance = distances.get(currentNodeId) ?? Number.POSITIVE_INFINITY;
    if (currentDistance > knownDistance) {
      continue;
    }

    visited.add(currentNodeId);

    if (currentNodeId === targetWay.from_node_id) {
      break;
    }

    const outgoingWayIds = runtime.indexes.outgoing_way_ids_by_node.get(currentNodeId) ?? [];
    outgoingWayIds.forEach((wayId) => {
      const way = runtime.indexes.ways_by_id.get(wayId);
      if (!way || visited.has(way.to_node_id)) {
        return;
      }

      const candidateDistance = currentDistance + getWayTravelTimeMin(way.id, scenario, runtime);
      if (candidateDistance < (distances.get(way.to_node_id) ?? Number.POSITIVE_INFINITY)) {
        distances.set(way.to_node_id, candidateDistance);
        previousNode.set(way.to_node_id, currentNodeId);
        previousWay.set(way.to_node_id, way.id);
        queue.push(candidateDistance, way.to_node_id);
      }
    });
  }

  if (!previousWay.has(targetWay.from_node_id)) {
    return [];
  }

  const routeWayIds = [];
  let cursorNodeId = targetWay.from_node_id;

  while (cursorNodeId !== sourceNodeId) {
    const wayId = previousWay.get(cursorNodeId);
    const prevNodeId = previousNode.get(cursorNodeId);
    if (!wayId || !prevNodeId) {
      return [];
    }
    routeWayIds.unshift(wayId);
    cursorNodeId = prevNodeId;
  }

  routeWayIds.push(targetWay.id);
  return routeWayIds;
}

/**
 * targetWay の始点へ向かう逆向き最短経路木を返す。
 *
 * 広域OSMでは、車ごと・requestごとに通常のダイクストラを走らせると重い。
 * そこで request 側を目的地にした木を一度作り、各車は次に入る Way を参照する。
 * 現段階では経路選択用の重みは自由流所要時間で固定し、実際の移動速度は別途 BPR で更新する。
 *
 * @param {string} targetWayId
 * @param {SimulationRuntime} runtime
 * @returns {ShortestPathTree | null}
 */
function getShortestPathTreeToTargetWay(targetWayId, runtime) {
  const cachedTree = runtime.shortest_path_trees_by_target_way_id.get(targetWayId);
  if (cachedTree) {
    return cachedTree;
  }

  const targetWay = runtime.indexes.ways_by_id.get(targetWayId);
  if (!targetWay) {
    return null;
  }

  const targetNodeId = targetWay.from_node_id;
  const distanceMinByNode = new Map([[targetNodeId, 0]]);
  const nextWayIdByNode = new Map();
  const visited = new Set();
  const queue = new MinPriorityQueue();
  queue.push(0, targetNodeId);

  while (!queue.isEmpty()) {
    const nextItem = queue.pop();
    if (!nextItem) {
      break;
    }

    const currentNodeId = nextItem.value;
    const currentDistance = nextItem.priority;
    if (visited.has(currentNodeId)) {
      continue;
    }

    const knownDistance = distanceMinByNode.get(currentNodeId) ?? Number.POSITIVE_INFINITY;
    if (currentDistance > knownDistance) {
      continue;
    }

    visited.add(currentNodeId);

    const incomingWayIds = runtime.indexes.incoming_way_ids_by_node.get(currentNodeId) ?? [];
    incomingWayIds.forEach((wayId) => {
      const way = runtime.indexes.ways_by_id.get(wayId);
      if (!way || visited.has(way.from_node_id)) {
        return;
      }

      const candidateDistance = currentDistance + getFreeFlowWayTravelTimeMin(way);
      if (candidateDistance < (distanceMinByNode.get(way.from_node_id) ?? Number.POSITIVE_INFINITY)) {
        distanceMinByNode.set(way.from_node_id, candidateDistance);
        nextWayIdByNode.set(way.from_node_id, way.id);
        queue.push(candidateDistance, way.from_node_id);
      }
    });
  }

  const tree = {
    target_way_id: targetWayId,
    target_from_node_id: targetNodeId,
    distance_min_by_node: distanceMinByNode,
    next_way_id_by_node: nextWayIdByNode
  };
  runtime.shortest_path_trees_by_target_way_id.set(targetWayId, tree);
  return tree;
}

/**
 * 逆向き最短経路木から sourceNodeId から targetWayId までの Way 列を復元する。
 *
 * @param {string} sourceNodeId
 * @param {string} targetWayId
 * @param {SimulationRuntime} runtime
 * @returns {string[]}
 */
function findCachedShortestRouteWayIds(sourceNodeId, targetWayId, runtime) {
  const targetWay = runtime.indexes.ways_by_id.get(targetWayId);
  const tree = getShortestPathTreeToTargetWay(targetWayId, runtime);
  if (!targetWay || !tree) {
    return [];
  }

  if (sourceNodeId === tree.target_from_node_id) {
    return [targetWay.id];
  }

  if (!tree.distance_min_by_node.has(sourceNodeId)) {
    return [];
  }

  const routeWayIds = [];
  const visitedNodeIds = new Set();
  let currentNodeId = sourceNodeId;

  while (currentNodeId !== tree.target_from_node_id) {
    if (visitedNodeIds.has(currentNodeId)) {
      return [];
    }
    visitedNodeIds.add(currentNodeId);

    const nextWayId = tree.next_way_id_by_node.get(currentNodeId);
    const nextWay = nextWayId ? runtime.indexes.ways_by_id.get(nextWayId) : null;
    if (!nextWay) {
      return [];
    }

    routeWayIds.push(nextWay.id);
    currentNodeId = nextWay.to_node_id;
  }

  routeWayIds.push(targetWay.id);
  return routeWayIds;
}

/**
 * 1 ステップ分シミュレーションを進める。
 *
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {SimulationRuntime}
 */
export function stepSimulation(scenario, runtime) {
  runtime.active_cars = runtime.active_cars.filter((car) => car.status === "active");
  runtime.way_states = updateWayRuntimeStates(runtime.indexes.ways_by_id, runtime.active_cars);
  refreshCandidateRequestWindows(scenario, runtime);
  runtime.nearby_observation_ids_cache_by_node = new Map();
  runtime.cell_need_by_grid_cell = new Map();
  runtime.car_count_by_grid_cell = new Map();
  runtime.route_plan_cache = new Map();
  syncCarSpeeds(runtime);
  cancelBrokenReservationsIfNeeded(scenario, runtime);
  assignRequestsToIdleCarsAtNodes(scenario, runtime);
  spawnCarsIfNeeded(scenario, runtime);

  runtime.active_cars.forEach((car) => {
    if (car.status !== "active") {
      return;
    }

    const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
    if (!currentWay) {
      car.status = "retired";
      return;
    }

    if (isCarAtNode(car, currentWay)) {
      if (car.reserved_request_window_id === null && car.route_index >= car.route_way_ids.length) {
        if (!tryRetainCarWithoutReservation(car, scenario, runtime, currentWay.to_node_id)) {
          retireCar(car, runtime, currentWay.to_node_id);
          return;
        }
      }
    }

    moveCarOneStep(car, scenario, runtime);
  });

  runtime.now_min += (scenario.simulation_config.time_step_sec ?? 1) / 60;
  runtime.active_cars = runtime.active_cars.filter((car) => car.status === "active");
  return runtime;
}

/**
 * 予約を持たない車を継続させるか判定する。
 *
 * まず車を unassigned 状態へ落とし、その上で soft target を1件だけ選ぶ。
 * 条件を満たせなければ retired とする。
 *
 * @param {CarState} car
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @param {string} nodeId
 * @returns {boolean}
 */
function tryRetainCarWithoutReservation(car, scenario, runtime, nodeId) {
  car.assignment_state = "unassigned";
  car.reservation_fail_count += 1;

  const unassignedFailLimit = scenario.simulation_config.unassigned_fail_limit ?? 3;
  const unassignedTimeLimitMin = scenario.simulation_config.standby_total_time_limit_min ?? 10;
  if (
    car.reservation_fail_count > unassignedFailLimit ||
    car.unassigned_elapsed_min >= unassignedTimeLimitMin - EPSILON_TIME_MIN
  ) {
    return false;
  }

  const started = tryStartStandbyMoveForCar(car, scenario, runtime);
  if (!started) {
    return false;
  }

  appendLogEvent(runtime, {
    event_type: "car_unassigned",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: car.current_way_id,
    position_meter_on_way: car.position_meter_on_way,
    node_id: nodeId,
    request_window_id: car.soft_target_request_window_id,
    value: car.reservation_fail_count
  });

  return true;
}

/**
 * 現在時刻で意味のある request 候補集合を更新する。
 *
 * `request_windows` は時刻順にソート済みなので、各ステップで全件を見直さず、
 * 先頭と末尾のカーソルだけを前へ進める。
 *
 * 候補に残す条件は次の通り。
 *
 * 1. まだ終了していない: `window_end_min >= now`
 * 2. 車が horizon 内で届きうる: `window_start_min <= now + request_horizon_min`
 *
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 */
function refreshCandidateRequestWindows(scenario, runtime) {
  const requestWindows = runtime.request_windows;
  const requestHorizonMin = scenario.simulation_config.request_horizon_min ?? 20;
  const latestRelevantWindowStartMin = runtime.now_min + requestHorizonMin + EPSILON_TIME_MIN;

  while (
    runtime.candidate_request_end_index < requestWindows.length &&
    requestWindows[runtime.candidate_request_end_index].window_start_min <= latestRelevantWindowStartMin
  ) {
    runtime.candidate_request_end_index += 1;
  }

  while (
    runtime.candidate_request_start_index < runtime.candidate_request_end_index &&
    requestWindows[runtime.candidate_request_start_index].window_end_min < runtime.now_min - EPSILON_TIME_MIN
  ) {
    runtime.candidate_request_start_index += 1;
  }

  runtime.candidate_request_windows = requestWindows.slice(
    runtime.candidate_request_start_index,
    runtime.candidate_request_end_index
  );

  const candidateRequestsByObservationId = new Map();
  runtime.candidate_request_windows.forEach((requestWindow) => {
    if (!candidateRequestsByObservationId.has(requestWindow.observation_point_id)) {
      candidateRequestsByObservationId.set(requestWindow.observation_point_id, []);
    }
    candidateRequestsByObservationId.get(requestWindow.observation_point_id).push(requestWindow);
  });
  runtime.candidate_requests_by_observation_id = candidateRequestsByObservationId;
  rebuildPriorityRequestCache(runtime);
}

/**
 * 交差点上で未予約の既存車に先に request を割り当てる。
 *
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 */
function assignRequestsToIdleCarsAtNodes(scenario, runtime) {
  runtime.active_cars.forEach((car) => {
    if (car.status !== "active" || car.reserved_request_window_id !== null) {
      return;
    }

    const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
    if (!currentWay || !isCarAtNode(car, currentWay)) {
      return;
    }

    tryReserveBestRequestForCar(car, scenario, runtime);
  });
}

/**
 * request を予約する。
 *
 * @param {CarState} car
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {boolean}
 */
export function reserveRequestForCar(car, requestWindow, scenario, runtime) {
  const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
  if (!currentWay) {
    return false;
  }

  const reservationScore = computeScoreRequest(car, requestWindow, scenario, runtime);
  if (reservationScore <= 0 && requestWindow.matched_way_id !== car.current_way_id) {
    return false;
  }

  if (isCarAtNode(car, currentWay)) {
    const routePlan = computeRoutePlanFromNodeToRequest(
      currentWay.to_node_id,
      requestWindow,
      scenario,
      runtime
    );
    const travelTimeMin = routePlan.travel_time_min;
    const arrivalTimeMin = runtime.now_min + travelTimeMin;

    if (
      !Number.isFinite(arrivalTimeMin) ||
      !canRequestAcceptArrival(requestWindow, arrivalTimeMin) ||
      computeNeededReservationCountAtArrival(requestWindow, arrivalTimeMin) < 1 ||
      !isPriorityRequestForObservation(requestWindow, arrivalTimeMin, runtime)
    ) {
      return false;
    }
  }

  const routeWayIds = isCarAtNode(car, currentWay)
    ? computeRoutePlanFromNodeToRequest(
      currentWay.to_node_id,
      requestWindow,
      scenario,
      runtime
    ).route_way_ids
    : [requestWindow.matched_way_id];

  if (routeWayIds.length === 0 && requestWindow.matched_way_id !== car.current_way_id) {
    return false;
  }

  requestWindow.reserved_count += 1;
  refreshPriorityRequestForObservation(requestWindow.observation_point_id, runtime);
  car.reserved_request_window_id = requestWindow.id;
  car.assignment_state = "assigned";
  car.soft_target_request_window_id = null;
  car.unassigned_elapsed_min = 0;
  car.reservation_fail_count = 0;
  car.route_way_ids = routeWayIds;
  car.route_index = 0;

  appendLogEvent(runtime, {
    event_type: "request_reserved",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: car.current_way_id,
    position_meter_on_way: car.position_meter_on_way,
    node_id: isCarAtNode(car, currentWay) ? currentWay.to_node_id : null,
    request_window_id: requestWindow.id,
    value: reservationScore
  });

  return true;
}

/**
 * request 予約を解除する。
 *
 * @param {CarState} car
 * @param {SimulationRuntime} runtime
 * @param {string} eventType
 * @param {number | null} value
 */
export function cancelCarReservation(car, runtime, eventType = "request_cancelled", value = null) {
  if (car.reserved_request_window_id === null) {
    return;
  }

  const requestWindow = runtime.indexes.requests_by_id.get(car.reserved_request_window_id);
  if (requestWindow) {
    requestWindow.reserved_count = Math.max(0, requestWindow.reserved_count - 1);
    if (eventType === "request_failed") {
      requestWindow.failed_count += 1;
    }
    refreshPriorityRequestForObservation(requestWindow.observation_point_id, runtime);
  }

  appendLogEvent(runtime, {
    event_type: eventType,
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: car.current_way_id,
    position_meter_on_way: car.position_meter_on_way,
    node_id: null,
    request_window_id: car.reserved_request_window_id,
    value
  });

  car.reserved_request_window_id = null;
  car.assignment_state = "unassigned";
  car.soft_target_request_window_id = null;
  car.route_way_ids = [];
  car.route_index = 0;
}

/**
 * 値を指定範囲に丸める。
 *
 * @param {number} value
 * @param {number} minValue
 * @param {number} maxValue
 * @returns {number}
 */
function clamp(value, minValue, maxValue) {
  return Math.min(maxValue, Math.max(minValue, value));
}

/**
 * 予想到達時刻が request 窓内に収まるか返す。
 *
 * 終了時刻を過ぎた request は未充足でも予約・生成対象にしない。
 * これにより、期限切れ request が次の request の優先判定を塞ぐのを防ぐ。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} arrivalTimeMin
 * @returns {boolean}
 */
function canRequestAcceptArrival(requestWindow, arrivalTimeMin) {
  return arrivalTimeMin <= requestWindow.window_end_min + EPSILON_TIME_MIN;
}

/**
 * 時刻が request 窓内にあるか返す。
 *
 * 1 秒刻みの加算で 480 分が 479.999999999995 のようにずれるため、
 * 境界判定には微小な許容幅を持たせる。
 *
 * @param {RequestWindow} requestWindow
 * @param {number} timeMin
 * @returns {boolean}
 */
function isTimeInRequestWindow(requestWindow, timeMin) {
  return (
    requestWindow.window_start_min - EPSILON_TIME_MIN <= timeMin &&
    timeMin <= requestWindow.window_end_min + EPSILON_TIME_MIN
  );
}

/**
 * 車速度を Way 速度で同期する。
 *
 * @param {SimulationRuntime} runtime
 */
function syncCarSpeeds(runtime) {
  runtime.active_cars.forEach((car) => {
    const way = runtime.indexes.ways_by_id.get(car.current_way_id);
    const wayState = way ? getWayRuntimeState(way.id, runtime) : null;
    if (wayState) {
      car.current_speed_mps = wayState.current_speed_mps;
    }
  });
}

/**
 * Way の実行時状態を返す。
 *
 * `runtime.way_states` は車がいるWayだけを持つ。
 * 未登録のWayは空いているWayとみなし、自由流状態をその場で計算する。
 *
 * @param {string} wayId
 * @param {SimulationRuntime} runtime
 * @returns {WayRuntimeState | null}
 */
function getWayRuntimeState(wayId, runtime) {
  const storedState = runtime.way_states.get(wayId);
  if (storedState) {
    return storedState;
  }

  const way = runtime.indexes.ways_by_id.get(wayId);
  if (!way) {
    return null;
  }

  return buildWayRuntimeState(way, 0);
}

/**
 * 指定台数に対するWay状態を作る。
 *
 * @param {WayRecord} way
 * @param {number} currentCarCount
 * @returns {WayRuntimeState}
 */
function buildWayRuntimeState(way, currentCarCount) {
  const freeSpeedKmh = resolveFreeSpeedKmh(way);
  const speedState = computeWaySpeedState(
    freeSpeedKmh,
    currentCarCount,
    way.storage_capacity_cars
  );

  return {
    way_id: way.id,
    current_car_count: currentCarCount,
    occupancy_ratio: speedState.occupancy_ratio,
    free_speed_kmh: freeSpeedKmh,
    current_speed_kmh: speedState.current_speed_kmh,
    current_speed_mps: speedState.current_speed_mps,
    dynamic_flow_rate_cars_per_min: computeDynamicFlowRateCarsPerMin(
      way.lane_count,
      speedState.current_speed_kmh
    )
  };
}

/**
 * Way の所要時間を分で返す。
 *
 * @param {string} wayId
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {number}
 */
function getWayTravelTimeMin(wayId, scenario, runtime) {
  const way = runtime.indexes.ways_by_id.get(wayId);
  const wayState = getWayRuntimeState(wayId, runtime);
  if (!way || !wayState || wayState.current_speed_mps <= 0) {
    return Number.POSITIVE_INFINITY;
  }

  return way.length_meter / wayState.current_speed_mps / 60;
}

/**
 * Way の自由流所要時間を分で返す。
 *
 * 経路選択キャッシュでは、混雑で毎秒変わる速度ではなく自由流速度を使う。
 * これにより広域OSMでも同じ目的地への経路木を再利用できる。
 *
 * @param {WayRecord} way
 * @returns {number}
 */
function getFreeFlowWayTravelTimeMin(way) {
  const freeSpeedMps = resolveFreeSpeedKmh(way) * 1000 / 3600;
  if (freeSpeedMps <= 0) {
    return Number.POSITIVE_INFINITY;
  }

  return way.length_meter / freeSpeedMps / 60;
}

/**
 * Node から request 観測点までの最短所要時間を返す。
 *
 * @param {string} sourceNodeId
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {number}
 */
function computeTravelTimeMinFromNodeToRequest(sourceNodeId, requestWindow, scenario, runtime) {
  return computeRoutePlanFromNodeToRequest(
    sourceNodeId,
    requestWindow,
    scenario,
    runtime
  ).travel_time_min;
}

/**
 * Node から request 観測点までの経路と所要時間を返す。
 *
 * 同じステップ内で同じ始点・request の評価が何度も発生するため、
 * 結果を runtime.route_plan_cache に保存して重複計算を避ける。
 *
 * @param {string} sourceNodeId
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {{travel_time_min: number, route_way_ids: string[]}}
 */
function computeRoutePlanFromNodeToRequest(sourceNodeId, requestWindow, scenario, runtime) {
  const cacheKey = `${sourceNodeId}__${requestWindow.id}`;
  const cachedPlan = runtime.route_plan_cache.get(cacheKey);
  if (cachedPlan) {
    return cachedPlan;
  }

  const targetWay = runtime.indexes.ways_by_id.get(requestWindow.matched_way_id);
  const observation = runtime.indexes.observations_by_id.get(requestWindow.observation_point_id);
  const targetWayState = getWayRuntimeState(requestWindow.matched_way_id, runtime);

  if (!targetWay || !observation || !targetWayState || targetWayState.current_speed_mps <= 0) {
    const emptyPlan = {
      travel_time_min: Number.POSITIVE_INFINITY,
      route_way_ids: []
    };
    runtime.route_plan_cache.set(cacheKey, emptyPlan);
    return emptyPlan;
  }

  const tree = getShortestPathTreeToTargetWay(requestWindow.matched_way_id, runtime);
  const routeWayIds = findCachedShortestRouteWayIds(
    sourceNodeId,
    requestWindow.matched_way_id,
    runtime
  );

  if (!tree || routeWayIds.length === 0) {
    const emptyPlan = {
      travel_time_min: Number.POSITIVE_INFINITY,
      route_way_ids: []
    };
    runtime.route_plan_cache.set(cacheKey, emptyPlan);
    return emptyPlan;
  }

  let totalMin = tree.distance_min_by_node.get(sourceNodeId) ?? Number.POSITIVE_INFINITY;
  const targetMeters = clamp(observation.matched_position_ratio, 0, 1) * targetWay.length_meter;
  totalMin += targetMeters / targetWayState.current_speed_mps / 60;

  const routePlan = {
    travel_time_min: totalMin,
    route_way_ids: routeWayIds
  };
  runtime.route_plan_cache.set(cacheKey, routePlan);
  return routePlan;
}

/**
 * 新車が request 観測点へ到達する予想到達時刻を返す。
 *
 * @param {RequestWindow} requestWindow
 * @param {SimulationRuntime} runtime
 * @returns {number}
 */
function computeSpawnArrivalTimeMin(requestWindow, runtime) {
  const targetWay = runtime.indexes.ways_by_id.get(requestWindow.matched_way_id);
  const observation = runtime.indexes.observations_by_id.get(requestWindow.observation_point_id);
  const targetWayState = getWayRuntimeState(requestWindow.matched_way_id, runtime);

  if (!targetWay || !observation || !targetWayState || targetWayState.current_speed_mps <= 0) {
    return Number.POSITIVE_INFINITY;
  }

  const targetMeters = clamp(observation.matched_position_ratio, 0, 1) * targetWay.length_meter;
  return runtime.now_min + targetMeters / targetWayState.current_speed_mps / 60;
}

/**
 * 予約破綻をチェックする。
 *
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 */
function cancelBrokenReservationsIfNeeded(scenario, runtime) {
  runtime.active_cars.forEach((car) => {
    if (car.status !== "active" || car.reserved_request_window_id === null) {
      return;
    }

    const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
    const requestWindow = runtime.indexes.requests_by_id.get(car.reserved_request_window_id);

    if (!currentWay || !requestWindow || !isCarAtNode(car, currentWay)) {
      return;
    }

    const travelTimeMin = computeTravelTimeMinFromNodeToRequest(
      currentWay.to_node_id,
      requestWindow,
      scenario,
      runtime
    );
    const slackMin = requestWindow.window_end_min - runtime.now_min - travelTimeMin;

    if (slackMin < 0) {
      cancelCarReservation(
        car,
        runtime,
        "request_failed",
        Number.isFinite(slackMin) ? slackMin : null
      );
    }
  });
}

/**
 * セル need に応じて新車を補充する。
 *
 * request 不足へ直接反応させず、1km セルごとの need を生成クレジットへ積む。
 * これにより 5 分窓切替のスパイクを弱める。
 *
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 */
function spawnCarsIfNeeded(scenario, runtime) {
  if (runtime.cell_need_by_grid_cell.size === 0) {
    runtime.cell_need_by_grid_cell = buildCellNeedByGridCell(scenario, runtime);
  }

  const planningHorizonMin = scenario.simulation_config.standby_horizon_min ?? DEFAULT_UNASSIGNED_HORIZON_MIN;
  const stepTimeMin = (scenario.simulation_config.time_step_sec ?? 1) / 60;
  const candidateCells = Array.from(runtime.cell_need_by_grid_cell.entries())
    .filter(([, cellNeed]) => cellNeed > 0)
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]));

  candidateCells.forEach(([gridCellKey, cellNeed]) => {
    const nextCredit =
      (runtime.spawn_credit_by_grid_cell.get(gridCellKey) ?? 0) +
      cellNeed * stepTimeMin / planningHorizonMin;
    runtime.spawn_credit_by_grid_cell.set(gridCellKey, nextCredit);
  });

  candidateCells.forEach(([gridCellKey]) => {
    while ((runtime.spawn_credit_by_grid_cell.get(gridCellKey) ?? 0) >= 1 - EPSILON_SCORE) {
      const spawnChoice = chooseSpawnNodeAndWayForGridCell(gridCellKey, scenario, runtime);
      if (!spawnChoice.node_id || !spawnChoice.next_way_id) {
        break;
      }

      const spawned = spawnCarForCell(gridCellKey, spawnChoice.node_id, spawnChoice.next_way_id, runtime);
      if (!spawned) {
        break;
      }

      runtime.spawn_credit_by_grid_cell.set(
        gridCellKey,
        (runtime.spawn_credit_by_grid_cell.get(gridCellKey) ?? 0) - 1
      );
      runtime.car_count_by_grid_cell.set(
        gridCellKey,
        (runtime.car_count_by_grid_cell.get(gridCellKey) ?? 0) + 1
      );
      runtime.cell_need_by_grid_cell.set(
        gridCellKey,
        (runtime.cell_need_by_grid_cell.get(gridCellKey) ?? 0) - 1
      );
    }
  });
}

/**
 * 交差点上で未予約の車だけを集める。
 *
 * 新車生成時の既存車探索では、走行中の車は候補にならない。
 * そのため毎 request ごとに全 active 車両を走査せず、候補を事前に絞る。
 *
 * @param {SimulationRuntime} runtime
 * @returns {{
 *   idle_car_entries: {car: CarState, current_way: WayRecord}[],
 *   idle_cars_by_node_id: Map<string, {car: CarState, current_way: WayRecord}[]>,
 *   idle_node_ids_by_grid_cell: Map<string, string[]>
 * }}
 */
function collectIdleCarsAtNodes(runtime) {
  const idleCarsAtNodes = [];
  const idleCarsByNodeId = new Map();
  const idleNodeIdsByGridCell = new Map();

  runtime.active_cars.forEach((car) => {
    if (car.status !== "active" || car.reserved_request_window_id !== null) {
      return;
    }

    const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
    if (!currentWay || !isCarAtNode(car, currentWay)) {
      return;
    }

    const idleCarEntry = {
      car,
      current_way: currentWay
    };
    idleCarsAtNodes.push(idleCarEntry);

    if (!idleCarsByNodeId.has(currentWay.to_node_id)) {
      idleCarsByNodeId.set(currentWay.to_node_id, []);
    }
    idleCarsByNodeId.get(currentWay.to_node_id).push(idleCarEntry);

    const nodeMeterPosition = runtime.indexes.node_meter_positions_by_id.get(currentWay.to_node_id);
    if (!nodeMeterPosition) {
      return;
    }

    const gridX = Math.floor(nodeMeterPosition.x_meter / OBSERVATION_GRID_CELL_SIZE_METER);
    const gridY = Math.floor(nodeMeterPosition.y_meter / OBSERVATION_GRID_CELL_SIZE_METER);
    const gridCellKey = buildGridCellKey(gridX, gridY);
    if (!idleNodeIdsByGridCell.has(gridCellKey)) {
      idleNodeIdsByGridCell.set(gridCellKey, []);
    }

    const idleNodeIds = idleNodeIdsByGridCell.get(gridCellKey);
    if (!idleNodeIds.includes(currentWay.to_node_id)) {
      idleNodeIds.push(currentWay.to_node_id);
    }
  });

  return {
    idle_car_entries: idleCarsAtNodes,
    idle_cars_by_node_id: idleCarsByNodeId,
    idle_node_ids_by_grid_cell: idleNodeIdsByGridCell
  };
}

/**
 * request から時間予算内に入りうる idle car 候補を返す。
 *
 * グリッドは node 候補の索引として使い、最後の可否判定は既存の経路・時間判定で行う。
 *
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @param {{
 *   idle_car_entries: {car: CarState, current_way: WayRecord}[],
 *   idle_cars_by_node_id: Map<string, {car: CarState, current_way: WayRecord}[]>,
 *   idle_node_ids_by_grid_cell: Map<string, string[]>
 * }} idleCarsAtNodes
 * @returns {string[]}
 */
function collectNearbyIdleNodeIdsForRequest(requestWindow, scenario, runtime, idleCarsAtNodes) {
  const observationPosition =
    runtime.indexes.observation_meter_positions_by_id.get(requestWindow.observation_point_id);
  if (!observationPosition) {
    return Array.from(idleCarsAtNodes.idle_cars_by_node_id.keys());
  }

  const requestHorizonMin = scenario.simulation_config.request_horizon_min ?? 20;
  const remainingTimeMin = requestWindow.window_end_min - runtime.now_min;
  const timeBudgetMin = Math.min(requestHorizonMin, remainingTimeMin);
  if (timeBudgetMin <= 0) {
    return [];
  }

  const maxReachableDistanceMeter =
    runtime.max_candidate_speed_kmh * 1000 * timeBudgetMin / 60;
  const cellSizeMeter = runtime.indexes.observation_grid_cell_size_meter;
  const minGridX = Math.floor((observationPosition.x_meter - maxReachableDistanceMeter) / cellSizeMeter);
  const maxGridX = Math.floor((observationPosition.x_meter + maxReachableDistanceMeter) / cellSizeMeter);
  const minGridY = Math.floor((observationPosition.y_meter - maxReachableDistanceMeter) / cellSizeMeter);
  const maxGridY = Math.floor((observationPosition.y_meter + maxReachableDistanceMeter) / cellSizeMeter);
  const seenNodeIds = new Set();

  for (let gridX = minGridX; gridX <= maxGridX; gridX += 1) {
    for (let gridY = minGridY; gridY <= maxGridY; gridY += 1) {
      const gridCellKey = buildGridCellKey(gridX, gridY);
      const idleNodeIds = idleCarsAtNodes.idle_node_ids_by_grid_cell.get(gridCellKey) ?? [];
      idleNodeIds.forEach((nodeId) => {
        if (seenNodeIds.has(nodeId)) {
          return;
        }
        seenNodeIds.add(nodeId);
      });
    }
  }

  return Array.from(seenNodeIds);
}

/**
 * request を担当できる未予約車がいるか返す。
 *
 * @param {RequestWindow} requestWindow
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @param {{
 *   idle_car_entries: {car: CarState, current_way: WayRecord}[],
 *   idle_cars_by_node_id: Map<string, {car: CarState, current_way: WayRecord}[]>,
 *   idle_node_ids_by_grid_cell: Map<string, string[]>
 * }} idleCarsAtNodes
 * @returns {boolean}
 */
function hasAvailableCarForRequest(requestWindow, scenario, runtime, idleCarsAtNodes) {
  const nearbyIdleNodeIds = collectNearbyIdleNodeIdsForRequest(
    requestWindow,
    scenario,
    runtime,
    idleCarsAtNodes
  );
  const nodeCandidates = [];
  let firstNodeCandidate = null;
  let firstNodeProxyScore = Number.NEGATIVE_INFINITY;

  nearbyIdleNodeIds.forEach((nodeId) => {
    if (
      isRequestOutsideStraightDistanceReach(
        nodeId,
        requestWindow,
        scenario,
        runtime
      )
    ) {
      return;
    }

    const proxyScoreUpperBound = computeScoreUpperBoundForRequestFromNode(
      nodeId,
      requestWindow,
      scenario,
      runtime
    );
    if (proxyScoreUpperBound <= 0) {
      return;
    }

    const nodeCandidate = {
      node_id: nodeId,
      proxy_score_upper_bound: proxyScoreUpperBound
    };
    nodeCandidates.push(nodeCandidate);

    const isBetterProxy = proxyScoreUpperBound > firstNodeProxyScore;
    const isSameProxy = proxyScoreUpperBound === firstNodeProxyScore;
    const isEarlierNodeId =
      firstNodeCandidate !== null &&
      nodeId.localeCompare(firstNodeCandidate.node_id) < 0;

    if (
      isBetterProxy ||
      (isSameProxy && (firstNodeCandidate === null || isEarlierNodeId))
    ) {
      firstNodeCandidate = nodeCandidate;
      firstNodeProxyScore = proxyScoreUpperBound;
    }
  });

  const canNodeHandleRequest = (nodeId) => {
    const routePlan = computeRoutePlanFromNodeToRequest(
      nodeId,
      requestWindow,
      scenario,
      runtime
    );
    const travelTimeMin = routePlan.travel_time_min;
    const arrivalTimeMin = runtime.now_min + travelTimeMin;

    return (
      Number.isFinite(arrivalTimeMin) &&
      canRequestAcceptArrival(requestWindow, arrivalTimeMin) &&
      computeNeededReservationCountAtArrival(requestWindow, arrivalTimeMin) >= 1 &&
      isPriorityRequestForObservation(requestWindow, arrivalTimeMin, runtime) &&
      computeScoreRequestFromTravelTimeMin(requestWindow, travelTimeMin, scenario, runtime) > 0
    );
  };

  if (firstNodeCandidate && canNodeHandleRequest(firstNodeCandidate.node_id)) {
    return true;
  }

  return nodeCandidates.some((nodeCandidate) => {
    if (nodeCandidate === firstNodeCandidate) {
      return false;
    }
    return canNodeHandleRequest(nodeCandidate.node_id);
  });
}

/**
 * request の始点側に新車を作る。
 *
 * @param {RequestWindow} requestWindow
 * @param {SimulationRuntime} runtime
 */
function spawnCarForRequest(requestWindow, runtime) {
  const way = runtime.indexes.ways_by_id.get(requestWindow.matched_way_id);
  const wayState = getWayRuntimeState(requestWindow.matched_way_id, runtime);
  if (!way || !wayState) {
    return;
  }

  const car = {
    id: `car_${String(runtime.next_car_sequence).padStart(6, "0")}`,
    birth_time_min: runtime.now_min,
    current_way_id: way.id,
    position_meter_on_way: 0,
    current_speed_mps: wayState.current_speed_mps,
    reserved_request_window_id: requestWindow.id,
    assignment_state: "assigned",
    soft_target_request_window_id: null,
    unassigned_elapsed_min: 0,
    reservation_fail_count: 0,
    route_way_ids: [],
    route_index: 0,
    status: "active"
  };

  runtime.next_car_sequence += 1;
  runtime.cars.push(car);
  runtime.active_cars.push(car);
  requestWindow.reserved_count += 1;
  refreshPriorityRequestForObservation(requestWindow.observation_point_id, runtime);

  appendLogEvent(runtime, {
    event_type: "car_spawn",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: car.current_way_id,
    position_meter_on_way: car.position_meter_on_way,
    node_id: way.from_node_id,
    request_window_id: requestWindow.id,
    value: 1
  });

  appendLogEvent(runtime, {
    event_type: "request_reserved",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: car.current_way_id,
    position_meter_on_way: car.position_meter_on_way,
    node_id: way.from_node_id,
    request_window_id: requestWindow.id,
    value: 1
  });
}

/**
 * 指定セル内の node / way から新車を出す。
 *
 * 新車は unassigned 状態で始め、まず不足セル方向へ流す。
 *
 * @param {string} gridCellKey
 * @param {string} nodeId
 * @param {string} nextWayId
 * @param {SimulationRuntime} runtime
 * @returns {boolean}
 */
function spawnCarForCell(gridCellKey, nodeId, nextWayId, runtime) {
  const way = runtime.indexes.ways_by_id.get(nextWayId);
  const wayState = getWayRuntimeState(nextWayId, runtime);
  if (!way || !wayState) {
    return false;
  }

  const car = {
    id: `car_${String(runtime.next_car_sequence).padStart(6, "0")}`,
    birth_time_min: runtime.now_min,
    current_way_id: way.id,
    position_meter_on_way: 0,
    current_speed_mps: wayState.current_speed_mps,
    reserved_request_window_id: null,
    assignment_state: "unassigned",
    soft_target_request_window_id: null,
    unassigned_elapsed_min: 0,
    reservation_fail_count: 0,
    route_way_ids: [],
    route_index: 0,
    status: "active"
  };

  runtime.next_car_sequence += 1;
  runtime.cars.push(car);
  runtime.active_cars.push(car);

  appendLogEvent(runtime, {
    event_type: "car_spawn",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: way.id,
    position_meter_on_way: 0,
    node_id: nodeId,
    request_window_id: null,
    value: runtime.cell_need_by_grid_cell.get(gridCellKey) ?? 0
  });

  return true;
}

/**
 * 車に最も良い request を予約させる。
 *
 * @param {CarState} car
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 */
function tryReserveBestRequestForCar(car, scenario, runtime) {
  let bestRequestWindow = null;
  let bestScore = Number.NEGATIVE_INFINITY;
  const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
  if (!currentWay || !isCarAtNode(car, currentWay)) {
    return;
  }

  const nearbyObservationIds = collectNearbyObservationIdsForNode(
    currentWay.to_node_id,
    scenario,
    runtime
  );
  const proxyCandidates = [];
  let firstCandidate = null;
  let firstCandidateProxyScore = Number.NEGATIVE_INFINITY;

  nearbyObservationIds.forEach((observationId) => {
    const priorityRequests = runtime.priority_request_by_observation_id.get(observationId) ?? [];
    priorityRequests.forEach((requestWindow) => {
      if (
        isRequestOutsideStraightDistanceReach(
          currentWay.to_node_id,
          requestWindow,
          scenario,
          runtime
        )
      ) {
        return;
      }

      const proxyScoreUpperBound = computeScoreUpperBoundForRequestFromNode(
        currentWay.to_node_id,
        requestWindow,
        scenario,
        runtime
      );
      if (proxyScoreUpperBound <= 0) {
        return;
      }

      const candidate = {
        observationId,
        requestWindow,
        proxyScoreUpperBound
      };
      proxyCandidates.push(candidate);

      const isBetterProxy = proxyScoreUpperBound > firstCandidateProxyScore;
      const isSameProxy = proxyScoreUpperBound === firstCandidateProxyScore;
      const isEarlierTime =
        firstCandidate !== null &&
        requestWindow.time_min < firstCandidate.requestWindow.time_min;
      const isSameTimeEarlierId =
        firstCandidate !== null &&
        requestWindow.time_min === firstCandidate.requestWindow.time_min &&
        requestWindow.id.localeCompare(firstCandidate.requestWindow.id) < 0;

      if (
        isBetterProxy ||
        (isSameProxy && (firstCandidate === null || isEarlierTime || isSameTimeEarlierId))
      ) {
        firstCandidate = candidate;
        firstCandidateProxyScore = proxyScoreUpperBound;
      }
    });
  });

  const evaluateCandidate = (candidate) => {
    if (candidate.proxyScoreUpperBound <= bestScore + EPSILON_SCORE) {
      return;
    }

    const routePlan = computeRoutePlanFromNodeToRequest(
      currentWay.to_node_id,
      candidate.requestWindow,
      scenario,
      runtime
    );
    const travelTimeMin = routePlan.travel_time_min;
    const arrivalTimeMin = runtime.now_min + travelTimeMin;
    if (
      !Number.isFinite(arrivalTimeMin) ||
      !canRequestAcceptArrival(candidate.requestWindow, arrivalTimeMin) ||
      computeNeededReservationCountAtArrival(candidate.requestWindow, arrivalTimeMin) < 1 ||
      !isPriorityRequestForObservation(candidate.requestWindow, arrivalTimeMin, runtime)
    ) {
      return;
    }

    const score = computeScoreRequestFromTravelTimeMin(
      candidate.requestWindow,
      travelTimeMin,
      scenario,
      runtime
    );
    if (score <= 0) {
      return;
    }

    const isBetterScore = score > bestScore;
    const isSameScore = score === bestScore;
    const isEarlierTime =
      bestRequestWindow !== null &&
      candidate.requestWindow.time_min < bestRequestWindow.time_min;
    const isSameTimeEarlierId =
      bestRequestWindow !== null &&
      candidate.requestWindow.time_min === bestRequestWindow.time_min &&
      candidate.requestWindow.id.localeCompare(bestRequestWindow.id) < 0;

    if (
      isBetterScore ||
      (isSameScore && (bestRequestWindow === null || isEarlierTime || isSameTimeEarlierId))
    ) {
      bestRequestWindow = candidate.requestWindow;
      bestScore = score;
    }
  };

  if (firstCandidate) {
    evaluateCandidate(firstCandidate);
  }

  proxyCandidates.forEach((candidate) => {
    if (candidate === firstCandidate) {
      return;
    }
    evaluateCandidate(candidate);
  });

  if (!bestRequestWindow) {
    return;
  }

  reserveRequestForCar(car, bestRequestWindow, scenario, runtime);
}

/**
 * 予約不能な車に soft target 移動を設定する。
 *
 * @param {CarState} car
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 * @returns {boolean}
 */
function tryStartStandbyMoveForCar(car, scenario, runtime) {
  const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
  if (!currentWay || !isCarAtNode(car, currentWay)) {
    return false;
  }
  const standbyTotalTimeLimitMin = scenario.simulation_config.standby_total_time_limit_min ?? 10;
  const standbyScoreThreshold = scenario.simulation_config.standby_score_threshold ?? 0.1;
  if (car.unassigned_elapsed_min >= standbyTotalTimeLimitMin - EPSILON_TIME_MIN) {
    return false;
  }

  const currentNodeId = currentWay.to_node_id;
  const wayChoice = chooseBestUnassignedWay(currentWay, scenario, runtime);
  if (!wayChoice.next_way_id || wayChoice.score < standbyScoreThreshold) {
    return false;
  }

  car.assignment_state = "unassigned";
  car.soft_target_request_window_id = null;
  car.route_way_ids = [wayChoice.next_way_id];
  car.route_index = 0;

  appendLogEvent(runtime, {
    event_type: "standby_started",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: wayChoice.next_way_id,
    position_meter_on_way: car.position_meter_on_way,
    node_id: currentNodeId,
    request_window_id: null,
    value: wayChoice.score
  });

  return true;
}

/**
 * 車を 1 ステップ進める。
 *
 * @param {CarState} car
 * @param {ScenarioInput} scenario
 * @param {SimulationRuntime} runtime
 */
function moveCarOneStep(car, scenario, runtime) {
  let remainingDistanceMeter = car.current_speed_mps * (scenario.simulation_config.time_step_sec ?? 1);
  const stepTimeMin = (scenario.simulation_config.time_step_sec ?? 1) / 60;

  while (remainingDistanceMeter > EPSILON_METER && car.status === "active") {
    const currentWay = runtime.indexes.ways_by_id.get(car.current_way_id);
    if (!currentWay) {
      car.status = "retired";
      return;
    }

    if (isCarAtNode(car, currentWay)) {
      const entered = enterNextRouteWayIfNeeded(car, runtime);
      if (!entered) {
        break;
      }
      continue;
    }

    const startPosition = car.position_meter_on_way;
    const remainingOnWay = Math.max(0, currentWay.length_meter - startPosition);
    const movement = Math.min(remainingDistanceMeter, remainingOnWay);
    const endPosition = startPosition + movement;

    car.position_meter_on_way = endPosition;
    remainingDistanceMeter -= movement;

    handleObservationCrossings(car, currentWay, startPosition, endPosition, runtime);

    if (car.position_meter_on_way >= currentWay.length_meter - EPSILON_METER) {
      car.position_meter_on_way = currentWay.length_meter;
      if (remainingDistanceMeter <= EPSILON_METER) {
        break;
      }
    } else {
      break;
    }
  }

  if (
    car.assignment_state === "unassigned" &&
    car.reserved_request_window_id === null &&
    car.route_index < car.route_way_ids.length
  ) {
    car.unassigned_elapsed_min += stepTimeMin;
  }
}

/**
 * 経路に従って次の Way に入る。
 *
 * @param {CarState} car
 * @param {SimulationRuntime} runtime
 * @returns {boolean}
 */
function enterNextRouteWayIfNeeded(car, runtime) {
  if (car.route_index >= car.route_way_ids.length) {
    return false;
  }

  const nextWayId = car.route_way_ids[car.route_index];
  const nextWay = runtime.indexes.ways_by_id.get(nextWayId);
  if (!nextWay) {
    return false;
  }

  car.current_way_id = nextWayId;
  car.position_meter_on_way = 0;
  car.route_index += 1;

  const wayState = getWayRuntimeState(nextWayId, runtime);
  if (wayState) {
    car.current_speed_mps = wayState.current_speed_mps;
  }

  appendLogEvent(runtime, {
    event_type: "way_entered",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: nextWayId,
    position_meter_on_way: 0,
    node_id: nextWay.from_node_id,
    request_window_id: car.reserved_request_window_id,
    value: 1
  });

  return true;
}

/**
 * 観測点通過を処理する。
 *
 * @param {CarState} car
 * @param {WayRecord} way
 * @param {number} startPosition
 * @param {number} endPosition
 * @param {SimulationRuntime} runtime
 */
function handleObservationCrossings(car, way, startPosition, endPosition, runtime) {
  const observations = runtime.indexes.observations_by_way_id.get(way.id) ?? [];
  if (observations.length === 0) {
    return;
  }

  observations.forEach((observation) => {
    const observationPosition = clamp(observation.matched_position_ratio, 0, 1) * way.length_meter;
    const crossed =
      startPosition - EPSILON_METER <= observationPosition &&
      observationPosition <= endPosition + EPSILON_METER &&
      startPosition + EPSILON_METER < observationPosition;

    if (!crossed) {
      return;
    }

    const requestWindow = findAssignableRequestWindowForObservation(
      observation.id,
      car.reserved_request_window_id,
      runtime
    );

    if (requestWindow) {
      requestWindow.assigned_count += 1;
      refreshPriorityRequestForObservation(observation.id, runtime);
    }

    appendLogEvent(runtime, {
      event_type: "observation_passed",
      time_min: runtime.now_min,
      car_id: car.id,
      way_id: way.id,
      position_meter_on_way: observationPosition,
      node_id: null,
      request_window_id: requestWindow?.id ?? null,
      value: 1
    });

    if (requestWindow && car.reserved_request_window_id === requestWindow.id) {
      requestWindow.reserved_count = Math.max(0, requestWindow.reserved_count - 1);
      refreshPriorityRequestForObservation(observation.id, runtime);
      car.reserved_request_window_id = null;
      car.assignment_state = "unassigned";
      car.soft_target_request_window_id = null;
      car.route_way_ids = [];
      car.route_index = 0;
    }
  });
}

/**
 * observation 通過時に加算すべき request を返す。
 *
 * @param {string} observationId
 * @param {string | null} reservedRequestWindowId
 * @param {SimulationRuntime} runtime
 * @returns {RequestWindow | null}
 */
function findAssignableRequestWindowForObservation(observationId, reservedRequestWindowId, runtime) {
  const requestWindows =
    runtime.candidate_requests_by_observation_id.get(observationId) ??
    runtime.indexes.requests_by_observation_id.get(observationId) ??
    [];

  if (reservedRequestWindowId !== null) {
    const reservedRequestWindow = runtime.indexes.requests_by_id.get(reservedRequestWindowId) ?? null;
    if (
      reservedRequestWindow &&
      reservedRequestWindow.observation_point_id === observationId &&
      isTimeInRequestWindow(reservedRequestWindow, runtime.now_min) &&
      reservedRequestWindow.assigned_count < reservedRequestWindow.target_count
    ) {
      return reservedRequestWindow;
    }
  }

  const activeUnfilled = requestWindows.find((requestWindow) => (
    isTimeInRequestWindow(requestWindow, runtime.now_min) &&
    requestWindow.assigned_count < requestWindow.target_count
  ));
  if (activeUnfilled) {
    return activeUnfilled;
  }

  return null;
}

/**
 * 車を終了させる。
 *
 * @param {CarState} car
 * @param {SimulationRuntime} runtime
 * @param {string | null} nodeId
 */
function retireCar(car, runtime, nodeId = null) {
  car.status = "retired";
  car.assignment_state = "unassigned";
  car.soft_target_request_window_id = null;
  appendLogEvent(runtime, {
    event_type: "car_finished",
    time_min: runtime.now_min,
    car_id: car.id,
    way_id: car.current_way_id,
    position_meter_on_way: car.position_meter_on_way,
    node_id: nodeId,
    request_window_id: null,
    value: 0
  });
}

/**
 * 車が Way の終点にいるか返す。
 *
 * @param {CarState} car
 * @param {WayRecord} way
 * @returns {boolean}
 */
function isCarAtNode(car, way) {
  return car.position_meter_on_way >= way.length_meter - EPSILON_METER;
}

/**
 * ログを追加する。
 *
 * @param {SimulationRuntime} runtime
 * @param {LogEvent} event
 */
function appendLogEvent(runtime, event) {
  runtime.event_counters.set(
    event.event_type,
    (runtime.event_counters.get(event.event_type) ?? 0) + 1
  );

  if (!runtime.logging_enabled) {
    return;
  }

  if (runtime.logging_mode === "summary") {
    return;
  }

  runtime.event_logs.push(event);

  if (runtime.logging_mode === "sample" && runtime.event_logs.length > runtime.logging_sample_size) {
    runtime.event_logs.shift();
  }
}

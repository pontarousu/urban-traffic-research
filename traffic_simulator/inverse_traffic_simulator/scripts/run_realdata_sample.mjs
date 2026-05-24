import fs from "node:fs/promises";
import path from "node:path";
import {
  createSimulationRuntime,
  stepSimulation
} from "../src/sim_core.mjs";

const DEFAULT_SCENARIO_PATH = "../data/realdata_sample_small.json";

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const scenarioPath = path.resolve(options.scenario);
  const scenario = JSON.parse(await fs.readFile(scenarioPath, "utf-8"));
  const runtime = createSimulationRuntime(scenario);
  const endMin = options.endMin ?? inferEndMin(scenario);
  const timeStepMin = (scenario.simulation_config.time_step_sec ?? 1) / 60;
  let maxActiveCars = 0;

  while (runtime.now_min < endMin - timeStepMin / 2) {
    stepSimulation(scenario, runtime);
    const activeCars = runtime.active_cars.length;
    maxActiveCars = Math.max(maxActiveCars, activeCars);
  }

  const summary = buildSummary(runtime, maxActiveCars);
  console.log(JSON.stringify(summary, null, 2));
}

/**
 * 実験結果の要約を作る。
 *
 * @param {import("../src/sim_core.mjs").SimulationRuntime} runtime
 * @param {number} maxActiveCars
 * @returns {Object}
 */
function buildSummary(runtime, maxActiveCars) {
  const eventCounts = runtime.event_counters ?? new Map();

  const totalTargetCount = runtime.request_windows.reduce(
    (sum, requestWindow) => sum + requestWindow.target_count,
    0
  );
  const totalAssignedCount = runtime.request_windows.reduce(
    (sum, requestWindow) => sum + requestWindow.assigned_count,
    0
  );
  const totalReservedCount = runtime.request_windows.reduce(
    (sum, requestWindow) => sum + requestWindow.reserved_count,
    0
  );
  const totalFailedCount = runtime.request_windows.reduce(
    (sum, requestWindow) => sum + requestWindow.failed_count,
    0
  );
  const underfilledRequests = runtime.request_windows
    .filter((requestWindow) => requestWindow.assigned_count < requestWindow.target_count)
    .map(formatRequestWindow);
  const overfilledRequests = runtime.request_windows
    .filter((requestWindow) => requestWindow.assigned_count > requestWindow.target_count)
    .map(formatRequestWindow);

  return {
    now_min: round(runtime.now_min, 4),
    cars_total: runtime.cars.length,
    cars_active: runtime.active_cars.length,
    cars_finished: runtime.cars.filter((car) => car.status === "retired").length,
    max_active_cars: maxActiveCars,
    request_window_count: runtime.request_windows.length,
    total_target_count: totalTargetCount,
    total_assigned_count: totalAssignedCount,
    total_reserved_count: totalReservedCount,
    total_failed_count: totalFailedCount,
    fill_rate: totalTargetCount > 0 ? round(totalAssignedCount / totalTargetCount, 4) : null,
    underfilled_request_count: underfilledRequests.length,
    overfilled_request_count: overfilledRequests.length,
    logging_mode: runtime.logging_mode,
    logged_event_count: runtime.event_logs.length,
    event_counts: Object.fromEntries(eventCounts.entries()),
    underfilled_requests: underfilledRequests.slice(0, 20),
    overfilled_requests: overfilledRequests.slice(0, 20),
    recent_events: runtime.event_logs.slice(-10)
  };
}

/**
 * RequestWindow をログ表示用に整形する。
 *
 * @param {Object} requestWindow
 * @returns {Object}
 */
function formatRequestWindow(requestWindow) {
  return {
    id: requestWindow.id,
    time_min: requestWindow.time_min,
    target_count: requestWindow.target_count,
    assigned_count: requestWindow.assigned_count,
    reserved_count: requestWindow.reserved_count,
    failed_count: requestWindow.failed_count
  };
}

/**
 * 実験終了時刻を scenario から推定する。
 *
 * @param {Object} scenario
 * @returns {number}
 */
function inferEndMin(scenario) {
  const requestTimes = scenario.observation_points.flatMap((observationPoint) => (
    observationPoint.traffic_volume.map((record) => record.time_min)
  ));
  const lastRequestTime = Math.max(...requestTimes);
  const requestWindowMin = scenario.simulation_config.request_window_min ?? 5;
  return lastRequestTime + requestWindowMin;
}

/**
 * 数値を丸める。
 *
 * @param {number} value
 * @param {number} digits
 * @returns {number}
 */
function round(value, digits) {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
}

/**
 * コマンドラインオプションを読む。
 *
 * @param {string[]} args
 * @returns {{scenario: string, endMin: number | null}}
 */
function parseOptions(args) {
  const options = {
    scenario: DEFAULT_SCENARIO_PATH,
    endMin: null
  };

  for (let index = 0; index < args.length; index += 1) {
    const name = args[index];
    const value = args[index + 1];

    if (name === "--scenario") {
      options.scenario = value;
      index += 1;
    } else if (name === "--end-min") {
      options.endMin = Number(value);
      index += 1;
    }
  }

  if (options.endMin !== null && !Number.isFinite(options.endMin)) {
    throw new Error("--end-min は数値にしてください。");
  }

  return options;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

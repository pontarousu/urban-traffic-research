import fs from "node:fs";
import fsPromises from "node:fs/promises";
import path from "node:path";
import {
  createSimulationRuntime,
  stepSimulation
} from "../src/sim_core.mjs";

const DEFAULT_SCENARIO_PATH =
  "../data/current/tokyo_core_small_realdata_osm_300obs_allday.json";
const DEFAULT_OUTPUT_PATH =
  "../data/current/tokyo_core_small_realdata_osm_300obs_allday_playback.json";

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const scenarioPath = path.resolve(options.scenario);
  const outputPath = path.resolve(options.output);
  const rawScenario = JSON.parse(await fsPromises.readFile(scenarioPath, "utf-8"));
  const scenario = sliceScenarioByTimeRange(rawScenario, options.startMin, options.endMin);
  scenario.simulation_config = {
    ...scenario.simulation_config,
    time_step_sec: options.simulationStepSec ?? scenario.simulation_config?.time_step_sec ?? 1,
    logging: {
      ...(scenario.simulation_config?.logging ?? {}),
      enabled: false
    }
  };
  const runtime = createSimulationRuntime(scenario);
  if (runtime.request_windows.length === 0) {
    throw new Error("指定した時間範囲に request がありません。");
  }
  const endMin = options.endMin ?? inferEndMin(scenario);
  const frameIntervalMin = options.frameIntervalSec / 60;
  const carIndexById = new Map();
  const wayIndexById = new Map(
    scenario.graph.ways.map((way, index) => [way.id, index])
  );
  const wayLookup = scenario.graph.ways.map((way) => [
    way.id,
    round(way.length_meter, 2)
  ]);
  const startTimeMin = round(
    scenario.meta?.start_time_min ?? runtime.request_windows[0]?.window_start_min ?? runtime.now_min,
    4
  );
  const frameCount = computeFrameCount(runtime.now_min, endMin, frameIntervalMin);
  let nextFrameTimeMin = runtime.now_min;
  let maxActiveCars = 0;
  let writtenFrameCount = 0;
  let isFirstFrame = true;

  await fsPromises.mkdir(path.dirname(outputPath), { recursive: true });
  const outputStream = fs.createWriteStream(outputPath, { encoding: "utf-8" });
  try {
    writePlaybackHeader(outputStream, {
      scenario,
      scenarioPath,
      outputPath,
      endMin,
      frameIntervalSec: options.frameIntervalSec,
      simulationStepSec: scenario.simulation_config.time_step_sec,
      startTimeMin,
      frameCount,
      wayLookup
    });

    ({
      isFirstFrame,
      writtenFrameCount
    } = writeFrameRecord(
      outputStream,
      captureFrame(runtime, carIndexById, wayIndexById),
      isFirstFrame,
      writtenFrameCount
    ));
    nextFrameTimeMin += frameIntervalMin;

    const timeStepMin = (scenario.simulation_config.time_step_sec ?? 1) / 60;
    while (runtime.now_min < endMin - timeStepMin / 2) {
      stepSimulation(scenario, runtime);
      maxActiveCars = Math.max(maxActiveCars, runtime.active_cars.length);

      while (runtime.now_min + 1e-7 >= nextFrameTimeMin) {
        ({
          isFirstFrame,
          writtenFrameCount
        } = writeFrameRecord(
          outputStream,
          captureFrame(runtime, carIndexById, wayIndexById),
          isFirstFrame,
          writtenFrameCount
        ));
        nextFrameTimeMin += frameIntervalMin;
      }
    }

    const summary = buildSummary(runtime, maxActiveCars);
    writePlaybackFooter(outputStream, summary);
    await waitForStreamClose(outputStream);

    console.log(JSON.stringify({
      output: path.relative(process.cwd(), outputPath),
      frame_count: writtenFrameCount,
      cars_total: summary.cars_total,
      max_active_cars: summary.max_active_cars,
      fill_rate: summary.fill_rate
    }, null, 2));
  } catch (error) {
    outputStream.destroy();
    throw error;
  }
}

/**
 * Playback 用のフレームを追加する。
 *
 * @param {import("../src/sim_core.mjs").SimulationRuntime} runtime
 * @param {Map<string, number>} carIndexById
 * @param {Map<string, number>} wayIndexById
 * @returns {Object}
 */
function captureFrame(runtime, carIndexById, wayIndexById) {
  const cars = [];

  runtime.active_cars.forEach((car) => {
    const wayIndex = wayIndexById.get(car.current_way_id);
    if (wayIndex === undefined) {
      return;
    }

    const carIndex = getCarIndex(car.id, carIndexById);
    cars.push([
      carIndex,
      wayIndex,
      round(car.position_meter_on_way, 2),
      round(car.current_speed_mps * 3.6, 1)
    ]);
  });

  return {
    time_min: round(runtime.now_min, 4),
    active_car_count: cars.length,
    cars
  };
}

/**
 * playback JSON のヘッダ部分を書き出す。
 *
 * @param {import("node:fs").WriteStream} outputStream
 * @param {Object} options
 */
function writePlaybackHeader(outputStream, options) {
  const header = {
    schema_version: "traffic_playback_v1",
    meta: {
      title: options.scenario.meta?.scenario_name ?? "交通再生ビューア",
      scenario_file: path.relative(path.dirname(options.outputPath), options.scenarioPath),
      source_scenario_id: options.scenario.meta?.scenario_id ?? null,
      start_time_min: options.startTimeMin,
      end_time_min: round(options.endMin, 4),
      frame_interval_sec: options.frameIntervalSec,
      simulation_step_sec: options.simulationStepSec,
      frame_count: options.frameCount,
      car_record_format: "way_position_v2"
    },
    view_box: options.scenario.meta?.view_box ?? computeScenarioViewBox(options.scenario),
    way_lookup: options.wayLookup,
    observations: buildObservationSummaries(options.scenario.observation_points)
  };

  outputStream.write(`${JSON.stringify(header).slice(0, -1)},\"frames\":[`);
}

/**
 * フッタ部分を書き出す。
 *
 * @param {import("node:fs").WriteStream} outputStream
 * @param {Object} summary
 */
function writePlaybackFooter(outputStream, summary) {
  outputStream.write(`],\"summary\":${JSON.stringify(summary)}`);
}

/**
 * 1フレーム分を書き出す。
 *
 * @param {import("node:fs").WriteStream} outputStream
 * @param {Object} frame
 * @param {boolean} isFirstFrame
 * @param {number} writtenFrameCount
 * @returns {{isFirstFrame: boolean, writtenFrameCount: number}}
 */
function writeFrameRecord(outputStream, frame, isFirstFrame, writtenFrameCount) {
  if (!isFirstFrame) {
    outputStream.write(",");
  }
  outputStream.write(JSON.stringify(frame));
  return {
    isFirstFrame: false,
    writtenFrameCount: writtenFrameCount + 1
  };
}

/**
 * playback JSON を閉じる。
 *
 * @param {import("node:fs").WriteStream} outputStream
 */
function closePlaybackJson(outputStream) {
  outputStream.write("}");
}

/**
 * ストリームの close 完了を待つ。
 *
 * @param {import("node:fs").WriteStream} outputStream
 * @returns {Promise<void>}
 */
function waitForStreamClose(outputStream) {
  closePlaybackJson(outputStream);
  outputStream.end();
  return new Promise((resolve, reject) => {
    outputStream.on("finish", resolve);
    outputStream.on("error", reject);
  });
}

/**
 * 観測点の要約を返す。
 *
 * @param {Object[]} observationPoints
 * @returns {Object[]}
 */
function buildObservationSummaries(observationPoints) {
  return observationPoints.map((observationPoint) => ({
    id: observationPoint.id,
    point_name: observationPoint.point_name,
    view_x: round(observationPoint.view_x, 2),
    view_y: round(observationPoint.view_y, 2),
    total_volume: observationPoint.traffic_volume.reduce(
      (sum, record) => sum + record.volume_5min,
      0
    )
  }));
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

  return {
    now_min: round(runtime.now_min, 4),
    cars_total: runtime.cars.length,
    cars_finished: runtime.cars.filter((car) => car.status === "retired").length,
    max_active_cars: maxActiveCars,
    request_window_count: runtime.request_windows.length,
    total_target_count: totalTargetCount,
    total_assigned_count: totalAssignedCount,
    total_reserved_count: totalReservedCount,
    total_failed_count: totalFailedCount,
    fill_rate: totalTargetCount > 0 ? round(totalAssignedCount / totalTargetCount, 4) : null,
    event_counts: Object.fromEntries(eventCounts.entries())
  };
}

/**
 * シナリオの表示範囲を返す。
 *
 * @param {Object} scenario
 * @returns {number[]}
 */
function computeScenarioViewBox(scenario) {
  const points = [];
  scenario.graph.ways.forEach((way) => {
    (way.shape_points ?? []).forEach((point) => points.push(point));
  });

  if (points.length === 0) {
    return [0, 0, 1000, 1000];
  }

  const minX = Math.min(...points.map((point) => point.view_x));
  const maxX = Math.max(...points.map((point) => point.view_x));
  const minY = Math.min(...points.map((point) => point.view_y));
  const maxY = Math.max(...points.map((point) => point.view_y));
  const width = maxX - minX;
  const height = maxY - minY;
  const padding = Math.max(width, height) * 0.03;

  return [
    round(minX - padding, 2),
    round(minY - padding, 2),
    round(width + padding * 2, 2),
    round(height + padding * 2, 2)
  ];
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
 * 指定時間帯だけに観測レコードを切り出した scenario を返す。
 *
 * @param {Object} scenario
 * @param {number | null} startMin
 * @param {number | null} endMin
 * @returns {Object}
 */
function sliceScenarioByTimeRange(scenario, startMin, endMin) {
  const slicedObservationPoints = scenario.observation_points
    .map((observationPoint) => {
      const trafficVolume = observationPoint.traffic_volume.filter((record) => {
        if (startMin !== null && record.time_min < startMin) {
          return false;
        }
        if (endMin !== null && record.time_min > endMin) {
          return false;
        }
        return true;
      });

      return {
        ...observationPoint,
        traffic_volume: trafficVolume
      };
    })
    .filter((observationPoint) => observationPoint.traffic_volume.length > 0);

  return {
    ...scenario,
    meta: {
      ...(scenario.meta ?? {}),
      start_time_min: startMin ?? scenario.meta?.start_time_min ?? 0,
      end_time_min: endMin ?? scenario.meta?.end_time_min ?? null
    },
    observation_points: slicedObservationPoints
  };
}

/**
 * 期待フレーム数を返す。
 *
 * @param {number} startMin
 * @param {number} endMin
 * @param {number} frameIntervalMin
 * @returns {number}
 */
function computeFrameCount(startMin, endMin, frameIntervalMin) {
  if (!Number.isFinite(frameIntervalMin) || frameIntervalMin <= 0) {
    return 1;
  }

  const durationMin = Math.max(0, endMin - startMin);
  return Math.floor(durationMin / frameIntervalMin + 1e-7) + 1;
}

/**
 * 車IDへ連番を振る。
 *
 * @param {string} carId
 * @param {Map<string, number>} carIndexById
 * @returns {number}
 */
function getCarIndex(carId, carIndexById) {
  const existing = carIndexById.get(carId);
  if (existing !== undefined) {
    return existing;
  }

  const nextIndex = carIndexById.size;
  carIndexById.set(carId, nextIndex);
  return nextIndex;
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
 * @returns {{scenario: string, output: string, startMin: number | null, endMin: number | null, frameIntervalSec: number, simulationStepSec: number | null}}
 */
function parseOptions(args) {
  const options = {
    scenario: DEFAULT_SCENARIO_PATH,
    output: DEFAULT_OUTPUT_PATH,
    startMin: null,
    endMin: null,
    frameIntervalSec: 5,
    simulationStepSec: null
  };

  for (let index = 0; index < args.length; index += 1) {
    const name = args[index];
    const value = args[index + 1];

    if (name === "--scenario") {
      options.scenario = value;
      index += 1;
    } else if (name === "--output") {
      options.output = value;
      index += 1;
    } else if (name === "--start-min") {
      options.startMin = Number(value);
      index += 1;
    } else if (name === "--end-min") {
      options.endMin = Number(value);
      index += 1;
    } else if (name === "--frame-interval-sec") {
      options.frameIntervalSec = Number(value);
      index += 1;
    } else if (name === "--simulation-step-sec") {
      options.simulationStepSec = Number(value);
      index += 1;
    }
  }

  if (options.startMin !== null && !Number.isFinite(options.startMin)) {
    throw new Error("--start-min は数値にしてください。");
  }
  if (options.endMin !== null && !Number.isFinite(options.endMin)) {
    throw new Error("--end-min は数値にしてください。");
  }
  if (
    options.startMin !== null &&
    options.endMin !== null &&
    options.startMin >= options.endMin
  ) {
    throw new Error("--start-min は --end-min より小さくしてください。");
  }

  if (!Number.isFinite(options.frameIntervalSec) || options.frameIntervalSec <= 0) {
    throw new Error("--frame-interval-sec は正の数値にしてください。");
  }

  if (
    options.simulationStepSec !== null &&
    (!Number.isFinite(options.simulationStepSec) || options.simulationStepSec <= 0)
  ) {
    throw new Error("--simulation-step-sec は正の数値にしてください。");
  }

  return options;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

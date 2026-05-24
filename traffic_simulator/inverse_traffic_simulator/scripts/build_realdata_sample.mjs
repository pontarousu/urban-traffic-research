import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_INPUT_PATH = "../data/realdata_all.json";
const DEFAULT_OUTPUT_PATH = "../data/realdata_sample_small.json";
const DEFAULT_SYNTHETIC_LANE_COUNT = 4;

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const inputPath = path.resolve(options.input);
  const outputPath = path.resolve(options.output);
  const scenario = JSON.parse(await fs.readFile(inputPath, "utf-8"));

  const selectedObservationPoints = selectObservationPoints(
    scenario.observation_points,
    options.startMin,
    options.durationMin,
    options.pointCount
  );

  if (selectedObservationPoints.length === 0) {
    throw new Error("指定条件に合う観測点が見つかりません。");
  }

  const selectedWayIds = new Set(
    selectedObservationPoints.map((observationPoint) => observationPoint.matched_way_id)
  );
  const selectedWays = scenario.graph.ways
    .filter((way) => selectedWayIds.has(way.id))
    .map((way) => adjustSyntheticWayCapacity(way, options.syntheticLaneCount));
  const selectedNodeIds = new Set();
  const requestWindowMin = scenario.simulation_config.request_window_min ?? 5;
  const simulationStartMin = Math.max(0, options.startMin - requestWindowMin);

  selectedWays.forEach((way) => {
    selectedNodeIds.add(way.from_node_id);
    selectedNodeIds.add(way.to_node_id);
  });

  const selectedNodes = scenario.graph.nodes.filter((node) => selectedNodeIds.has(node.id));
  const sampleScenario = {
    ...scenario,
    meta: {
      ...scenario.meta,
      scenario_id: "realdata_sample_small",
      scenario_name: "Real Traffic Volume Small Sample",
      start_time_min: simulationStartMin,
      sample: {
        source_scenario_id: scenario.meta?.scenario_id ?? null,
        simulation_start_time_min: simulationStartMin,
        first_observation_time_min: options.startMin,
        last_observation_time_min: options.startMin + options.durationMin - 5,
        observation_end_time_min: options.startMin + options.durationMin,
        duration_min: options.durationMin,
        point_count: selectedObservationPoints.length,
        selection_strategy: "指定時間帯の交通量合計が大きい観測点を選択"
      },
      summary: {
        observation_point_count: selectedObservationPoints.length,
        node_count: selectedNodes.length,
        way_count: selectedWays.length,
        request_window_count: selectedObservationPoints.reduce(
          (sum, observationPoint) => sum + observationPoint.traffic_volume.length,
          0
        ),
        total_target_count: selectedObservationPoints.reduce(
          (sum, observationPoint) => sum + sumTrafficVolume(observationPoint.traffic_volume),
          0
        )
      }
    },
    graph: {
      nodes: selectedNodes,
      ways: selectedWays
    },
    observation_points: selectedObservationPoints,
    simulation_config: {
      ...scenario.simulation_config,
      logging: {
        enabled: true
      }
    }
  };

  await fs.writeFile(outputPath, `${JSON.stringify(sampleScenario, null, 2)}\n`, "utf-8");

  console.log("realdata_sample_small.json を生成しました。");
  console.log(JSON.stringify(sampleScenario.meta.summary, null, 2));
  console.log("selected_observation_points:");
  selectedObservationPoints.forEach((observationPoint) => {
    console.log({
      id: observationPoint.id,
      point_number: observationPoint.point_number ?? null,
      point_name: observationPoint.point_name ?? null,
      total_target_count: sumTrafficVolume(observationPoint.traffic_volume)
    });
  });
}

/**
 * 指定時間帯の交通量合計が大きい観測点を選ぶ。
 *
 * @param {Array<Object>} observationPoints
 * @param {number} startMin
 * @param {number} durationMin
 * @param {number} pointCount
 * @returns {Array<Object>}
 */
function selectObservationPoints(observationPoints, startMin, durationMin, pointCount) {
  const endMin = startMin + durationMin;

  return observationPoints
    .map((observationPoint) => {
      const trafficVolume = observationPoint.traffic_volume
        .filter((record) => startMin <= record.time_min && record.time_min < endMin)
        .map((record) => ({
          time_min: record.time_min,
          volume_5min: record.volume_5min
        }));

      return {
        observationPoint: {
          ...observationPoint,
          traffic_volume: trafficVolume
        },
        totalTargetCount: sumTrafficVolume(trafficVolume)
      };
    })
    .filter((candidate) => candidate.totalTargetCount > 0)
    .sort((left, right) => {
      if (right.totalTargetCount !== left.totalTargetCount) {
        return right.totalTargetCount - left.totalTargetCount;
      }
      return left.observationPoint.id.localeCompare(right.observationPoint.id);
    })
    .slice(0, pointCount)
    .map((candidate) => candidate.observationPoint);
}

/**
 * 交通量の合計を返す。
 *
 * @param {{volume_5min: number}[]} trafficVolume
 * @returns {number}
 */
function sumTrafficVolume(trafficVolume) {
  return trafficVolume.reduce((sum, record) => sum + record.volume_5min, 0);
}

/**
 * コマンドラインオプションを読む。
 *
 * @param {string[]} args
 * @returns {{input: string, output: string, startMin: number, durationMin: number, pointCount: number, syntheticLaneCount: number}}
 */
function parseOptions(args) {
  const options = {
    input: DEFAULT_INPUT_PATH,
    output: DEFAULT_OUTPUT_PATH,
    startMin: 8 * 60,
    durationMin: 30,
    pointCount: 5,
    syntheticLaneCount: DEFAULT_SYNTHETIC_LANE_COUNT
  };

  for (let index = 0; index < args.length; index += 1) {
    const name = args[index];
    const value = args[index + 1];

    if (name === "--input") {
      options.input = value;
      index += 1;
    } else if (name === "--output") {
      options.output = value;
      index += 1;
    } else if (name === "--start-min") {
      options.startMin = Number(value);
      index += 1;
    } else if (name === "--duration-min") {
      options.durationMin = Number(value);
      index += 1;
    } else if (name === "--point-count") {
      options.pointCount = Number(value);
      index += 1;
    } else if (name === "--synthetic-lane-count") {
      options.syntheticLaneCount = Number(value);
      index += 1;
    }
  }

  validateOptions(options);
  return options;
}

/**
 * オプション値を検証する。
 *
 * @param {{input: string, output: string, startMin: number, durationMin: number, pointCount: number, syntheticLaneCount: number}} options
 */
function validateOptions(options) {
  if (!Number.isFinite(options.startMin) || options.startMin < 0) {
    throw new Error("--start-min は 0 以上の数値にしてください。");
  }

  if (!Number.isFinite(options.durationMin) || options.durationMin <= 0) {
    throw new Error("--duration-min は正の数値にしてください。");
  }

  if (!Number.isFinite(options.pointCount) || options.pointCount <= 0) {
    throw new Error("--point-count は正の数値にしてください。");
  }

  if (!Number.isFinite(options.syntheticLaneCount) || options.syntheticLaneCount <= 0) {
    throw new Error("--synthetic-lane-count は正の数値にしてください。");
  }
}

/**
 * 実道路マッチング前の仮想 Way に、検証用の十分な容量を与える。
 *
 * @param {Object} way
 * @param {number} laneCount
 * @returns {Object}
 */
function adjustSyntheticWayCapacity(way, laneCount) {
  if (way.road_type !== "synthetic_observation_link") {
    return way;
  }

  return {
    ...way,
    lane_count: laneCount,
    storage_capacity_cars: Math.max(
      laneCount,
      Math.floor(way.length_meter / 4) * laneCount
    )
  };
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

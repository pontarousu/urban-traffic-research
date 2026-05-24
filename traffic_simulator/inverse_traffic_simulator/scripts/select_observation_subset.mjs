import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_INPUT_PATH = "../data/tokyo_core_small_realdata_osm_allmatched_5min.json";
const DEFAULT_OUTPUT_PATH = "../data/tokyo_core_small_realdata_osm_subset.json";

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const inputPath = path.resolve(options.input);
  const outputPath = path.resolve(options.output);
  const scenario = JSON.parse(await fs.readFile(inputPath, "utf-8"));
  const rankedObservations = [...scenario.observation_points].sort(
    (left, right) => totalVolume(right) - totalVolume(left) || left.id.localeCompare(right.id)
  );

  const selectedObservations = rankedObservations.slice(options.startRank, options.startRank + options.count);
  scenario.observation_points = selectedObservations;
  scenario.meta = {
    ...scenario.meta,
    scenario_id: options.scenarioId ?? scenario.meta?.scenario_id ?? null,
    scenario_name: options.scenarioName ?? scenario.meta?.scenario_name ?? null,
    subset_selection: {
      start_rank: options.startRank,
      count: selectedObservations.length,
      volume_rank_order: "desc"
    },
    summary: {
      node_count: scenario.graph.nodes.length,
      way_count: scenario.graph.ways.length,
      observation_point_count: selectedObservations.length,
      request_record_count: selectedObservations.reduce(
        (sum, observationPoint) => sum + observationPoint.traffic_volume.length,
        0
      ),
      total_target_count: selectedObservations.reduce(
        (sum, observationPoint) => sum + totalVolume(observationPoint),
        0
      )
    }
  };

  await fs.writeFile(outputPath, JSON.stringify(scenario));
  console.log(JSON.stringify({
    output: path.relative(process.cwd(), outputPath),
    observation_point_count: scenario.meta.summary.observation_point_count,
    request_record_count: scenario.meta.summary.request_record_count,
    total_target_count: scenario.meta.summary.total_target_count
  }, null, 2));
}

function totalVolume(observationPoint) {
  return observationPoint.traffic_volume.reduce(
    (sum, record) => sum + record.volume_5min,
    0
  );
}

function parseOptions(args) {
  const options = {
    input: DEFAULT_INPUT_PATH,
    output: DEFAULT_OUTPUT_PATH,
    startRank: 0,
    count: 100,
    scenarioId: null,
    scenarioName: null
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
    } else if (name === "--start-rank") {
      options.startRank = Number(value);
      index += 1;
    } else if (name === "--count") {
      options.count = Number(value);
      index += 1;
    } else if (name === "--scenario-id") {
      options.scenarioId = value;
      index += 1;
    } else if (name === "--scenario-name") {
      options.scenarioName = value;
      index += 1;
    }
  }

  if (!Number.isInteger(options.startRank) || options.startRank < 0) {
    throw new Error("--start-rank は 0 以上の整数にしてください。");
  }

  if (!Number.isInteger(options.count) || options.count <= 0) {
    throw new Error("--count は 1 以上の整数にしてください。");
  }

  return options;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

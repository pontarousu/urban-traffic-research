import fs from "node:fs/promises";
import path from "node:path";
import {
  createSimulationRuntime,
  stepSimulation
} from "./sim_core.mjs";

async function main() {
  const scenarios = [
    ["single_way_single_obs", "inverse_traffic_simulator/data/scenarios/single_way_single_obs.json", 40],
    ["branch_choice", "inverse_traffic_simulator/data/scenarios/branch_choice.json", 50],
    ["chain_two_obs", "inverse_traffic_simulator/data/scenarios/chain_two_obs.json", 80],
    ["failure_recovery", "inverse_traffic_simulator/data/scenarios/failure_recovery.json", 90],
    ["branch_merge", "inverse_traffic_simulator/data/scenarios/branch_merge.json", 90],
    ["dense_junction", "inverse_traffic_simulator/data/scenarios/dense_junction.json", 80]
  ];

  for (const [label, scenarioRelativePath, steps] of scenarios) {
    await runScenario(label, scenarioRelativePath, steps);
  }
}

async function runScenario(label, scenarioRelativePath, steps) {
  const scenarioPath = path.resolve(scenarioRelativePath);
  const scenario = JSON.parse(await fs.readFile(scenarioPath, "utf-8"));
  const runtime = createSimulationRuntime(scenario);

  for (let stepIndex = 0; stepIndex < steps; stepIndex += 1) {
    stepSimulation(scenario, runtime);
  }

  console.log(`\n=== ${label} ===`);
  console.log(`now_min: ${runtime.now_min.toFixed(4)}`);
  console.log(`cars_total: ${runtime.cars.length}`);
  console.log(`cars_active: ${runtime.cars.filter((car) => car.status === "active").length}`);
  console.log("request_windows:");
  runtime.request_windows.forEach((requestWindow) => {
    console.log({
      id: requestWindow.id,
      time_min: requestWindow.time_min,
      target_count: requestWindow.target_count,
      assigned_count: requestWindow.assigned_count,
      reserved_count: requestWindow.reserved_count,
      failed_count: requestWindow.failed_count
    });
  });

  const eventCounts = runtime.event_counters ?? new Map();
  console.log("event_counts:", Object.fromEntries(eventCounts.entries()));
  console.log(`failed_events: ${eventCounts.get("request_failed") ?? 0}`);
  console.log("recent_events:");
  runtime.event_logs.slice(-10).forEach((event) => {
    console.log(event);
  });
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

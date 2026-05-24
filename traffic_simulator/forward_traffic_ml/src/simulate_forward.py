#!/usr/bin/env python3
"""順方向交通シミュレーションを実行する。"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from branch_policy import BranchPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "data/processed/small_forward_dataset.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results/simulation_counts.csv"
DEFAULT_TRACE_OUTPUT_PATH = PROJECT_ROOT / "results/simulation_traces.json"


@dataclass
class Vehicle:
    """道路上を前進する車両の状態を持つ。"""

    vehicle_id: int
    way_id: str
    position_meter: float
    birth_time_sec: int
    source_way_id: str
    source_category: str
    branch_trace: list[dict[str, Any]] = field(default_factory=list)
    observation_trace: list[dict[str, Any]] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="順方向シミュレーションを実行します。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--trace-output", type=Path, default=DEFAULT_TRACE_OUTPUT_PATH)
    parser.add_argument("--theta-input", type=Path, default=None)
    parser.add_argument("--theta-output", type=Path, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--time-step-sec", type=int, default=1)
    parser.add_argument("--min-branch-probability", type=float, default=0.02)
    parser.add_argument("--epsilon", type=float, default=0.0)
    parser.add_argument("--active-cap-multiplier", type=float, default=1.0)
    return parser.parse_args()


def load_dataset(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def choose_weighted(items: list[dict[str, Any]], rng: random.Random) -> dict[str, Any] | None:
    if not items:
        return None
    total = sum(max(0.0, float(item.get("weight", 1.0))) for item in items)
    if total <= 0:
        return rng.choice(items)
    threshold = rng.random() * total
    current = 0.0
    for item in items:
        current += max(0.0, float(item.get("weight", 1.0)))
        if current >= threshold:
            return item
    return items[-1]


def way_speed_meter_per_sec(way: dict[str, Any], current_car_count: int = 0) -> float:
    speed_kmh = float(way.get("speed_limit_kmh") or 30.0)
    capacity = max(1, int(way.get("storage_capacity_cars") or 10))
    occupancy_ratio = max(0.0, current_car_count / capacity)
    current_speed_kmh = speed_kmh / (1.0 + 2.0 * (occupancy_ratio ** 4.0))
    current_speed_kmh = max(3.0, current_speed_kmh)
    return current_speed_kmh * 1000.0 / 3600.0


def target_active_lookup(calibration: dict[str, Any]) -> dict[int, int]:
    return {
        int(item["time_min"]): int(item["target_active_cars"])
        for item in calibration.get("demand_profile", [])
    }


def build_observation_index(observations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by_way: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        by_way[observation["matched_way_id"]].append(observation)
    return by_way


def record_crossing(
    vehicle: Vehicle,
    counts: dict[tuple[int, str], int],
    observations_by_way: dict[str, list[dict[str, Any]]],
    way: dict[str, Any],
    previous_position: float,
    next_position: float,
    time_sec: int,
    time_min: int,
) -> None:
    way_length = max(1.0, float(way.get("length_meter") or 1.0))
    for observation in observations_by_way.get(way["id"], []):
        ratio = float(observation.get("matched_position_ratio") or 0.5)
        target_position = way_length * min(1.0, max(0.0, ratio))
        if previous_position <= target_position < next_position:
            bin_min = (time_min // 5) * 5
            counts[(bin_min, observation["id"])] += 1
            vehicle.observation_trace.append(
                {
                    "time_sec": time_sec,
                    "time_min": time_min,
                    "bin_min": bin_min,
                    "obs_id": observation["id"],
                    "way_id": way["id"],
                }
            )


def choose_source_way(calibration: dict[str, Any], rng: random.Random) -> tuple[str, str] | None:
    source_candidates = calibration.get("source_candidates", {})
    ratios = source_candidates.get("category_ratios", {})
    categories = source_candidates.get("categories", {})
    ratio_items = [{"category": key, "weight": value} for key, value in ratios.items()]
    category_item = choose_weighted(ratio_items, rng)
    if not category_item:
        return None
    category = category_item["category"]
    source_item = choose_weighted(categories.get(category, []), rng)
    if source_item:
        return category, source_item.get("way_id")

    legacy_source_way_ids = calibration.get("source_way_ids", [])
    if legacy_source_way_ids:
        return "legacy", rng.choice(legacy_source_way_ids)
    return None


def spawn_to_target(
    active: list[Vehicle],
    way_vehicle_count: dict[str, int],
    ways_by_id: dict[str, dict[str, Any]],
    calibration: dict[str, Any],
    rng: random.Random,
    target_active_cars: int,
    next_vehicle_id: int,
    time_sec: int,
    spawn_stats_by_category: dict[str, int],
    spawn_stats_by_way: dict[str, int],
) -> tuple[int, int]:
    spawn_count = max(0, target_active_cars - len(active))
    spawned = 0
    for _ in range(spawn_count):
        source = choose_source_way(calibration, rng)
        if not source:
            break
        source_category, way_id = source
        way = ways_by_id.get(way_id)
        if not way:
            continue
        active.append(Vehicle(next_vehicle_id, way_id, 0.0, time_sec, way_id, source_category))
        way_vehicle_count[way_id] += 1
        spawn_stats_by_category[source_category] += 1
        spawn_stats_by_way[way_id] += 1
        next_vehicle_id += 1
        spawned += 1
    return next_vehicle_id, spawned


def remove_excess_vehicles(
    active: list[Vehicle],
    way_vehicle_count: dict[str, int],
    target_active_cars: int,
    completed_traces: list[dict[str, Any]],
    time_sec: int,
) -> int:
    remove_count = max(0, len(active) - target_active_cars)
    if remove_count == 0:
        return 0

    # 観測点をまだ通っていない車、かつ長く残っている車から優先して整理する。
    active.sort(key=lambda vehicle: (len(vehicle.observation_trace) > 0, -len(vehicle.branch_trace), vehicle.birth_time_sec))
    removed = active[:remove_count]
    del active[:remove_count]
    for vehicle in removed:
        way_vehicle_count[vehicle.way_id] = max(0, way_vehicle_count[vehicle.way_id] - 1)
        completed_traces.append(vehicle_to_trace(vehicle, "active_cap_removed", time_sec))
    return len(removed)


def vehicle_to_trace(vehicle: Vehicle, final_status: str, final_time_sec: int) -> dict[str, Any]:
    return {
        "vehicle_id": vehicle.vehicle_id,
        "birth_time_sec": vehicle.birth_time_sec,
        "final_time_sec": final_time_sec,
        "final_status": final_status,
        "source_way_id": vehicle.source_way_id,
        "source_category": vehicle.source_category,
        "branch_trace": vehicle.branch_trace,
        "observation_trace": vehicle.observation_trace,
    }


def run_simulation(
    dataset: dict[str, Any],
    seed: int,
    time_step_sec: int,
    policy: BranchPolicy | None = None,
    active_cap_multiplier: float = 1.0,
) -> dict[str, Any]:
    rng = random.Random(seed)
    ways = dataset["graph"]["ways"]
    ways_by_id = {way["id"]: way for way in ways}
    observations_by_way = build_observation_index(dataset["observations"])
    calibration = dataset["calibration"]
    target_by_time = target_active_lookup(calibration)
    policy = policy or BranchPolicy.from_dataset(dataset)

    start_min = int(dataset["meta"]["start_min"])
    end_min = int(dataset["meta"]["end_min"])
    total_seconds = (end_min - start_min) * 60

    active: list[Vehicle] = []
    completed_traces: list[dict[str, Any]] = []
    way_vehicle_count: dict[str, int] = defaultdict(int)
    counts: dict[tuple[int, str], int] = defaultdict(int)
    next_vehicle_id = 1
    total_spawned = 0
    total_removed = 0
    active_count_samples: list[int] = []
    spawn_stats_by_category: dict[str, int] = defaultdict(int)
    spawn_stats_by_way: dict[str, int] = defaultdict(int)

    for elapsed_sec in range(0, total_seconds, time_step_sec):
        current_time_sec = elapsed_sec
        current_min_float = start_min + elapsed_sec / 60.0
        current_min = int(current_min_float)
        bin_min = (current_min // 5) * 5

        if elapsed_sec % 300 == 0:
            target_active_cars = target_by_time.get(bin_min, len(active))
            active_cap = round(target_active_cars * max(1.0, active_cap_multiplier))
            removed = remove_excess_vehicles(active, way_vehicle_count, active_cap, completed_traces, current_time_sec)
            total_removed += removed
            next_vehicle_id, spawned = spawn_to_target(
                active=active,
                way_vehicle_count=way_vehicle_count,
                ways_by_id=ways_by_id,
                calibration=calibration,
                rng=rng,
                target_active_cars=target_active_cars,
                next_vehicle_id=next_vehicle_id,
                time_sec=current_time_sec,
                spawn_stats_by_category=spawn_stats_by_category,
                spawn_stats_by_way=spawn_stats_by_way,
            )
            total_spawned += spawned

        remaining: list[Vehicle] = []
        for vehicle in active:
            way = ways_by_id[vehicle.way_id]
            previous_position = vehicle.position_meter
            next_position = previous_position + way_speed_meter_per_sec(way, way_vehicle_count[vehicle.way_id]) * time_step_sec
            record_crossing(
                vehicle,
                counts,
                observations_by_way,
                way,
                previous_position,
                next_position,
                current_time_sec,
                current_min,
            )

            way_length = float(way.get("length_meter") or 1.0)
            if next_position < way_length:
                vehicle.position_meter = next_position
                remaining.append(vehicle)
                continue

            way_vehicle_count[vehicle.way_id] = max(0, way_vehicle_count[vehicle.way_id] - 1)
            node_id = way["to_node_id"]
            next_way_id = policy.choose(node_id, way["id"], rng)
            if not next_way_id:
                completed_traces.append(vehicle_to_trace(vehicle, "no_next_way", current_time_sec))
                continue
            next_way = ways_by_id[next_way_id]

            vehicle.branch_trace.append(
                {
                    "time_sec": current_time_sec,
                    "time_min": current_min,
                    "node_id": node_id,
                    "incoming_way_id": way["id"],
                    "outgoing_way_id": next_way_id,
                }
            )
            overflow_position = max(0.0, next_position - way_length)
            vehicle.way_id = next_way_id
            vehicle.position_meter = min(overflow_position, float(next_way.get("length_meter") or 1.0))
            way_vehicle_count[next_way_id] += 1
            remaining.append(vehicle)
        active = remaining
        active_count_samples.append(len(active))

    for vehicle in active:
        completed_traces.append(vehicle_to_trace(vehicle, "simulation_end", total_seconds))

    return {
        "counts": counts,
        "vehicle_traces": completed_traces,
        "summary": {
            "spawned_count": total_spawned,
            "removed_count": total_removed,
            "active_car_count_avg": sum(active_count_samples) / len(active_count_samples) if active_count_samples else 0.0,
            "active_car_count_max": max(active_count_samples) if active_count_samples else 0,
            "vehicle_trace_count": len(completed_traces),
            "spawn_stats_by_category": dict(spawn_stats_by_category),
            "spawn_stats_by_way": dict(spawn_stats_by_way),
            "active_cap_multiplier": active_cap_multiplier,
        },
    }


def write_counts(dataset: dict[str, Any], counts: dict[tuple[int, str], int], output_path: Path) -> None:
    start_min = int(dataset["meta"]["start_min"])
    end_min = int(dataset["meta"]["end_min"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["time_min", "obs_id", "point_number", "point_name", "matched_way_id", "simulated_count_5min"],
        )
        writer.writeheader()
        for time_min in range(start_min, end_min, 5):
            for observation in dataset["observations"]:
                writer.writerow(
                    {
                        "time_min": time_min,
                        "obs_id": observation["id"],
                        "point_number": observation.get("point_number"),
                        "point_name": observation.get("point_name"),
                        "matched_way_id": observation["matched_way_id"],
                        "simulated_count_5min": counts.get((time_min, observation["id"]), 0),
                    }
                )


def write_traces(vehicle_traces: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump({"schema_version": "0.1", "vehicle_traces": vehicle_traces}, file, ensure_ascii=False, indent=2)


def main() -> None:
    args = parse_args()
    dataset = load_dataset(args.input)
    if args.theta_input and args.theta_input.exists():
        policy = BranchPolicy.load(args.theta_input, dataset)
    else:
        policy = BranchPolicy.from_dataset(dataset, args.min_branch_probability, args.epsilon)
    policy.epsilon = args.epsilon
    result = run_simulation(dataset, args.seed, args.time_step_sec, policy, args.active_cap_multiplier)
    write_counts(dataset, result["counts"], args.output)
    write_traces(result["vehicle_traces"], args.trace_output)
    if args.theta_output:
        policy.save(args.theta_output)
    print(f"出力: {args.output}")
    print(f"trace出力: {args.trace_output}")
    print(f"発生台数: {result['summary']['spawned_count']}")
    print(f"整理台数: {result['summary']['removed_count']}")


if __name__ == "__main__":
    main()

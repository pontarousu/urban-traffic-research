#!/usr/bin/env python3
"""発生地点から最初の観測点までの走行距離・時間を集計する。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import median
from typing import Any

from road_db_network_loader import DEFAULT_SNAPSHOT_DIR, RoadDbNetwork


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE_PATH = PROJECT_ROOT / "results/road_db_phase3_upstream_300_1000_diagnostics/vehicle_traces.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results/road_db_phase3_upstream_300_1000_diagnostics/source_to_first_observation.csv"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "results/road_db_phase3_upstream_300_1000_diagnostics/source_to_first_observation_summary.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--traces", type=Path, default=DEFAULT_TRACE_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_PATH)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    """JSONを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    """診断を実行する。"""

    args = parse_args()
    network = RoadDbNetwork.load(args.snapshot_dir)
    traces = load_json(args.traces)["vehicle_traces"]
    rows = [build_vehicle_row(network, trace) for trace in traces]
    write_rows(rows, args.output)
    summary = summarize(rows)
    write_summary(summary, args.summary_output)
    print(f"出力: {args.output}")
    print(f"summary出力: {args.summary_output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_vehicle_row(network: RoadDbNetwork, trace: dict[str, Any]) -> dict[str, Any]:
    """1台ぶんの発生地点から初回観測点までの診断行を作る。"""

    first_observation = first_observation_trace(trace)
    distance = None
    time_sec = None
    if first_observation:
        distance = source_to_observation_distance(network, trace, first_observation)
        time_sec = int(first_observation["time_sec"]) - int(trace["birth_time_sec"])

    return {
        "vehicle_id": trace["vehicle_id"],
        "source_edge_id": trace["source_edge_id"],
        "source_category": trace.get("source_category"),
        "birth_time_sec": trace["birth_time_sec"],
        "final_time_sec": trace["final_time_sec"],
        "final_status": trace["final_status"],
        "branch_trace_count": len(trace.get("branch_trace", [])),
        "observation_trace_count": len(trace.get("observation_trace", [])),
        "first_observation_id": first_observation.get("observation_id") if first_observation else None,
        "first_observation_time_sec": first_observation.get("time_sec") if first_observation else None,
        "source_to_first_observation_time_sec": time_sec,
        "source_to_first_observation_distance_meter": distance,
    }


def first_observation_trace(trace: dict[str, Any]) -> dict[str, Any] | None:
    """最初の観測点通過traceを返す。"""

    observations = trace.get("observation_trace", [])
    if not observations:
        return None
    return min(observations, key=lambda item: int(item["time_sec"]))


def source_to_observation_distance(
    network: RoadDbNetwork,
    trace: dict[str, Any],
    observation: dict[str, Any],
) -> float | None:
    """発生edge始点から観測点までの概算走行距離を返す。"""

    observation_edge_id = observation["directed_edge_id"]
    observation_position = network.edge_length(observation_edge_id) * float(observation.get("position_ratio") or 0.5)
    current_edge_id = trace["source_edge_id"]
    distance = 0.0
    if current_edge_id == observation_edge_id:
        return round(observation_position, 3)

    observation_time = int(observation["time_sec"])
    for branch in sorted(trace.get("branch_trace", []), key=lambda item: int(item["time_sec"])):
        if int(branch["time_sec"]) > observation_time:
            break
        distance += network.edge_length(current_edge_id)
        current_edge_id = branch["outgoing_directed_edge_id"]
        if current_edge_id == observation_edge_id:
            return round(distance + observation_position, 3)
    return None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """診断サマリを作る。"""

    with_observation = [row for row in rows if row["first_observation_id"]]
    distance_values = [
        float(row["source_to_first_observation_distance_meter"])
        for row in with_observation
        if row["source_to_first_observation_distance_meter"] is not None
    ]
    time_values = [
        float(row["source_to_first_observation_time_sec"])
        for row in with_observation
        if row["source_to_first_observation_time_sec"] is not None
    ]
    return {
        "vehicle_count": len(rows),
        "vehicles_with_observation": len(with_observation),
        "vehicles_with_distance": len(distance_values),
        "observation_reach_ratio": len(with_observation) / len(rows) if rows else None,
        "distance_mean": mean_or_none(distance_values),
        "distance_median": median(distance_values) if distance_values else None,
        "distance_p90": percentile(distance_values, 0.9),
        "distance_max": max(distance_values) if distance_values else None,
        "time_mean": mean_or_none(time_values),
        "time_median": median(time_values) if time_values else None,
        "time_p90": percentile(time_values, 0.9),
        "time_max": max(time_values) if time_values else None,
    }


def write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    """診断CSVを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(summary: dict[str, Any], path: Path) -> None:
    """診断サマリJSONを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)


def mean_or_none(values: list[float]) -> float | None:
    """平均値を返す。"""

    if not values:
        return None
    return sum(values) / len(values)


def percentile(values: list[float], ratio: float) -> float | None:
    """単純なパーセンタイルを返す。"""

    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


if __name__ == "__main__":
    main()

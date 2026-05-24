#!/usr/bin/env python3
"""道路DBベースの順方向シミュレーションを実行する。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from road_db_forward_simulator import run_road_db_simulation
from road_db_network_loader import (
    DEFAULT_OBSERVATION_ALIGNMENT_PATH,
    DEFAULT_SNAPSHOT_DIR,
    build_source_candidates,
    load_observation_matches,
    RoadDbNetwork,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/road_db_phase3"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--observation-alignment", type=Path, default=DEFAULT_OBSERVATION_ALIGNMENT_PATH)
    parser.add_argument("--scenario", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-min", type=int, default=480)
    parser.add_argument("--duration-min", type=int, default=15)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--time-step-sec", type=int, default=5)
    parser.add_argument("--generation-multiplier", type=float, default=0.05)
    parser.add_argument("--max-spawn-per-bin", type=int, default=300)
    parser.add_argument("--max-active-vehicles", type=int, default=1200)
    parser.add_argument("--max-vehicle-age-sec", type=int, default=1800)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--spawn-timing", choices=["batch", "distributed"], default="distributed")
    parser.add_argument("--source-mode", choices=["major", "matched_edges", "mixed", "observation_upstream"], default="mixed")
    parser.add_argument("--upstream-min-distance-meter", type=float, default=80.0)
    parser.add_argument("--upstream-max-distance-meter", type=float, default=450.0)
    parser.add_argument("--upstream-max-candidates-per-observation", type=int, default=12)
    parser.add_argument("--include-low-confidence", action="store_true")
    return parser.parse_args()


def write_counts(
    *,
    observations: list[Any],
    counts: dict[tuple[int, str], int],
    output_path: Path,
    start_min: int,
    duration_min: int,
) -> None:
    """観測点別・5分別のシミュレーション台数をCSVへ出す。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "time_min",
                "observation_id",
                "point_number",
                "point_name",
                "directed_edge_id",
                "match_method",
                "match_confidence",
                "observed_count_5min",
                "simulated_count_5min",
            ],
        )
        writer.writeheader()
        for time_min in range(start_min, start_min + duration_min, 5):
            for observation in observations:
                writer.writerow(
                    {
                        "time_min": time_min,
                        "observation_id": observation.observation_id,
                        "point_number": observation.point_number,
                        "point_name": observation.point_name,
                        "directed_edge_id": observation.directed_edge_id,
                        "match_method": observation.match_method,
                        "match_confidence": observation.match_confidence,
                        "observed_count_5min": observation.observed_volume_5min.get(time_min, 0),
                        "simulated_count_5min": counts.get((time_min, observation.observation_id), 0),
                    }
                )


def write_traces(vehicle_traces: list[dict[str, Any]], output_path: Path) -> None:
    """車両 trace をJSONへ出す。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "schema_version": "road_db_vehicle_traces.v1",
                "vehicle_traces": vehicle_traces,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )


def write_summary(summary: dict[str, Any], output_path: Path) -> None:
    """実行サマリをJSONへ出す。"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)


def main() -> None:
    """シミュレーションを実行する。"""

    args = parse_args()
    network = RoadDbNetwork.load(args.snapshot_dir)
    observations = load_observation_matches(
        alignment_path=args.observation_alignment,
        scenario_path=args.scenario,
        start_min=args.start_min,
        duration_min=args.duration_min,
        include_low_confidence=args.include_low_confidence,
    )
    source_candidates = build_source_candidates(
        network,
        observations,
        args.source_mode,
        upstream_min_distance_meter=args.upstream_min_distance_meter,
        upstream_max_distance_meter=args.upstream_max_distance_meter,
        upstream_max_candidates_per_observation=args.upstream_max_candidates_per_observation,
    )
    result = run_road_db_simulation(
        network=network,
        observations=observations,
        source_candidates=source_candidates,
        start_min=args.start_min,
        duration_min=args.duration_min,
        seed=args.seed,
        time_step_sec=args.time_step_sec,
        generation_multiplier=args.generation_multiplier,
        max_spawn_per_bin=args.max_spawn_per_bin,
        max_active_vehicles=args.max_active_vehicles,
        max_vehicle_age_sec=args.max_vehicle_age_sec,
        epsilon=args.epsilon,
        spawn_timing=args.spawn_timing,
    )

    counts_path = args.output_dir / "simulation_counts.csv"
    traces_path = args.output_dir / "vehicle_traces.json"
    summary_path = args.output_dir / "simulation_summary.json"
    write_counts(
        observations=observations,
        counts=result["counts"],
        output_path=counts_path,
        start_min=args.start_min,
        duration_min=args.duration_min,
    )
    write_traces(result["vehicle_traces"], traces_path)
    summary = {
        **result["summary"],
        "snapshot_dir": str(args.snapshot_dir),
        "observation_alignment": str(args.observation_alignment),
        "source_mode": args.source_mode,
        "spawn_timing": args.spawn_timing,
        "upstream_min_distance_meter": args.upstream_min_distance_meter,
        "upstream_max_distance_meter": args.upstream_max_distance_meter,
        "upstream_max_candidates_per_observation": args.upstream_max_candidates_per_observation,
        "observation_count": len(observations),
        "source_candidate_count": len(source_candidates),
        "counts_csv": str(counts_path),
        "traces_json": str(traces_path),
    }
    write_summary(summary, summary_path)
    print(f"counts出力: {counts_path}")
    print(f"trace出力: {traces_path}")
    print(f"summary出力: {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

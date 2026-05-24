#!/usr/bin/env python3
"""分岐確率 theta を反復更新する学習実験を実行する。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from branch_policy import BranchPolicy
from compare_observed import build_rows, summarize, write_rows
from feedback_trainer import update_policy_from_traces
from simulate_forward import load_dataset, run_simulation, write_counts


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "data/processed/small_forward_dataset.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/training"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="分岐確率 theta の反復補正を実行します。")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--time-step-sec", type=int, default=1)
    parser.add_argument("--epsilon", type=float, default=0.0)
    parser.add_argument("--active-cap-multiplier", type=float, default=1.0)
    return parser.parse_args()


def write_metrics(metrics: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "iteration",
        "observed_total",
        "simulated_total",
        "mae",
        "rmse",
        "bias",
        "mape",
        "correlation",
        "improvement_from_baseline",
        "spawned_count",
        "removed_count",
        "active_car_count_avg",
        "active_car_count_max",
        "updated_branch_count",
        "max_abs_delta_theta",
    ]
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(metrics)


def counts_to_plain(counts: dict[tuple[int, str], int]) -> dict[str, int]:
    return {f"{time_min}|{obs_id}": count for (time_min, obs_id), count in counts.items()}


def main() -> None:
    args = parse_args()
    dataset = load_dataset(args.dataset)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    policy = BranchPolicy.from_dataset(dataset, epsilon=args.epsilon)
    metrics: list[dict[str, Any]] = []
    baseline_mae: float | None = None
    final_rows: list[dict[str, Any]] = []
    final_result: dict[str, Any] | None = None

    for iteration in range(args.iterations):
        policy.epsilon = args.epsilon
        result = run_simulation(dataset, args.seed + iteration, args.time_step_sec, policy, args.active_cap_multiplier)
        rows = build_rows(dataset, result["counts"])
        summary = summarize(rows)
        if baseline_mae is None:
            baseline_mae = float(summary["mae"] or 0.0)
        improvement = 0.0
        if baseline_mae:
            improvement = (baseline_mae - float(summary["mae"] or 0.0)) / baseline_mae

        update_summary = update_policy_from_traces(
            policy=policy,
            dataset=dataset,
            simulated_counts=result["counts"],
            vehicle_traces=result["vehicle_traces"],
        )

        metrics.append(
            {
                "iteration": iteration,
                "observed_total": summary["observed_total"],
                "simulated_total": summary["simulated_total"],
                "mae": summary["mae"],
                "rmse": summary["rmse"],
                "bias": summary["bias"],
                "mape": summary["mape"],
                "correlation": summary["correlation"],
                "improvement_from_baseline": improvement,
                "spawned_count": result["summary"]["spawned_count"],
                "removed_count": result["summary"]["removed_count"],
                "active_car_count_avg": result["summary"]["active_car_count_avg"],
                "active_car_count_max": result["summary"]["active_car_count_max"],
                "updated_branch_count": update_summary["updated_branch_count"],
                "max_abs_delta_theta": update_summary["max_abs_delta_theta"],
            }
        )

        final_rows = rows
        final_result = result
        print(
            f"iteration={iteration} "
            f"mae={summary['mae']:.3f} "
            f"rmse={summary['rmse']:.3f} "
            f"sim_total={summary['simulated_total']} "
            f"updates={update_summary['updated_branch_count']}"
        )

    write_metrics(metrics, output_dir / "iteration_metrics.csv")
    policy.save(output_dir / "final_branch_theta.json")
    if final_result is not None:
        write_counts(dataset, final_result["counts"], output_dir / "final_simulation_counts.csv")
        write_rows(final_rows, output_dir / "final_comparison.csv")
        with (output_dir / "final_traces.json").open("w", encoding="utf-8") as file:
            json.dump(
                {
                    "schema_version": "0.1",
                    "counts": counts_to_plain(final_result["counts"]),
                    "summary": final_result["summary"],
                    "vehicle_traces": final_result["vehicle_traces"],
                },
                file,
                ensure_ascii=False,
                indent=2,
            )
    print(f"学習結果出力: {output_dir}")


if __name__ == "__main__":
    main()

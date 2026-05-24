#!/usr/bin/env python3
"""順方向シミュレーション結果と観測交通量を比較する。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "data/processed/small_forward_dataset.json"
DEFAULT_SIMULATION_PATH = PROJECT_ROOT / "results/simulation_counts.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results/comparison.csv"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="観測値とシミュレーション結果を比較します。")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--simulation", type=Path, default=DEFAULT_SIMULATION_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def load_dataset(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_simulation_counts(path: Path) -> dict[tuple[int, str], int]:
    counts: dict[tuple[int, str], int] = {}
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            counts[(int(row["time_min"]), row["obs_id"])] = int(row["simulated_count_5min"])
    return counts


def correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance_x = sum((x - mean_x) ** 2 for x in xs)
    variance_y = sum((y - mean_y) ** 2 for y in ys)
    denominator = math.sqrt(variance_x * variance_y)
    if denominator == 0:
        return None
    return numerator / denominator


def build_rows(dataset: dict[str, Any], simulated: dict[tuple[int, str], int]) -> list[dict[str, Any]]:
    start_min = int(dataset["meta"]["start_min"])
    end_min = int(dataset["meta"]["end_min"])
    rows = []
    for time_min in range(start_min, end_min, 5):
        for observation in dataset["observations"]:
            observed = int(observation.get("observed_volume_5min", {}).get(str(time_min), 0))
            simulated_count = int(simulated.get((time_min, observation["id"]), 0))
            error = simulated_count - observed
            rows.append(
                {
                    "time_min": time_min,
                    "obs_id": observation["id"],
                    "point_number": observation.get("point_number"),
                    "point_name": observation.get("point_name"),
                    "matched_way_id": observation["matched_way_id"],
                    "observed_count_5min": observed,
                    "simulated_count_5min": simulated_count,
                    "error": error,
                    "absolute_error": abs(error),
                }
            )
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, float | int | None]:
    observed = [float(row["observed_count_5min"]) for row in rows]
    simulated = [float(row["simulated_count_5min"]) for row in rows]
    errors = [sim - obs for sim, obs in zip(simulated, observed)]
    absolute_errors = [abs(error) for error in errors]
    squared_errors = [error * error for error in errors]
    nonzero_pairs = [(obs, sim) for obs, sim in zip(observed, simulated) if obs > 0]
    mape = None
    if nonzero_pairs:
        mape = sum(abs(sim - obs) / obs for obs, sim in nonzero_pairs) / len(nonzero_pairs)
    return {
        "row_count": len(rows),
        "observed_total": int(sum(observed)),
        "simulated_total": int(sum(simulated)),
        "bias": sum(errors) / len(errors) if errors else None,
        "mae": sum(absolute_errors) / len(absolute_errors) if absolute_errors else None,
        "rmse": math.sqrt(sum(squared_errors) / len(squared_errors)) if squared_errors else None,
        "mape": mape,
        "correlation": correlation(observed, simulated),
    }


def write_rows(rows: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "time_min",
                "obs_id",
                "point_number",
                "point_name",
                "matched_way_id",
                "observed_count_5min",
                "simulated_count_5min",
                "error",
                "absolute_error",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    dataset = load_dataset(args.dataset)
    simulated = load_simulation_counts(args.simulation)
    rows = build_rows(dataset, simulated)
    write_rows(rows, args.output)
    summary = summarize(rows)

    print(f"出力: {args.output}")
    print(f"比較行数: {summary['row_count']}")
    print(f"観測合計: {summary['observed_total']}")
    print(f"シミュレーション合計: {summary['simulated_total']}")
    print(f"MAE: {summary['mae']:.3f}")
    print(f"RMSE: {summary['rmse']:.3f}")
    print(f"Bias: {summary['bias']:.3f}")
    if summary["mape"] is not None:
        print(f"MAPE: {summary['mape']:.3f}")
    if summary["correlation"] is not None:
        print(f"Correlation: {summary['correlation']:.3f}")


if __name__ == "__main__":
    main()

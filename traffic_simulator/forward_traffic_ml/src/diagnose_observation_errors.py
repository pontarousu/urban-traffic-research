#!/usr/bin/env python3
"""観測値とシミュレーション値の誤差を診断する。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COMPARISON_PATH = (
    PROJECT_ROOT
    / "results/road_db_training_mesh_uniform_500_g150_packet5_iter40_eval5"
    / "iteration_020/evaluation/comparison.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/observation_error_diagnostics"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--top-n", type=int, default=50)
    return parser.parse_args()


def main() -> None:
    """誤差診断を実行する。"""

    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = load_comparison_rows(args.comparison)
    observation_rows = aggregate_by_observation(rows)
    time_rows = aggregate_by_time(rows)
    summary = build_summary(rows, observation_rows, time_rows, args)

    write_rows(observation_rows, args.output_dir / "observation_error_by_point.csv")
    write_rows(time_rows, args.output_dir / "observation_error_by_time.csv")
    write_rows(sort_top_under(observation_rows, args.top_n), args.output_dir / "top_under_observed_points.csv")
    write_rows(sort_top_over(observation_rows, args.top_n), args.output_dir / "top_over_observed_points.csv")
    write_rows(sort_top_abs(observation_rows, args.top_n), args.output_dir / "top_absolute_error_points.csv")
    write_json(summary, args.output_dir / "error_diagnostics_summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def load_comparison_rows(path: Path) -> list[dict[str, Any]]:
    """comparison CSVを読む。"""

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            observed = int(float(row["observed_count_5min"]))
            simulated = int(float(row["simulated_count_5min"]))
            error = simulated - observed
            rows.append(
                {
                    **row,
                    "time_min": int(row["time_min"]),
                    "observed_count_5min": observed,
                    "simulated_count_5min": simulated,
                    "error": error,
                    "absolute_error": abs(error),
                }
            )
    return rows


def aggregate_by_observation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """観測点別に誤差を集計する。"""

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["observation_id"]].append(row)

    output: list[dict[str, Any]] = []
    for observation_id, values in groups.items():
        first = values[0]
        observed_total = sum(int(row["observed_count_5min"]) for row in values)
        simulated_total = sum(int(row["simulated_count_5min"]) for row in values)
        error_total = simulated_total - observed_total
        absolute_error_total = sum(abs(int(row["error"])) for row in values)
        hit_bin_count = sum(1 for row in values if int(row["simulated_count_5min"]) > 0)
        observed_bin_count = sum(1 for row in values if int(row["observed_count_5min"]) > 0)
        output.append(
            {
                "observation_id": observation_id,
                "point_number": first.get("point_number"),
                "point_name": first.get("point_name"),
                "directed_edge_id": first.get("directed_edge_id"),
                "match_confidence": first.get("match_confidence"),
                "observed_total": observed_total,
                "simulated_total": simulated_total,
                "error_total": error_total,
                "absolute_error_total": absolute_error_total,
                "mae_5min": absolute_error_total / len(values) if values else None,
                "ratio": safe_ratio(simulated_total, observed_total),
                "hit_bin_count": hit_bin_count,
                "observed_bin_count": observed_bin_count,
                "bin_count": len(values),
                "under_count": sum(1 for row in values if int(row["error"]) < 0),
                "over_count": sum(1 for row in values if int(row["error"]) > 0),
                "zero_simulated_count": sum(1 for row in values if int(row["simulated_count_5min"]) == 0),
            }
        )
    output.sort(key=lambda row: abs(float(row["error_total"])), reverse=True)
    return output


def aggregate_by_time(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """5分bin別に誤差を集計する。"""

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[int(row["time_min"])].append(row)

    output: list[dict[str, Any]] = []
    for time_min, values in sorted(groups.items()):
        observed_total = sum(int(row["observed_count_5min"]) for row in values)
        simulated_total = sum(int(row["simulated_count_5min"]) for row in values)
        errors = [int(row["error"]) for row in values]
        output.append(
            {
                "time_min": time_min,
                "observed_total": observed_total,
                "simulated_total": simulated_total,
                "error_total": simulated_total - observed_total,
                "absolute_error_total": sum(abs(error) for error in errors),
                "mae": sum(abs(error) for error in errors) / len(errors) if errors else None,
                "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else None,
                "ratio": safe_ratio(simulated_total, observed_total),
                "hit_rows": sum(1 for row in values if int(row["simulated_count_5min"]) > 0),
                "observed_rows": sum(1 for row in values if int(row["observed_count_5min"]) > 0),
                "under_rows": sum(1 for error in errors if error < 0),
                "over_rows": sum(1 for error in errors if error > 0),
            }
        )
    return output


def build_summary(
    rows: list[dict[str, Any]],
    observation_rows: list[dict[str, Any]],
    time_rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """診断summaryを作る。"""

    observed_total = sum(int(row["observed_count_5min"]) for row in rows)
    simulated_total = sum(int(row["simulated_count_5min"]) for row in rows)
    errors = [int(row["error"]) for row in rows]
    under_rows = [row for row in rows if int(row["error"]) < 0]
    over_rows = [row for row in rows if int(row["error"]) > 0]
    zero_rows = [row for row in rows if int(row["simulated_count_5min"]) == 0]
    under_points = [row for row in observation_rows if int(row["error_total"]) < 0]
    over_points = [row for row in observation_rows if int(row["error_total"]) > 0]
    return {
        "comparison": str(args.comparison),
        "row_count": len(rows),
        "observation_count": len(observation_rows),
        "time_bin_count": len(time_rows),
        "observed_total": observed_total,
        "simulated_total": simulated_total,
        "simulated_total_ratio": safe_ratio(simulated_total, observed_total),
        "error_total": simulated_total - observed_total,
        "mae": sum(abs(error) for error in errors) / len(errors) if errors else None,
        "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)) if errors else None,
        "under_row_count": len(under_rows),
        "over_row_count": len(over_rows),
        "exact_row_count": len(rows) - len(under_rows) - len(over_rows),
        "zero_simulated_row_count": len(zero_rows),
        "under_observation_count": len(under_points),
        "over_observation_count": len(over_points),
        "top_under_total": sum(int(row["error_total"]) for row in sort_top_under(observation_rows, args.top_n)),
        "top_over_total": sum(int(row["error_total"]) for row in sort_top_over(observation_rows, args.top_n)),
        "worst_under_points": sort_top_under(observation_rows, 10),
        "worst_over_points": sort_top_over(observation_rows, 10),
        "worst_time_bins": sorted(time_rows, key=lambda row: abs(float(row["error_total"])), reverse=True)[:8],
    }


def safe_ratio(numerator: float, denominator: float) -> float | None:
    """0除算を避けて比率を返す。"""

    if denominator == 0:
        return None
    return numerator / denominator


def sort_top_under(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """過小推定が大きい順に返す。"""

    return sorted(rows, key=lambda row: float(row["error_total"]))[:limit]


def sort_top_over(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """過大推定が大きい順に返す。"""

    return sorted(rows, key=lambda row: float(row["error_total"]), reverse=True)[:limit]


def sort_top_abs(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """絶対誤差が大きい順に返す。"""

    return sorted(rows, key=lambda row: abs(float(row["error_total"])), reverse=True)[:limit]


def write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    """CSVを書く。"""

    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(data: dict[str, Any], path: Path) -> None:
    """JSONを書く。"""

    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

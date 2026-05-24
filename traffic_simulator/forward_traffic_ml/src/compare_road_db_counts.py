#!/usr/bin/env python3
"""道路DBシミュレーション結果と観測値を比較する。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COUNTS_PATH = PROJECT_ROOT / "results/road_db_phase3/simulation_counts.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "results/road_db_phase3/comparison.csv"
DEFAULT_SUMMARY_PATH = PROJECT_ROOT / "results/road_db_phase3/comparison_summary.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", type=Path, default=DEFAULT_COUNTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_PATH)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict[str, Any]]:
    """counts CSV を比較行として読む。"""

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            observed = int(row["observed_count_5min"])
            simulated = int(row["simulated_count_5min"])
            error = simulated - observed
            rows.append(
                {
                    **row,
                    "observed_count_5min": observed,
                    "simulated_count_5min": simulated,
                    "error": error,
                    "absolute_error": abs(error),
                }
            )
    return rows


def correlation(xs: list[float], ys: list[float]) -> float | None:
    """相関係数を返す。"""

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


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """比較サマリを作る。"""

    observed = [float(row["observed_count_5min"]) for row in rows]
    simulated = [float(row["simulated_count_5min"]) for row in rows]
    errors = [sim - obs for sim, obs in zip(simulated, observed)]
    absolute_errors = [abs(error) for error in errors]
    squared_errors = [error * error for error in errors]
    hit_rows = sum(1 for value in simulated if value > 0)
    observed_rows = sum(1 for value in observed if value > 0)
    return {
        "row_count": len(rows),
        "observed_total": int(sum(observed)),
        "simulated_total": int(sum(simulated)),
        "hit_rows": hit_rows,
        "observed_rows": observed_rows,
        "bias": sum(errors) / len(errors) if errors else None,
        "mae": sum(absolute_errors) / len(absolute_errors) if absolute_errors else None,
        "rmse": math.sqrt(sum(squared_errors) / len(squared_errors)) if squared_errors else None,
        "correlation": correlation(observed, simulated),
    }


def write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    """比較CSVを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(summary: dict[str, Any], path: Path) -> None:
    """比較サマリJSONを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)


def main() -> None:
    """比較を実行する。"""

    args = parse_args()
    rows = load_rows(args.counts)
    summary = summarize(rows)
    write_rows(rows, args.output)
    write_summary(summary, args.summary_output)
    print(f"comparison出力: {args.output}")
    print(f"summary出力: {args.summary_output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

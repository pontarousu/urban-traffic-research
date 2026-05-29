#!/usr/bin/env python3
"""観測点ごとの誤差率分布をSVGとして描画する。"""

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
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/observation_error_distribution_g150_iter40_warmup10"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison", type=Path, default=DEFAULT_COMPARISON_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start-min", type=int, default=490)
    parser.add_argument("--bin-width", type=float, default=0.1)
    parser.add_argument("--min-rate", type=float, default=-1.0)
    parser.add_argument("--max-rate", type=float, default=1.5)
    return parser.parse_args()


def main() -> None:
    """誤差率分布を集計・描画する。"""

    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_rows = [
        row
        for row in load_rows(args.comparison)
        if row["time_min"] >= args.start_min
    ]
    rows = [row for row in all_rows if row["observed"] > 0]
    observation_rows = aggregate_by_observation(rows)
    time_rows = aggregate_by_time(rows)
    row_rate_rows = build_row_rate_rows(rows)
    observation_rates = [row["error_rate"] for row in observation_rows if row["error_rate"] is not None]
    row_rates = [row["error_rate"] for row in row_rate_rows if row["error_rate"] is not None]

    write_rows(observation_rows, args.output_dir / "observation_error_rates.csv")
    write_rows(time_rows, args.output_dir / "time_bin_error_rate_summary.csv")
    write_rows(row_rate_rows, args.output_dir / "row_error_rates.csv")
    write_svg_histogram(
        values=observation_rates,
        path=args.output_dir / "observation_error_rate_distribution.svg",
        title="Observation-level error rate distribution",
        subtitle=f"time_min >= {args.start_min}",
        bin_width=args.bin_width,
        min_rate=args.min_rate,
        max_rate=args.max_rate,
    )
    write_svg_histogram(
        values=row_rates,
        path=args.output_dir / "row_error_rate_distribution.svg",
        title="Observation x time-bin error rate distribution",
        subtitle=f"time_min >= {args.start_min}",
        bin_width=args.bin_width,
        min_rate=args.min_rate,
        max_rate=args.max_rate,
    )
    summary = build_summary(args, all_rows, rows, observation_rows, row_rate_rows)
    write_json(summary, args.output_dir / "error_rate_distribution_summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def load_rows(path: Path) -> list[dict[str, Any]]:
    """comparison CSVを読む。"""

    output: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            observed = int(float(row["observed_count_5min"]))
            simulated = int(float(row["simulated_count_5min"]))
            output.append(
                {
                    **row,
                    "time_min": int(row["time_min"]),
                    "observed": observed,
                    "simulated": simulated,
                    "error": simulated - observed,
                }
            )
    return output


def aggregate_by_observation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """観測点ごとの時間合計誤差率を返す。"""

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["observation_id"]].append(row)
    output: list[dict[str, Any]] = []
    for observation_id, values in groups.items():
        first = values[0]
        observed = sum(row["observed"] for row in values)
        simulated = sum(row["simulated"] for row in values)
        error = simulated - observed
        output.append(
            {
                "observation_id": observation_id,
                "point_number": first.get("point_number"),
                "point_name": first.get("point_name"),
                "directed_edge_id": first.get("directed_edge_id"),
                "observed_total": observed,
                "simulated_total": simulated,
                "error_total": error,
                "error_rate": safe_rate(error, observed),
                "ratio": simulated / observed if observed else None,
                "bin_count": len(values),
            }
        )
    output.sort(key=lambda row: row["error_rate"] if row["error_rate"] is not None else 0.0)
    return output


def aggregate_by_time(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """5分binごとの誤差率分布summaryを返す。"""

    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["time_min"]].append(row)
    output: list[dict[str, Any]] = []
    for time_min, values in sorted(groups.items()):
        rates = [safe_rate(row["error"], row["observed"]) for row in values if row["observed"] > 0]
        rates = [rate for rate in rates if rate is not None]
        observed = sum(row["observed"] for row in values)
        simulated = sum(row["simulated"] for row in values)
        output.append(
            {
                "time_min": time_min,
                "observed_total": observed,
                "simulated_total": simulated,
                "total_ratio": simulated / observed if observed else None,
                "rate_mean": mean(rates),
                "rate_std": stddev(rates),
                "rate_p10": percentile(rates, 0.10),
                "rate_p50": percentile(rates, 0.50),
                "rate_p90": percentile(rates, 0.90),
                "under_count": sum(1 for rate in rates if rate < 0),
                "over_count": sum(1 for rate in rates if rate > 0),
                "count": len(rates),
            }
        )
    return output


def build_row_rate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """観測点×時間binの誤差率行を作る。"""

    output: list[dict[str, Any]] = []
    for row in rows:
        output.append(
            {
                "time_min": row["time_min"],
                "observation_id": row["observation_id"],
                "point_number": row.get("point_number"),
                "point_name": row.get("point_name"),
                "observed": row["observed"],
                "simulated": row["simulated"],
                "error": row["error"],
                "error_rate": safe_rate(row["error"], row["observed"]),
            }
        )
    return output


def write_svg_histogram(
    *,
    values: list[float],
    path: Path,
    title: str,
    subtitle: str,
    bin_width: float,
    min_rate: float,
    max_rate: float,
) -> None:
    """誤差率ヒストグラムをSVGで描く。"""

    bins = build_bins(values, bin_width, min_rate, max_rate)
    width = 960
    height = 560
    margin_left = 72
    margin_right = 32
    margin_top = 72
    margin_bottom = 72
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    max_count = max((item["count"] for item in bins), default=1) or 1
    zero_x = margin_left + ((0.0 - min_rate) / (max_rate - min_rate)) * plot_width

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{margin_left}" y="32" font-size="22" font-family="Arial" fill="#222">{escape(title)}</text>',
        f'<text x="{margin_left}" y="56" font-size="13" font-family="Arial" fill="#666">{escape(subtitle)}</text>',
        f'<line x1="{margin_left}" y1="{height - margin_bottom}" x2="{width - margin_right}" y2="{height - margin_bottom}" stroke="#333"/>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{height - margin_bottom}" stroke="#333"/>',
        f'<line x1="{zero_x:.2f}" y1="{margin_top}" x2="{zero_x:.2f}" y2="{height - margin_bottom}" stroke="#d33" stroke-dasharray="4 4"/>',
    ]
    for item in bins:
        x = margin_left + ((item["start"] - min_rate) / (max_rate - min_rate)) * plot_width
        bar_width = max(1.0, (bin_width / (max_rate - min_rate)) * plot_width - 1)
        bar_height = (item["count"] / max_count) * plot_height
        y = height - margin_bottom - bar_height
        fill = "#2f75b5" if item["start"] < 0 else "#d9822b"
        parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" fill="{fill}" opacity="0.82"/>'
        )
    for tick in tick_values(min_rate, max_rate, 0.5):
        x = margin_left + ((tick - min_rate) / (max_rate - min_rate)) * plot_width
        parts.append(f'<line x1="{x:.2f}" y1="{height - margin_bottom}" x2="{x:.2f}" y2="{height - margin_bottom + 6}" stroke="#333"/>')
        parts.append(f'<text x="{x:.2f}" y="{height - margin_bottom + 24}" text-anchor="middle" font-size="12" font-family="Arial" fill="#333">{tick:.1f}</text>')
    for index in range(0, 5):
        value = max_count * index / 4
        y = height - margin_bottom - (value / max_count) * plot_height
        parts.append(f'<line x1="{margin_left - 5}" y1="{y:.2f}" x2="{margin_left}" y2="{y:.2f}" stroke="#333"/>')
        parts.append(f'<text x="{margin_left - 10}" y="{y + 4:.2f}" text-anchor="end" font-size="12" font-family="Arial" fill="#333">{round(value)}</text>')
        if index > 0:
            parts.append(f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" stroke="#eee"/>')
    parts.append(f'<text x="{width / 2}" y="{height - 18}" text-anchor="middle" font-size="13" font-family="Arial" fill="#333">error_rate = (simulated - observed) / observed</text>')
    parts.append(f'<text x="20" y="{height / 2}" transform="rotate(-90 20 {height / 2})" text-anchor="middle" font-size="13" font-family="Arial" fill="#333">count</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def build_bins(values: list[float], bin_width: float, min_rate: float, max_rate: float) -> list[dict[str, Any]]:
    """ヒストグラムbinを作る。"""

    count = int(math.ceil((max_rate - min_rate) / bin_width))
    bins = [
        {"start": min_rate + index * bin_width, "end": min_rate + (index + 1) * bin_width, "count": 0}
        for index in range(count)
    ]
    for value in values:
        clipped = min(max_rate - 1e-9, max(min_rate, value))
        index = int((clipped - min_rate) / bin_width)
        bins[min(max(0, index), len(bins) - 1)]["count"] += 1
    return bins


def build_summary(
    args: argparse.Namespace,
    all_rows: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    observation_rows: list[dict[str, Any]],
    row_rate_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """分布summaryを作る。"""

    observation_rates = [row["error_rate"] for row in observation_rows if row["error_rate"] is not None]
    row_rates = [row["error_rate"] for row in row_rate_rows if row["error_rate"] is not None]
    observed_total = sum(row["observed"] for row in rows)
    simulated_total = sum(row["simulated"] for row in rows)
    all_observed_total = sum(row["observed"] for row in all_rows)
    all_simulated_total = sum(row["simulated"] for row in all_rows)
    return {
        "comparison": str(args.comparison),
        "start_min": args.start_min,
        "all_row_count": len(all_rows),
        "all_observed_total": all_observed_total,
        "all_simulated_total": all_simulated_total,
        "all_simulated_total_ratio": all_simulated_total / all_observed_total if all_observed_total else None,
        "positive_observed_total": observed_total,
        "positive_simulated_total": simulated_total,
        "positive_simulated_total_ratio": simulated_total / observed_total if observed_total else None,
        "observation_count": len(observation_rows),
        "row_count": len(row_rate_rows),
        "observation_error_rate": describe(observation_rates),
        "row_error_rate": describe(row_rates),
        "under_observation_count": sum(1 for value in observation_rates if value < 0),
        "over_observation_count": sum(1 for value in observation_rates if value > 0),
        "under_row_count": sum(1 for value in row_rates if value < 0),
        "over_row_count": sum(1 for value in row_rates if value > 0),
    }


def describe(values: list[float]) -> dict[str, Any]:
    """分布統計量を返す。"""

    return {
        "count": len(values),
        "mean": mean(values),
        "std": stddev(values),
        "p05": percentile(values, 0.05),
        "p10": percentile(values, 0.10),
        "p25": percentile(values, 0.25),
        "p50": percentile(values, 0.50),
        "p75": percentile(values, 0.75),
        "p90": percentile(values, 0.90),
        "p95": percentile(values, 0.95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def safe_rate(error: float, observed: float) -> float | None:
    """誤差率を返す。"""

    if observed == 0:
        return None
    return error / observed


def mean(values: list[float]) -> float | None:
    """平均を返す。"""

    return sum(values) / len(values) if values else None


def stddev(values: list[float]) -> float | None:
    """標準偏差を返す。"""

    if not values:
        return None
    average = sum(values) / len(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / len(values))


def percentile(values: list[float], ratio: float) -> float | None:
    """線形補間なしpercentileを返す。"""

    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def tick_values(start: float, end: float, step: float) -> list[float]:
    """軸tickを返す。"""

    values: list[float] = []
    current = math.ceil(start / step) * step
    while current <= end + 1e-9:
        values.append(current)
        current += step
    return values


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


def escape(value: str) -> str:
    """SVG用に最低限escapeする。"""

    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()

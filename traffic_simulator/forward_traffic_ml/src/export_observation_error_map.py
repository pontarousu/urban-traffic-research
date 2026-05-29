#!/usr/bin/env python3
"""観測点誤差を地図ビューア用JSONへ変換する。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIGNMENT_PATH = PROJECT_ROOT / "viewer/data/observation_alignment.json"
DEFAULT_ERROR_RATES_PATH = (
    PROJECT_ROOT
    / "results/observation_error_distribution_g150_iter40_warmup10"
    / "observation_error_rates.csv"
)
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/observation_error_map.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT_PATH)
    parser.add_argument("--error-rates", type=Path, default=DEFAULT_ERROR_RATES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--start-min", type=int, default=490)
    return parser.parse_args()


def main() -> None:
    """地図用JSONを書き出す。"""

    args = parse_args()
    alignment = load_json(args.alignment)
    error_by_id = load_error_rates(args.error_rates)
    observations = build_observations(alignment, error_by_id)
    summary = build_summary(args, observations)
    output = {
        "schema_version": "observation_error_map.v1",
        "source": {
            "alignment": str(args.alignment),
            "error_rates": str(args.error_rates),
            "start_min": args.start_min,
        },
        "bounds": alignment["bounds"],
        "roads": alignment["roads"],
        "summary": summary,
        "observations": observations,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"出力: {args.output}")


def load_json(path: Path) -> dict[str, Any]:
    """JSONを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_error_rates(path: Path) -> dict[str, dict[str, Any]]:
    """観測点ごとの誤差率CSVを読む。"""

    output: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            observation_id = row["observation_id"]
            output[observation_id] = {
                **row,
                "observed_total": int(float(row["observed_total"])),
                "simulated_total": int(float(row["simulated_total"])),
                "error_total": int(float(row["error_total"])),
                "error_rate": float(row["error_rate"]),
                "ratio": float(row["ratio"]),
                "bin_count": int(float(row["bin_count"])),
            }
    return output


def build_observations(alignment: dict[str, Any], error_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """座標付き観測点と誤差率を結合する。"""

    observations: list[dict[str, Any]] = []
    for item in alignment.get("observations", []):
        error = error_by_id.get(item["id"])
        if not error:
            continue
        observations.append(
            {
                "observation_id": item["id"],
                "point_number": item.get("point_number"),
                "point_name": item.get("point_name"),
                "lat": item["lat"],
                "lon": item["lon"],
                "match_confidence": item.get("match_confidence"),
                "match_method": item.get("match_method"),
                "directed_edge_id": error.get("directed_edge_id") or item.get("matched_link", {}).get("directed_edge_id"),
                "observed_total": error["observed_total"],
                "simulated_total": error["simulated_total"],
                "error_total": error["error_total"],
                "error_rate": error["error_rate"],
                "ratio": error["ratio"],
                "bin_count": error["bin_count"],
            }
        )
    return observations


def build_summary(args: argparse.Namespace, observations: list[dict[str, Any]]) -> dict[str, Any]:
    """summaryを作る。"""

    observed_total = sum(item["observed_total"] for item in observations)
    simulated_total = sum(item["simulated_total"] for item in observations)
    under = [item for item in observations if item["error_rate"] < 0]
    over = [item for item in observations if item["error_rate"] > 0]
    rates = [item["error_rate"] for item in observations]
    return {
        "start_min": args.start_min,
        "observation_count": len(observations),
        "observed_total": observed_total,
        "simulated_total": simulated_total,
        "simulated_total_ratio": simulated_total / observed_total if observed_total else None,
        "under_observation_count": len(under),
        "over_observation_count": len(over),
        "error_rate_min": min(rates) if rates else None,
        "error_rate_max": max(rates) if rates else None,
        "error_rate_mean": sum(rates) / len(rates) if rates else None,
    }


if __name__ == "__main__":
    main()

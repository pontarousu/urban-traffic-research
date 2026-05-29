#!/usr/bin/env python3
"""近接する過小・過大観測点ペアを地図ビューア用JSONへ変換する。"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ERROR_MAP_PATH = PROJECT_ROOT / "viewer/data/observation_error_map.json"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/observation_error_pair_map.json"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--error-map", type=Path, default=DEFAULT_ERROR_MAP_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--max-distance-meter", type=float, default=150.0)
    parser.add_argument("--min-abs-error-rate", type=float, default=0.1)
    parser.add_argument("--top-n", type=int, default=200)
    return parser.parse_args()


def main() -> None:
    """近接逆符号ペアを抽出してJSONを書く。"""

    args = parse_args()
    error_map = load_json(args.error_map)
    observations = error_map["observations"]
    pairs = build_pairs(
        observations=observations,
        max_distance_meter=args.max_distance_meter,
        min_abs_error_rate=args.min_abs_error_rate,
    )
    ranked_pairs = sorted(pairs, key=lambda item: item["score"], reverse=True)
    output_pairs = ranked_pairs[: args.top_n]
    output = {
        "schema_version": "observation_error_pair_map.v1",
        "source": {
            "error_map": str(args.error_map),
            "max_distance_meter": args.max_distance_meter,
            "min_abs_error_rate": args.min_abs_error_rate,
        },
        "bounds": error_map["bounds"],
        "roads": error_map["roads"],
        "observations": observations,
        "pairs": output_pairs,
        "summary": build_summary(error_map, pairs, output_pairs, args),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False, indent=2)
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"出力: {args.output}")


def load_json(path: Path) -> dict[str, Any]:
    """JSONを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def build_pairs(
    *,
    observations: list[dict[str, Any]],
    max_distance_meter: float,
    min_abs_error_rate: float,
) -> list[dict[str, Any]]:
    """近接する逆符号ペアを返す。"""

    pairs: list[dict[str, Any]] = []
    for left_index, left in enumerate(observations):
        for right in observations[left_index + 1 :]:
            left_rate = float(left["error_rate"])
            right_rate = float(right["error_rate"])
            if left_rate == 0 or right_rate == 0:
                continue
            if left_rate * right_rate >= 0:
                continue
            if max(abs(left_rate), abs(right_rate)) < min_abs_error_rate:
                continue
            distance = haversine_meter(left["lat"], left["lon"], right["lat"], right["lon"])
            if distance > max_distance_meter:
                continue
            under = left if left_rate < 0 else right
            over = right if left_rate < 0 else left
            gap = abs(left_rate - right_rate)
            absolute_error_sum = abs(int(left["error_total"])) + abs(int(right["error_total"]))
            score = gap * math.log1p(absolute_error_sum) / max(20.0, distance)
            pairs.append(
                {
                    "pair_id": f"pair_{len(pairs) + 1:04d}",
                    "distance_meter": round(distance, 2),
                    "error_rate_gap": gap,
                    "absolute_error_sum": absolute_error_sum,
                    "score": score,
                    "left": compact_observation(left),
                    "right": compact_observation(right),
                    "under_observation_id": under["observation_id"],
                    "over_observation_id": over["observation_id"],
                    "under_error_rate": under["error_rate"],
                    "over_error_rate": over["error_rate"],
                }
            )
    return pairs


def compact_observation(item: dict[str, Any]) -> dict[str, Any]:
    """ペア表示に必要な観測点情報だけ返す。"""

    keys = [
        "observation_id",
        "point_number",
        "point_name",
        "lat",
        "lon",
        "directed_edge_id",
        "match_confidence",
        "observed_total",
        "simulated_total",
        "error_total",
        "error_rate",
        "ratio",
    ]
    return {key: item.get(key) for key in keys}


def build_summary(
    error_map: dict[str, Any],
    all_pairs: list[dict[str, Any]],
    output_pairs: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    """summaryを作る。"""

    distances = [pair["distance_meter"] for pair in all_pairs]
    gaps = [pair["error_rate_gap"] for pair in all_pairs]
    return {
        "start_min": error_map["summary"]["start_min"],
        "observation_count": len(error_map["observations"]),
        "pair_count_all": len(all_pairs),
        "pair_count_output": len(output_pairs),
        "max_distance_meter": args.max_distance_meter,
        "min_abs_error_rate": args.min_abs_error_rate,
        "distance_min": min(distances) if distances else None,
        "distance_median": percentile(distances, 0.5),
        "distance_max": max(distances) if distances else None,
        "error_rate_gap_median": percentile(gaps, 0.5),
        "error_rate_gap_max": max(gaps) if gaps else None,
        "top_pairs": output_pairs[:10],
    }


def haversine_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """2点間の概算距離をmeterで返す。"""

    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def percentile(values: list[float], ratio: float) -> float | None:
    """線形補間なしpercentileを返す。"""

    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


if __name__ == "__main__":
    main()

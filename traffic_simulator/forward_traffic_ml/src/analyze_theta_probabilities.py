#!/usr/bin/env python3
"""学習済み theta から分岐確率の偏りを集計する。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from road_db_network_loader import DEFAULT_SNAPSHOT_DIR, RoadDbNetwork, branch_key
from road_db_theta_policy import RoadDbThetaPolicy


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "results/theta_probability_analysis"


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--theta", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--epsilon", type=float, default=0.2)
    parser.add_argument("--top-n", type=int, default=50)
    return parser.parse_args()


def main() -> None:
    """theta の確率分布を集計してCSV/JSONへ保存する。"""

    args = parse_args()
    network = RoadDbNetwork.load(args.snapshot_dir)
    policy = RoadDbThetaPolicy.load(args.theta)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = build_probability_rows(network, policy.theta, args.epsilon)
    summary = summarize_rows(rows, policy.stats(), args)
    write_rows(rows, args.output_dir / "theta_probability_rows.csv")
    write_summary(summary, args.output_dir / "theta_probability_summary.json")
    write_top_rows(rows, args.output_dir / "top_biased_branches.csv", args.top_n)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def build_probability_rows(
    network: RoadDbNetwork,
    theta: dict[str, float],
    epsilon: float,
) -> list[dict[str, Any]]:
    """incoming edge ごとの分岐確率指標を作る。"""

    rows: list[dict[str, Any]] = []
    for incoming_edge_id, options in network.branch_options_by_incoming.items():
        if len(options) < 2:
            continue
        incoming = network.directed_edges.get(incoming_edge_id)
        if not incoming:
            continue
        node_id = incoming["to_node_id"]
        option_rows = []
        for option in options:
            outgoing_edge_id = option["outgoing_directed_edge_id"]
            key = branch_key(node_id, incoming_edge_id, outgoing_edge_id)
            option_rows.append(
                {
                    "theta_key": key,
                    "outgoing_edge_id": outgoing_edge_id,
                    "theta": theta.get(key, 0.0),
                }
            )
        probabilities = softmax_with_epsilon([item["theta"] for item in option_rows], epsilon)
        for item, probability in zip(option_rows, probabilities):
            item["probability"] = probability

        max_item = max(option_rows, key=lambda item: item["probability"])
        min_item = min(option_rows, key=lambda item: item["probability"])
        entropy = normalized_entropy([item["probability"] for item in option_rows])
        theta_values = [item["theta"] for item in option_rows]
        rows.append(
            {
                "node_id": node_id,
                "incoming_edge_id": incoming_edge_id,
                "option_count": len(option_rows),
                "max_probability": max_item["probability"],
                "min_probability": min_item["probability"],
                "probability_gap": max_item["probability"] - min_item["probability"],
                "normalized_entropy": entropy,
                "max_theta": max(theta_values),
                "min_theta": min(theta_values),
                "theta_gap": max(theta_values) - min(theta_values),
                "selected_outgoing_edge_id": max_item["outgoing_edge_id"],
                "selected_theta_key": max_item["theta_key"],
            }
        )
    return rows


def softmax_with_epsilon(values: list[float], epsilon: float) -> list[float]:
    """theta を softmax + epsilon 探索込みの確率へ変換する。"""

    if not values:
        return []
    max_value = max(values)
    exp_values = [math.exp(value - max_value) for value in values]
    total = sum(exp_values) or 1.0
    probabilities = [value / total for value in exp_values]
    if epsilon > 0:
        uniform = 1.0 / len(probabilities)
        probabilities = [
            (1.0 - epsilon) * probability + epsilon * uniform
            for probability in probabilities
        ]
    return probabilities


def normalized_entropy(probabilities: list[float]) -> float:
    """0から1の正規化entropyを返す。1に近いほど一様。"""

    if len(probabilities) <= 1:
        return 0.0
    entropy = -sum(probability * math.log(probability) for probability in probabilities if probability > 0)
    return entropy / math.log(len(probabilities))


def summarize_rows(rows: list[dict[str, Any]], theta_stats: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """分岐確率の偏り summary を作る。"""

    if not rows:
        return {
            "theta": str(args.theta),
            "epsilon": args.epsilon,
            "branch_group_count": 0,
            "theta_stats": theta_stats,
        }
    max_probabilities = [float(row["max_probability"]) for row in rows]
    entropies = [float(row["normalized_entropy"]) for row in rows]
    option_counts = [int(row["option_count"]) for row in rows]
    return {
        "theta": str(args.theta),
        "epsilon": args.epsilon,
        "branch_group_count": len(rows),
        "theta_stats": theta_stats,
        "option_count_avg": sum(option_counts) / len(option_counts),
        "max_probability_avg": sum(max_probabilities) / len(max_probabilities),
        "max_probability_p50": percentile(max_probabilities, 0.50),
        "max_probability_p90": percentile(max_probabilities, 0.90),
        "max_probability_p95": percentile(max_probabilities, 0.95),
        "max_probability_p99": percentile(max_probabilities, 0.99),
        "max_probability_max": max(max_probabilities),
        "normalized_entropy_avg": sum(entropies) / len(entropies),
        "normalized_entropy_p10": percentile(entropies, 0.10),
        "highly_biased_group_count_p70": sum(1 for value in max_probabilities if value >= 0.70),
        "highly_biased_group_count_p80": sum(1 for value in max_probabilities if value >= 0.80),
        "highly_biased_group_count_p90": sum(1 for value in max_probabilities if value >= 0.90),
    }


def percentile(values: list[float], ratio: float) -> float:
    """単純な線形補間なし percentile を返す。"""

    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]


def write_rows(rows: list[dict[str, Any]], path: Path) -> None:
    """詳細CSVを書く。"""

    fieldnames = [
        "node_id",
        "incoming_edge_id",
        "option_count",
        "max_probability",
        "min_probability",
        "probability_gap",
        "normalized_entropy",
        "max_theta",
        "min_theta",
        "theta_gap",
        "selected_outgoing_edge_id",
        "selected_theta_key",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_top_rows(rows: list[dict[str, Any]], path: Path, top_n: int) -> None:
    """最大確率が高い分岐をCSVへ書く。"""

    ordered = sorted(rows, key=lambda row: row["max_probability"], reverse=True)
    write_rows(ordered[:top_n], path)


def write_summary(summary: dict[str, Any], path: Path) -> None:
    """summary JSONを書く。"""

    with path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

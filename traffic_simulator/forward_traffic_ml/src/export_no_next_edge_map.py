#!/usr/bin/env python3
"""no_next_edge の位置分布を地図ビューア用JSONへ変換する。

公開版では入力となる観測点対応JSON・シミュレーション診断CSVを同梱しない。
これらは観測点位置や実験結果に由来するため、ローカル環境で生成したファイルを
明示的に指定して実行する。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIGNMENT_PATH = PROJECT_ROOT / "viewer/data/observation_alignment.json"
DEFAULT_NO_NEXT_PATH = (
    PROJECT_ROOT
    / "results/road_db_rl_mixed_auto_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact"
    / "no_next_edge_positions_by_source_quadrant.csv"
)
DEFAULT_SOURCE_SUMMARY_PATH = (
    PROJECT_ROOT
    / "results/road_db_rl_mixed_auto_mesh_uniform_500_g150_packet5_iter20_boundary1000_compact"
    / "source_quadrant_no_next_summary.csv"
)
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "viewer/data/no_next_edge_map.json"

# 注意:
# DEFAULT_* は研究用ローカル環境での再現用パスである。
# 公開リポジトリには viewer/data/*.json や results/* を含めない。
# 公開利用時は、権利上問題のない入力ファイルを --alignment / --no-next / --source-summary で指定する。


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を読む。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alignment", type=Path, default=DEFAULT_ALIGNMENT_PATH)
    parser.add_argument("--no-next", type=Path, default=DEFAULT_NO_NEXT_PATH)
    parser.add_argument("--source-summary", type=Path, default=DEFAULT_SOURCE_SUMMARY_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def main() -> None:
    """地図用JSONを書き出す。"""

    args = parse_args()
    alignment = load_json(args.alignment)
    no_next_edges = load_no_next_rows(args.no_next)
    source_summary = load_source_summary(args.source_summary)
    output = {
        "schema_version": "no_next_edge_map.v1",
        "source": {
            "alignment": str(args.alignment),
            "no_next": str(args.no_next),
            "source_summary": str(args.source_summary),
        },
        "bounds": alignment["bounds"],
        "roads": alignment["roads"],
        "observations": build_observations(alignment),
        "no_next_edges": no_next_edges,
        "source_summary": source_summary,
        "summary": build_summary(no_next_edges, source_summary),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(output, file, ensure_ascii=False)
    print(json.dumps(output["summary"], ensure_ascii=False, indent=2))
    print(f"出力: {args.output}")


def load_json(path: Path) -> dict[str, Any]:
    """JSONを読む。"""

    with path.open(encoding="utf-8") as file:
        return json.load(file)


def load_no_next_rows(path: Path) -> list[dict[str, Any]]:
    """no_next_edge 集計CSVを読む。"""

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            rows.append(
                {
                    "source_quadrant": row["source_quadrant"],
                    "final_edge_id": row["final_edge_id"],
                    "final_quadrant": row["final_quadrant"],
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "boundary_distance_meter": float(row["boundary_distance_meter"]),
                    "road_type": row["road_type"],
                    "weight": int(float(row["weight"])),
                    "packet_count": int(float(row["packet_count"])),
                    "with_observation_weight": int(float(row["with_observation_weight"])),
                    "without_observation_weight": int(float(row["without_observation_weight"])),
                }
            )
    return rows


def load_source_summary(path: Path) -> list[dict[str, Any]]:
    """source象限別サマリCSVを読む。"""

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            rows.append(
                {
                    "source_quadrant": row["source_quadrant"],
                    "spawn_weight": int(float(row["spawn_weight"])),
                    "spawn_packets": int(float(row["spawn_packets"])),
                    "with_observation_weight": int(float(row["with_observation_weight"])),
                    "no_next_weight": int(float(row["no_next_weight"])),
                    "no_next_without_observation_weight": int(float(row["no_next_without_observation_weight"])),
                    "no_next_with_observation_weight": int(float(row["no_next_with_observation_weight"])),
                    "reach_ratio": float(row["reach_ratio"]),
                    "no_next_ratio": float(row["no_next_ratio"]),
                    "no_next_without_observation_ratio": float(row["no_next_without_observation_ratio"]),
                }
            )
    return rows


def build_observations(alignment: dict[str, Any]) -> list[dict[str, Any]]:
    """観測点表示用データを作る。"""

    output = []
    for item in alignment.get("observations", []):
        output.append(
            {
                "observation_id": item["id"],
                "point_number": item.get("point_number"),
                "point_name": item.get("point_name"),
                "lat": item["lat"],
                "lon": item["lon"],
                "match_confidence": item.get("match_confidence"),
                "match_method": item.get("match_method"),
            }
        )
    return output


def build_summary(no_next_edges: list[dict[str, Any]], source_summary: list[dict[str, Any]]) -> dict[str, Any]:
    """表示用summaryを作る。"""

    total_weight = sum(row["weight"] for row in no_next_edges)
    without_observation_weight = sum(row["without_observation_weight"] for row in no_next_edges)
    return {
        "no_next_edge_count": len(no_next_edges),
        "no_next_weight": total_weight,
        "without_observation_weight": without_observation_weight,
        "without_observation_ratio": without_observation_weight / total_weight if total_weight else None,
        "source_summary": source_summary,
    }


if __name__ == "__main__":
    main()

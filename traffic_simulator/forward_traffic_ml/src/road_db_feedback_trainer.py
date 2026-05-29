#!/usr/bin/env python3
"""観測誤差を車両 trace の分岐へ戻して theta delta を作る。"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from road_db_network_loader import RoadDbNetwork, branch_key


RECENCY_WEIGHTS = [1.0, 0.8, 0.6, 0.4, 0.2]


def build_feedback_lookup(
    comparison_rows: list[dict[str, Any]],
    error_floor: float,
) -> dict[tuple[int, str], dict[str, float]]:
    """比較行から観測点・時間binごとの feedback を作る。"""

    lookup: dict[tuple[int, str], dict[str, float]] = {}
    for row in comparison_rows:
        time_min = int(row["time_min"])
        observation_id = row["observation_id"]
        observed = float(row["observed_count_5min"])
        simulated = float(row["simulated_count_5min"])
        feedback_error = (observed - simulated) / max(observed, error_floor)
        observation_weight = 1.0 / max(1.0, simulated)
        lookup[(time_min, observation_id)] = {
            "observed": observed,
            "simulated": simulated,
            "feedback_error": feedback_error,
            "observation_weight": observation_weight,
        }
    return lookup


def compute_feedback(
    *,
    network: RoadDbNetwork,
    comparison_rows: list[dict[str, Any]],
    vehicle_traces: list[dict[str, Any]],
    iteration: int,
    learning_rate: float,
    error_floor: float,
    max_backtrace_branches: int,
    backtrace_mode: str = "branch_count",
    max_backtrace_distance_meter: float = 1000.0,
    backtrace_decay_meter: float = 350.0,
    min_backtrace_weight: float = 0.05,
) -> dict[str, Any]:
    """trace-based feedback を計算する。"""

    feedback_lookup = build_feedback_lookup(comparison_rows, error_floor)
    deltas: dict[str, float] = defaultdict(float)
    diagnostics: list[dict[str, Any]] = []
    event_count = 0
    skipped_no_feedback = 0

    for vehicle in vehicle_traces:
        vehicle_weight = int(vehicle.get("weight", 1) or 1)
        branches = sorted(vehicle.get("branch_trace", []), key=lambda item: item["time_sec"])
        if not branches:
            continue
        for observation in vehicle.get("observation_trace", []):
            event_count += 1
            feedback = feedback_lookup.get((int(observation["bin_min"]), observation["observation_id"]))
            if not feedback:
                skipped_no_feedback += 1
                continue
            prior_indexes = [
                index
                for index, branch in enumerate(branches)
                if int(branch["time_sec"]) <= int(observation["time_sec"])
            ]
            candidate_indexes = select_backtrace_indexes(
                network=network,
                branches=branches,
                observation=observation,
                prior_indexes=prior_indexes,
                backtrace_mode=backtrace_mode,
                max_backtrace_branches=max_backtrace_branches,
                max_backtrace_distance_meter=max_backtrace_distance_meter,
            )
            for rank, branch_index, distance in candidate_indexes:
                branch = branches[branch_index]
                backtrace_weight = backtrace_weight_for_item(
                    rank=rank,
                    distance_meter=distance,
                    backtrace_mode=backtrace_mode,
                    backtrace_decay_meter=backtrace_decay_meter,
                    min_backtrace_weight=min_backtrace_weight,
                )
                theta_key = branch_key(
                    branch["node_id"],
                    branch["incoming_directed_edge_id"],
                    branch["outgoing_directed_edge_id"],
                )
                delta = (
                    learning_rate
                    * feedback["feedback_error"]
                    * backtrace_weight
                    * feedback["observation_weight"]
                    * vehicle_weight
                )
                deltas[theta_key] += delta
                diagnostics.append(
                    {
                        "iteration": iteration,
                        "observation_id": observation["observation_id"],
                        "time_bin": observation["bin_min"],
                        "vehicle_id": vehicle["vehicle_id"],
                        "vehicle_weight": vehicle_weight,
                        "rank_from_observation": rank,
                        "node_id": branch["node_id"],
                        "incoming_directed_edge_id": branch["incoming_directed_edge_id"],
                        "outgoing_directed_edge_id": branch["outgoing_directed_edge_id"],
                        "time_to_observation_sec": int(observation["time_sec"]) - int(branch["time_sec"]),
                        "distance_to_observation_meter": distance,
                        "feedback_error": feedback["feedback_error"],
                        "recency_weight": backtrace_weight,
                        "backtrace_mode": backtrace_mode,
                        "observation_weight": feedback["observation_weight"],
                        "delta_theta_raw": delta,
                        "theta_key": theta_key,
                    }
                )

    return {
        "deltas": dict(deltas),
        "diagnostics": diagnostics,
        "summary": {
            "observation_feedback_event_count": event_count,
            "skipped_no_feedback_count": skipped_no_feedback,
            "raw_feedback_contribution_count": len(diagnostics),
            "raw_delta_abs_sum": sum(abs(value) for value in deltas.values()),
            "backtrace_mode": backtrace_mode,
        },
    }


def select_backtrace_indexes(
    *,
    network: RoadDbNetwork,
    branches: list[dict[str, Any]],
    observation: dict[str, Any],
    prior_indexes: list[int],
    backtrace_mode: str,
    max_backtrace_branches: int,
    max_backtrace_distance_meter: float,
) -> list[tuple[int, int, float | None]]:
    """feedback対象の分岐indexを返す。"""

    if backtrace_mode == "branch_count":
        output = []
        for rank, branch_index in enumerate(reversed(prior_indexes[-max_backtrace_branches:]), start=1):
            distance = distance_from_branch_to_observation(network, branches, branch_index, observation)
            output.append((rank, branch_index, distance))
        return output

    if backtrace_mode != "distance":
        raise ValueError(f"未知の backtrace_mode です: {backtrace_mode}")

    output = []
    for branch_index in reversed(prior_indexes):
        distance = distance_from_branch_to_observation(network, branches, branch_index, observation)
        if distance is None:
            continue
        if distance > max_backtrace_distance_meter:
            continue
        output.append((len(output) + 1, branch_index, distance))
    return output


def backtrace_weight_for_item(
    *,
    rank: int,
    distance_meter: float | None,
    backtrace_mode: str,
    backtrace_decay_meter: float,
    min_backtrace_weight: float,
) -> float:
    """backtrace 対象分岐の重みを返す。"""

    if backtrace_mode == "branch_count":
        return recency_weight_for_rank(rank)
    if distance_meter is None:
        return 0.0
    decay = max(1.0, backtrace_decay_meter)
    return max(min_backtrace_weight, math.exp(-distance_meter / decay))


def recency_weight_for_rank(rank: int) -> float:
    """観測点に近い分岐ほど大きい重みを返す。"""

    if rank <= len(RECENCY_WEIGHTS):
        return RECENCY_WEIGHTS[rank - 1]
    return max(0.0, 1.0 - 0.2 * (rank - 1))


def distance_from_branch_to_observation(
    network: RoadDbNetwork,
    branches: list[dict[str, Any]],
    branch_index: int,
    observation: dict[str, Any],
) -> float | None:
    """分岐から観測点までの概算走行距離を返す。"""

    observation_edge_id = observation["directed_edge_id"]
    observation_position = network.edge_length(observation_edge_id) * float(observation.get("position_ratio") or 0.5)
    current_edge_id = branches[branch_index]["outgoing_directed_edge_id"]
    distance = 0.0
    if current_edge_id == observation_edge_id:
        return round(observation_position, 3)

    observation_time = int(observation["time_sec"])
    for next_branch in branches[branch_index + 1:]:
        if int(next_branch["time_sec"]) > observation_time:
            break
        distance += network.edge_length(current_edge_id)
        current_edge_id = next_branch["outgoing_directed_edge_id"]
        if current_edge_id == observation_edge_id:
            return round(distance + observation_position, 3)
    return None


def write_backtrace_diagnostics(rows: list[dict[str, Any]], path: Path) -> None:
    """backtrace 診断CSVを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "iteration",
        "observation_id",
        "time_bin",
        "vehicle_id",
        "vehicle_weight",
        "rank_from_observation",
        "node_id",
        "incoming_directed_edge_id",
        "outgoing_directed_edge_id",
        "time_to_observation_sec",
        "distance_to_observation_meter",
        "feedback_error",
        "recency_weight",
        "backtrace_mode",
        "observation_weight",
        "delta_theta_raw",
        "theta_key",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def summarize_backtrace(rows: list[dict[str, Any]], iteration: int) -> list[dict[str, Any]]:
    """rank別のbacktrace距離・時間サマリを作る。"""

    by_rank: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_rank[int(row["rank_from_observation"])].append(row)

    summaries = []
    for rank in sorted(by_rank):
        values = by_rank[rank]
        distances = [
            float(row["distance_to_observation_meter"])
            for row in values
            if row["distance_to_observation_meter"] is not None
            and not math.isnan(float(row["distance_to_observation_meter"]))
        ]
        times = [float(row["time_to_observation_sec"]) for row in values]
        summaries.append(
            {
                "iteration": iteration,
                "rank_from_observation": rank,
                "sample_count": len(values),
                "distance_sample_count": len(distances),
                "distance_mean": mean_or_none(distances),
                "distance_median": median(distances) if distances else None,
                "distance_p90": percentile(distances, 0.9),
                "time_mean": mean_or_none(times),
                "time_median": median(times) if times else None,
                "time_p90": percentile(times, 0.9),
            }
        )
    return summaries


def write_backtrace_summary(rows: list[dict[str, Any]], path: Path) -> None:
    """backtrace summary CSVを書く。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "iteration",
        "rank_from_observation",
        "sample_count",
        "distance_sample_count",
        "distance_mean",
        "distance_median",
        "distance_p90",
        "time_mean",
        "time_median",
        "time_p90",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def mean_or_none(values: list[float]) -> float | None:
    """平均値を返す。"""

    if not values:
        return None
    return sum(values) / len(values)


def percentile(values: list[float], ratio: float) -> float | None:
    """単純なパーセンタイルを返す。"""

    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * ratio)))
    return ordered[index]

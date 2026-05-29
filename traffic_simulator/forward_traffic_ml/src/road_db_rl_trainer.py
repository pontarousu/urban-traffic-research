#!/usr/bin/env python3
"""道路DBシミュレーションの最小RL更新を計算する。"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from road_db_feedback_trainer import (
    backtrace_weight_for_item,
    select_backtrace_indexes,
)
from road_db_network_loader import RoadDbNetwork, branch_key


def build_reward_lookup(
    comparison_rows: list[dict[str, Any]],
    *,
    reward_start_min: int,
) -> dict[tuple[int, str], dict[str, Any]]:
    """比較行から観測点・時間binごとの報酬を作る。"""

    lookup: dict[tuple[int, str], dict[str, float]] = {}
    for row in comparison_rows:
        time_min = int(row["time_min"])
        if time_min < reward_start_min:
            continue
        observation_id = str(row["observation_id"])
        observed = float(row["observed_count_5min"])
        simulated = float(row["simulated_count_5min"])
        error_rate = (simulated - observed) / max(observed, 1.0)
        reward = -abs(error_rate)
        lookup[(time_min, observation_id)] = {
            "observation_id": observation_id,
            "observed": observed,
            "simulated": simulated,
            "error_rate": error_rate,
            "reward": reward,
        }
    return lookup


def compute_global_baseline(reward_lookup: dict[tuple[int, str], dict[str, Any]]) -> float:
    """全観測点・全時間binの平均報酬を返す。"""

    rewards = [item["reward"] for item in reward_lookup.values()]
    if not rewards:
        return 0.0
    return sum(rewards) / len(rewards)


def compute_observation_baselines(
    reward_lookup: dict[tuple[int, str], dict[str, Any]]
) -> dict[str, float]:
    """観測点ごとの平均報酬を返す。"""

    rewards_by_observation: dict[str, list[float]] = defaultdict(list)
    for item in reward_lookup.values():
        rewards_by_observation[str(item["observation_id"])].append(item["reward"])
    return {
        observation_id: sum(rewards) / len(rewards)
        for observation_id, rewards in rewards_by_observation.items()
        if rewards
    }


def baseline_for_reward(
    *,
    reward_info: dict[str, Any],
    global_baseline: float,
    observation_baselines: dict[str, float],
    baseline_mode: str,
    mixed_baseline_global_weight: float,
) -> float:
    """指定した方式で報酬に対応するbaselineを返す。"""

    if baseline_mode == "global":
        return global_baseline

    observation_id = str(reward_info["observation_id"])
    observation_baseline = observation_baselines.get(observation_id, global_baseline)
    if baseline_mode == "observation":
        return observation_baseline

    if baseline_mode == "mixed":
        global_weight = min(1.0, max(0.0, mixed_baseline_global_weight))
        return observation_baseline * (1.0 - global_weight) + global_baseline * global_weight

    raise ValueError(f"未知の baseline_mode です: {baseline_mode}")


def compute_rl_feedback(
    *,
    network: RoadDbNetwork,
    comparison_rows: list[dict[str, Any]],
    vehicle_traces: list[dict[str, Any]],
    theta: dict[str, float],
    iteration: int,
    reward_start_min: int,
    learning_rate: float,
    epsilon: float,
    backtrace_mode: str,
    max_backtrace_branches: int,
    max_backtrace_distance_meter: float,
    backtrace_decay_meter: float,
    min_backtrace_weight: float,
    diagnostics_limit: int = 0,
    baseline_mode: str = "global",
    mixed_baseline_global_weight: float = 0.3,
) -> dict[str, Any]:
    """REINFORCE風の theta delta を計算する。"""

    reward_lookup = build_reward_lookup(
        comparison_rows,
        reward_start_min=reward_start_min,
    )
    global_baseline = compute_global_baseline(reward_lookup)
    observation_baselines = compute_observation_baselines(reward_lookup)
    deltas: dict[str, float] = defaultdict(float)
    diagnostics: list[dict[str, Any]] = []
    observation_event_count = 0
    skipped_before_reward_window = 0
    skipped_no_reward = 0
    skipped_no_branches = 0
    skipped_no_options = 0
    contribution_count = 0

    for vehicle in vehicle_traces:
        vehicle_weight = int(vehicle.get("weight", 1) or 1)
        branches = sorted(vehicle.get("branch_trace", []), key=lambda item: item["time_sec"])
        if not branches:
            skipped_no_branches += len(vehicle.get("observation_trace", []))
            continue
        for observation in vehicle.get("observation_trace", []):
            observation_event_count += 1
            bin_min = int(observation["bin_min"])
            if bin_min < reward_start_min:
                skipped_before_reward_window += 1
                continue
            reward_info = reward_lookup.get((bin_min, observation["observation_id"]))
            if not reward_info:
                skipped_no_reward += 1
                continue
            baseline = baseline_for_reward(
                reward_info=reward_info,
                global_baseline=global_baseline,
                observation_baselines=observation_baselines,
                baseline_mode=baseline_mode,
                mixed_baseline_global_weight=mixed_baseline_global_weight,
            )
            advantage = reward_info["reward"] - baseline
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
                gradient_items = policy_log_gradient(
                    network=network,
                    theta=theta,
                    incoming_edge_id=branch["incoming_directed_edge_id"],
                    chosen_outgoing_edge_id=branch["outgoing_directed_edge_id"],
                    epsilon=epsilon,
                )
                if not gradient_items:
                    skipped_no_options += 1
                    continue
                contribution_count += 1
                contribution_scale = learning_rate * advantage * backtrace_weight * vehicle_weight
                for theta_key, gradient in gradient_items:
                    deltas[theta_key] += contribution_scale * gradient
                if diagnostics_limit > 0 and len(diagnostics) < diagnostics_limit:
                    diagnostics.append(
                        {
                            "iteration": iteration,
                            "observation_id": observation["observation_id"],
                            "time_bin": bin_min,
                            "vehicle_id": vehicle["vehicle_id"],
                            "vehicle_weight": vehicle_weight,
                            "rank_from_observation": rank,
                            "node_id": branch["node_id"],
                            "incoming_directed_edge_id": branch["incoming_directed_edge_id"],
                            "outgoing_directed_edge_id": branch["outgoing_directed_edge_id"],
                            "time_to_observation_sec": int(observation["time_sec"]) - int(branch["time_sec"]),
                            "distance_to_observation_meter": distance,
                            "observed": reward_info["observed"],
                            "simulated": reward_info["simulated"],
                            "error_rate": reward_info["error_rate"],
                            "reward": reward_info["reward"],
                            "baseline": baseline,
                            "advantage": advantage,
                            "backtrace_weight": backtrace_weight,
                            "backtrace_mode": backtrace_mode,
                            "contribution_scale": contribution_scale,
                        }
                    )

    return {
        "deltas": dict(deltas),
        "diagnostics": diagnostics,
        "summary": {
            "rl_reward_baseline": global_baseline,
            "rl_reward_baseline_global": global_baseline,
            "rl_baseline_mode": baseline_mode,
            "rl_mixed_baseline_global_weight": mixed_baseline_global_weight,
            "rl_observation_baseline_count": len(observation_baselines),
            "rl_observation_baseline_min": min(observation_baselines.values()) if observation_baselines else None,
            "rl_observation_baseline_max": max(observation_baselines.values()) if observation_baselines else None,
            "rl_reward_row_count": len(reward_lookup),
            "rl_observation_event_count": observation_event_count,
            "rl_skipped_before_reward_window": skipped_before_reward_window,
            "rl_skipped_no_reward": skipped_no_reward,
            "rl_skipped_no_branches": skipped_no_branches,
            "rl_skipped_no_options": skipped_no_options,
            "rl_policy_gradient_contribution_count": contribution_count,
            "rl_diagnostics_sample_count": len(diagnostics),
            "raw_delta_abs_sum": sum(abs(value) for value in deltas.values()),
            "backtrace_mode": backtrace_mode,
        },
    }


def policy_log_gradient(
    *,
    network: RoadDbNetwork,
    theta: dict[str, float],
    incoming_edge_id: str,
    chosen_outgoing_edge_id: str,
    epsilon: float,
) -> list[tuple[str, float]]:
    """epsilon混合policyの log 確率に対する theta 勾配を返す。"""

    options = network.outgoing_options(incoming_edge_id)
    if not options:
        return []
    incoming = network.directed_edges[incoming_edge_id]
    node_id = incoming["to_node_id"]
    outgoing_ids = [option["outgoing_directed_edge_id"] for option in options]
    if chosen_outgoing_edge_id not in outgoing_ids:
        return []

    scores = [
        theta.get(branch_key(node_id, incoming_edge_id, outgoing_edge_id), 0.0)
        for outgoing_edge_id in outgoing_ids
    ]
    softmax_values = softmax(scores)
    chosen_index = outgoing_ids.index(chosen_outgoing_edge_id)
    chosen_softmax = softmax_values[chosen_index]
    option_count = len(outgoing_ids)
    chosen_policy_probability = (
        (1.0 - epsilon) * chosen_softmax
        + epsilon * (1.0 / option_count)
    )
    if chosen_policy_probability <= 0:
        return []

    coefficient = (1.0 - epsilon) * chosen_softmax / chosen_policy_probability
    gradients: list[tuple[str, float]] = []
    for index, outgoing_edge_id in enumerate(outgoing_ids):
        indicator = 1.0 if index == chosen_index else 0.0
        gradient = coefficient * (indicator - softmax_values[index])
        theta_key = branch_key(node_id, incoming_edge_id, outgoing_edge_id)
        gradients.append((theta_key, gradient))
    return gradients


def softmax(scores: list[float]) -> list[float]:
    """score列をsoftmax確率へ変換する。"""

    if not scores:
        return []
    max_score = max(scores)
    exp_values = [math.exp(score - max_score) for score in scores]
    total = sum(exp_values) or 1.0
    return [value / total for value in exp_values]


def write_rl_diagnostics(rows: list[dict[str, Any]], path: Path) -> None:
    """RL診断CSVを書く。"""

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
        "observed",
        "simulated",
        "error_rate",
        "reward",
        "baseline",
        "advantage",
        "backtrace_weight",
        "backtrace_mode",
        "contribution_scale",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

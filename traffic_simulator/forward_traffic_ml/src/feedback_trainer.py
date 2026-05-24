#!/usr/bin/env python3
"""観測誤差を分岐確率 theta にフィードバックする。"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from branch_policy import BranchPolicy


def observed_count(dataset: dict[str, Any], obs_id: str, time_min: int) -> int:
    for observation in dataset["observations"]:
        if observation["id"] == obs_id:
            return int(observation.get("observed_volume_5min", {}).get(str(time_min), 0))
    return 0


def build_observed_lookup(dataset: dict[str, Any]) -> dict[tuple[int, str], int]:
    lookup: dict[tuple[int, str], int] = {}
    start_min = int(dataset["meta"]["start_min"])
    end_min = int(dataset["meta"]["end_min"])
    for observation in dataset["observations"]:
        values = observation.get("observed_volume_5min", {})
        for time_min in range(start_min, end_min, 5):
            lookup[(time_min, observation["id"])] = int(values.get(str(time_min), 0))
    return lookup


def normalized_errors(
    dataset: dict[str, Any],
    simulated_counts: dict[tuple[int, str], int],
    minimum_volume: int = 10,
) -> dict[tuple[int, str], float]:
    observed = build_observed_lookup(dataset)
    errors: dict[tuple[int, str], float] = {}
    for key, observed_value in observed.items():
        simulated_value = simulated_counts.get(key, 0)
        errors[key] = (observed_value - simulated_value) / max(observed_value, minimum_volume)
    return errors


def update_policy_from_traces(
    policy: BranchPolicy,
    dataset: dict[str, Any],
    simulated_counts: dict[tuple[int, str], int],
    vehicle_traces: list[dict[str, Any]],
    minimum_volume: int = 10,
    max_trace_back_steps: int = 5,
    tau: float = 300.0,
    vehicle_feedback_cap: float = 1.0,
    learning_rate: float = 0.05,
    delta_theta_clip: float = 0.2,
    regularization_strength: float = 0.01,
) -> dict[str, Any]:
    """車両 trace から theta を更新する。"""
    errors = normalized_errors(dataset, simulated_counts, minimum_volume)
    branch_feedback: dict[str, float] = defaultdict(float)
    branch_feedback_count: dict[str, int] = defaultdict(int)

    for vehicle in vehicle_traces:
        vehicle_deltas: dict[str, float] = defaultdict(float)
        branch_trace = vehicle.get("branch_trace", [])
        observation_trace = vehicle.get("observation_trace", [])
        for observation_event in observation_trace:
            obs_id = observation_event["obs_id"]
            bin_min = int(observation_event["bin_min"])
            obs_time_sec = float(observation_event["time_sec"])
            error = errors.get((bin_min, obs_id), 0.0)
            if error == 0:
                continue

            prior_branches = [
                branch for branch in branch_trace
                if float(branch["time_sec"]) <= obs_time_sec
            ][-max_trace_back_steps:]
            for branch in prior_branches:
                delta_time = max(0.0, obs_time_sec - float(branch["time_sec"]))
                time_decay = math.exp(-delta_time / tau)
                key = BranchPolicy.key_to_string(
                    branch["node_id"],
                    branch["incoming_way_id"],
                    branch["outgoing_way_id"],
                )
                vehicle_deltas[key] += error * time_decay

        total_abs = sum(abs(value) for value in vehicle_deltas.values())
        if total_abs > vehicle_feedback_cap and total_abs > 0:
            scale = vehicle_feedback_cap / total_abs
            vehicle_deltas = defaultdict(float, {key: value * scale for key, value in vehicle_deltas.items()})

        for key, value in vehicle_deltas.items():
            branch_feedback[key] += value
            branch_feedback_count[key] += 1

    policy.regularize(regularization_strength)
    update_count = 0
    max_abs_delta = 0.0
    for key, feedback in branch_feedback.items():
        count = max(1, branch_feedback_count[key])
        raw_delta = learning_rate * feedback / count
        delta = max(-delta_theta_clip, min(delta_theta_clip, raw_delta))
        node_id, incoming_way_id, outgoing_way_id = BranchPolicy.string_to_key(key)
        policy.add_delta(node_id, incoming_way_id, outgoing_way_id, delta)
        update_count += 1
        max_abs_delta = max(max_abs_delta, abs(delta))

    return {
        "updated_branch_count": update_count,
        "max_abs_delta_theta": max_abs_delta,
    }

#!/usr/bin/env python3
"""道路DB directed_edge ベースの最小順方向シミュレーション。"""

from __future__ import annotations

import random
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from road_db_network_loader import ObservationMatch, RoadDbNetwork, build_observations_by_edge


@dataclass
class RoadDbVehicle:
    """directed edge 上を移動する車両状態。"""

    vehicle_id: int
    directed_edge_id: str
    position_meter: float
    birth_time_sec: int
    source_edge_id: str
    source_category: str
    source_position_meter: float
    weight: int = 1
    source_mesh_id: str | None = None
    branch_trace: list[dict[str, Any]] = field(default_factory=list)
    observation_trace: list[dict[str, Any]] = field(default_factory=list)


def choose_weighted(items: list[dict[str, Any]], rng: random.Random) -> dict[str, Any] | None:
    """weight に従って候補を1つ選ぶ。"""

    if not items:
        return None
    total = sum(max(0.0, float(item.get("weight", 1.0))) for item in items)
    if total <= 0:
        return rng.choice(items)
    threshold = rng.random() * total
    current = 0.0
    for item in items:
        current += max(0.0, float(item.get("weight", 1.0)))
        if current >= threshold:
            return item
    return items[-1]


class WeightedSourceSampler:
    """発生候補を累積重みから高速に選ぶ。"""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.cumulative_weights: list[float] = []
        current = 0.0
        for item in items:
            current += max(0.0, float(item.get("weight", 1.0)))
            self.cumulative_weights.append(current)
        self.total_weight = current

    def choose(self, rng: random.Random) -> dict[str, Any] | None:
        """weight に従って候補を1つ返す。"""

        if not self.items:
            return None
        if self.total_weight <= 0:
            return rng.choice(self.items)
        threshold = rng.random() * self.total_weight
        index = bisect_left(self.cumulative_weights, threshold)
        return self.items[min(index, len(self.items) - 1)]


def observed_total_by_bin(observations: list[ObservationMatch], start_min: int, duration_min: int) -> dict[int, int]:
    """対象観測点の5分観測総量を返す。"""

    totals: dict[int, int] = {}
    for time_min in range(start_min, start_min + duration_min, 5):
        totals[time_min] = sum(obs.observed_volume_5min.get(time_min, 0) for obs in observations)
    return totals


def build_spawn_schedule(
    *,
    observed_totals: dict[int, int],
    start_min: int,
    duration_min: int,
    time_step_sec: int,
    generation_multiplier: float,
    max_spawn_per_bin: int,
    spawn_timing: str,
) -> dict[int, int]:
    """5分binごとの発生量をシミュレーション時刻へ配分する。"""

    schedule: dict[int, int] = defaultdict(int)
    for time_min in range(start_min, start_min + duration_min, 5):
        bin_start_sec = (time_min - start_min) * 60
        requested_spawn = round(observed_totals.get(time_min, 0) * generation_multiplier)
        bin_spawn_count = min(max_spawn_per_bin, requested_spawn)
        if bin_spawn_count <= 0:
            continue
        if spawn_timing == "batch":
            schedule[bin_start_sec] += bin_spawn_count
            continue
        if spawn_timing != "distributed":
            raise ValueError(f"未知の spawn_timing です: {spawn_timing}")

        step_count = max(1, 300 // time_step_sec)
        spawned_so_far = 0
        for step_index in range(step_count):
            elapsed_in_bin = step_index * time_step_sec
            target_cumulative = round(bin_spawn_count * (step_index + 1) / step_count)
            spawn_now = target_cumulative - spawned_so_far
            if spawn_now > 0:
                schedule[bin_start_sec + elapsed_in_bin] += spawn_now
                spawned_so_far += spawn_now
    return dict(schedule)


def spawn_vehicles(
    *,
    active: list[RoadDbVehicle],
    source_sampler: WeightedSourceSampler,
    rng: random.Random,
    spawn_count: int,
    next_vehicle_id: int,
    time_sec: int,
    spawn_stats_by_category: dict[str, int],
    spawn_stats_by_edge: dict[str, int],
    spawn_stats_by_mesh: dict[str, int],
    vehicle_packet_size: int,
) -> tuple[int, int, int]:
    """指定台数の車両を発生させる。"""

    represented_spawned = 0
    packet_spawned = 0
    packet_size = max(1, int(vehicle_packet_size))
    remaining = max(0, int(spawn_count))
    while remaining > 0:
        packet_weight = min(packet_size, remaining)
        source = source_sampler.choose(rng)
        if not source:
            break
        edge_id = source["directed_edge_id"]
        category = source.get("source_category", "unknown")
        position_meter = choose_spawn_position(source, rng)
        active.append(
            RoadDbVehicle(
                vehicle_id=next_vehicle_id,
                directed_edge_id=edge_id,
                position_meter=position_meter,
                birth_time_sec=time_sec,
                source_edge_id=edge_id,
                source_category=category,
                source_position_meter=position_meter,
                weight=packet_weight,
                source_mesh_id=source.get("mesh_id"),
            )
        )
        spawn_stats_by_category[category] += packet_weight
        spawn_stats_by_edge[edge_id] += packet_weight
        if source.get("mesh_id"):
            spawn_stats_by_mesh[source["mesh_id"]] += packet_weight
        next_vehicle_id += 1
        represented_spawned += packet_weight
        packet_spawned += 1
        remaining -= packet_weight
    return next_vehicle_id, represented_spawned, packet_spawned


def choose_spawn_position(source: dict[str, Any], rng: random.Random) -> float:
    """edge上の発生位置を返す。"""

    edge_length = max(1.0, float(source.get("length_meter") or 0.0))
    if edge_length <= 1.0:
        return 0.0
    margin = min(20.0, edge_length * 0.2)
    if edge_length <= margin * 2:
        return edge_length * 0.5
    return rng.uniform(margin, edge_length - margin)


def record_crossings(
    *,
    vehicle: RoadDbVehicle,
    observations_by_edge: dict[str, list[ObservationMatch]],
    counts: dict[tuple[int, str], int],
    edge_id: str,
    previous_position: float,
    next_position: float,
    current_time_sec: int,
    current_time_min: int,
) -> None:
    """前回位置から今回位置までの間にある観測点通過を記録する。"""

    if next_position < previous_position:
        return
    bin_min = (current_time_min // 5) * 5
    epsilon = 1e-6
    for observation in observations_by_edge.get(edge_id, []):
        target = observation.position_meter
        if previous_position - epsilon <= target <= next_position + epsilon:
            counts[(bin_min, observation.observation_id)] += vehicle.weight
            vehicle.observation_trace.append(
                {
                    "time_sec": current_time_sec,
                    "time_min": current_time_min,
                    "bin_min": bin_min,
                    "observation_id": observation.observation_id,
                    "point_number": observation.point_number,
                    "directed_edge_id": edge_id,
                    "position_ratio": observation.position_ratio,
                    "weight": vehicle.weight,
                }
            )


def vehicle_to_trace(vehicle: RoadDbVehicle, final_status: str, final_time_sec: int) -> dict[str, Any]:
    """車両 trace を JSON 出力用に変換する。"""

    return {
        "vehicle_id": vehicle.vehicle_id,
        "birth_time_sec": vehicle.birth_time_sec,
        "final_time_sec": final_time_sec,
        "final_status": final_status,
        "source_edge_id": vehicle.source_edge_id,
        "source_category": vehicle.source_category,
        "source_position_meter": round(vehicle.source_position_meter, 3),
        "weight": vehicle.weight,
        "source_mesh_id": vehicle.source_mesh_id,
        "branch_trace": vehicle.branch_trace,
        "observation_trace": vehicle.observation_trace,
    }


def run_road_db_simulation(
    *,
    network: RoadDbNetwork,
    observations: list[ObservationMatch],
    source_candidates: list[dict[str, Any]],
    start_min: int,
    duration_min: int,
    seed: int,
    time_step_sec: int,
    generation_multiplier: float,
    max_spawn_per_bin: int,
    max_active_vehicles: int,
    max_vehicle_age_sec: int,
    epsilon: float,
    spawn_timing: str = "distributed",
    vehicle_packet_size: int = 1,
    theta: dict[str, float] | None = None,
) -> dict[str, Any]:
    """road DB ベースの最小シミュレーションを実行する。"""

    rng = random.Random(seed)
    theta = theta or {}
    source_sampler = WeightedSourceSampler(source_candidates)
    observations_by_edge = build_observations_by_edge(observations)
    observed_totals = observed_total_by_bin(observations, start_min, duration_min)
    total_seconds = duration_min * 60
    spawn_schedule = build_spawn_schedule(
        observed_totals=observed_totals,
        start_min=start_min,
        duration_min=duration_min,
        time_step_sec=time_step_sec,
        generation_multiplier=generation_multiplier,
        max_spawn_per_bin=max_spawn_per_bin,
        spawn_timing=spawn_timing,
    )

    active: list[RoadDbVehicle] = []
    completed_traces: list[dict[str, Any]] = []
    counts: dict[tuple[int, str], int] = defaultdict(int)
    next_vehicle_id = 1
    total_scheduled_spawn = sum(spawn_schedule.values())
    total_spawned = 0
    total_spawn_packets = 0
    dropped_spawn_count = 0
    active_packet_samples: list[int] = []
    active_weight_samples: list[int] = []
    spawn_stats_by_category: dict[str, int] = defaultdict(int)
    spawn_stats_by_edge: dict[str, int] = defaultdict(int)
    spawn_stats_by_mesh: dict[str, int] = defaultdict(int)
    final_status_counts: dict[str, int] = defaultdict(int)

    for elapsed_sec in range(0, total_seconds, time_step_sec):
        current_time_sec = elapsed_sec
        current_time_min = start_min + elapsed_sec // 60
        scheduled_spawn = spawn_schedule.get(elapsed_sec, 0)
        if scheduled_spawn > 0:
            room = max(0, max_active_vehicles - len(active))
            spawn_count = min(scheduled_spawn, room)
            dropped_spawn_count += scheduled_spawn - spawn_count
            next_vehicle_id, spawned, spawned_packets = spawn_vehicles(
                active=active,
                source_sampler=source_sampler,
                rng=rng,
                spawn_count=spawn_count,
                next_vehicle_id=next_vehicle_id,
                time_sec=current_time_sec,
                spawn_stats_by_category=spawn_stats_by_category,
                spawn_stats_by_edge=spawn_stats_by_edge,
                spawn_stats_by_mesh=spawn_stats_by_mesh,
                vehicle_packet_size=vehicle_packet_size,
            )
            total_spawned += spawned
            total_spawn_packets += spawned_packets

        next_active: list[RoadDbVehicle] = []
        for vehicle in active:
            if current_time_sec - vehicle.birth_time_sec > max_vehicle_age_sec:
                completed_traces.append(vehicle_to_trace(vehicle, "max_age", current_time_sec))
                final_status_counts["max_age"] += 1
                continue
            final_status = move_vehicle_one_step(
                vehicle=vehicle,
                network=network,
                observations_by_edge=observations_by_edge,
                counts=counts,
                current_time_sec=current_time_sec,
                current_time_min=current_time_min,
                time_step_sec=time_step_sec,
                rng=rng,
                theta=theta,
                epsilon=epsilon,
            )
            if final_status:
                completed_traces.append(vehicle_to_trace(vehicle, final_status, current_time_sec))
                final_status_counts[final_status] += 1
            else:
                next_active.append(vehicle)
        active = next_active
        active_packet_count = len(active)
        active_weight_count = sum(vehicle.weight for vehicle in active)
        active_packet_samples.append(active_packet_count)
        active_weight_samples.append(active_weight_count)

    for vehicle in active:
        completed_traces.append(vehicle_to_trace(vehicle, "simulation_end", total_seconds))
        final_status_counts["simulation_end"] += 1

    return {
        "counts": counts,
        "vehicle_traces": completed_traces,
        "summary": {
            "start_min": start_min,
            "duration_min": duration_min,
            "time_step_sec": time_step_sec,
            "generation_multiplier": generation_multiplier,
            "max_spawn_per_bin": max_spawn_per_bin,
            "max_active_vehicles": max_active_vehicles,
            "vehicle_packet_size": max(1, int(vehicle_packet_size)),
            "spawn_timing": spawn_timing,
            "scheduled_spawn_events": len(spawn_schedule),
            "scheduled_spawn_count": total_scheduled_spawn,
            "spawned_count": total_spawned,
            "spawn_packet_count": total_spawn_packets,
            "dropped_spawn_count": dropped_spawn_count,
            "active_packet_avg": sum(active_packet_samples) / len(active_packet_samples) if active_packet_samples else 0.0,
            "active_packet_max": max(active_packet_samples) if active_packet_samples else 0,
            "active_vehicle_weight_avg": sum(active_weight_samples) / len(active_weight_samples) if active_weight_samples else 0.0,
            "active_vehicle_weight_max": max(active_weight_samples) if active_weight_samples else 0,
            "active_vehicle_avg": sum(active_packet_samples) / len(active_packet_samples) if active_packet_samples else 0.0,
            "active_vehicle_max": max(active_packet_samples) if active_packet_samples else 0,
            "vehicle_trace_count": len(completed_traces),
            "observation_event_count": sum(len(trace["observation_trace"]) for trace in completed_traces),
            "observation_event_weight_sum": sum(
                int(event.get("weight", 1))
                for trace in completed_traces
                for event in trace["observation_trace"]
            ),
            "branch_event_count": sum(len(trace["branch_trace"]) for trace in completed_traces),
            "final_status_counts": dict(final_status_counts),
            "spawn_stats_by_category": dict(spawn_stats_by_category),
            "spawn_stats_by_mesh": dict(spawn_stats_by_mesh),
            "top_spawn_edges": sorted(
                spawn_stats_by_edge.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:20],
            "top_spawn_meshes": sorted(
                spawn_stats_by_mesh.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:20],
        },
    }


def move_vehicle_one_step(
    *,
    vehicle: RoadDbVehicle,
    network: RoadDbNetwork,
    observations_by_edge: dict[str, list[ObservationMatch]],
    counts: dict[tuple[int, str], int],
    current_time_sec: int,
    current_time_min: int,
    time_step_sec: int,
    rng: random.Random,
    theta: dict[str, float],
    epsilon: float,
) -> str | None:
    """1台の車両を1 timestep 進める。終了した場合は終了理由を返す。"""

    remaining_distance = network.edge_speed_mps(vehicle.directed_edge_id) * time_step_sec
    transition_count = 0
    while remaining_distance > 0:
        edge_id = vehicle.directed_edge_id
        edge_length = network.edge_length(edge_id)
        previous_position = vehicle.position_meter
        next_position = min(edge_length, previous_position + remaining_distance)
        record_crossings(
            vehicle=vehicle,
            observations_by_edge=observations_by_edge,
            counts=counts,
            edge_id=edge_id,
            previous_position=previous_position,
            next_position=next_position,
            current_time_sec=current_time_sec,
            current_time_min=current_time_min,
        )
        traveled = next_position - previous_position
        remaining_distance -= max(0.0, traveled)
        vehicle.position_meter = next_position
        if vehicle.position_meter < edge_length:
            return None

        next_edge_id, probability = network.choose_next_edge(edge_id, theta, rng, epsilon)
        if not next_edge_id:
            return "no_next_edge"

        edge = network.directed_edges[edge_id]
        vehicle.branch_trace.append(
            {
                "time_sec": current_time_sec,
                "time_min": current_time_min,
                "node_id": edge["to_node_id"],
                "incoming_directed_edge_id": edge_id,
                "outgoing_directed_edge_id": next_edge_id,
                "probability": probability,
            }
        )
        vehicle.directed_edge_id = next_edge_id
        vehicle.position_meter = 0.0
        transition_count += 1
        if transition_count > 8:
            return None
    return None

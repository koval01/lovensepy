"""
Socket API integration demo scenarios and helpers.

Orchestration helpers for integration tests. They call the public library API.
"""

from __future__ import annotations

import asyncio
import math
import secrets
from typing import Any, Callable

from lovensepy import SocketAPIClient, features_for_toy


def log(msg: str) -> None:
    print(msg, flush=True)


def _build_toy_feature_sequence(toys: dict[str, Any]) -> list[tuple[str, str]]:
    sequence: list[tuple[str, str]] = []
    for tid, t in toys.items():
        for feat in features_for_toy(t):
            sequence.append((tid, feat))
    return sequence


def _stop_action_for_toy(toys: dict[str, Any], toy_id: str) -> str:
    return ",".join(f"{feature}:0" for feature in features_for_toy(toys[toy_id]))


def _toy_targets(toys: dict[str, Any]) -> list[tuple[str, str]]:
    return [(toy_id, feature) for toy_id, toy in toys.items() for feature in features_for_toy(toy)]


def _announce_wave_step(
    toys: dict[str, Any],
    toy_id: str,
    feature: str,
    index: int,
    total: int,
    log_fn: Callable[[str], None],
) -> None:
    toy_name = toys[toy_id].get("name") or toy_id
    log_fn(f"    [{index}/{total}] {toy_name} — {feature}")


async def _play_sine_feature(
    client: SocketAPIClient,
    toys: dict[str, Any],
    toy_id: str,
    feature: str,
    *,
    duration_sec: float,
    num_steps: int,
    stop_prev_first: bool,
) -> None:
    interval_sec = duration_sec / num_steps
    stop_prev = stop_prev_first
    for i in range(num_steps + 1):
        t = (i / num_steps) * duration_sec
        level = max(0, min(20, int(10 + 10 * math.sin(math.pi * t))))
        client.send_command(
            "Function",
            f"{feature}:{level}",
            time_sec=0,
            toy=toy_id,
            stop_previous=1 if stop_prev else 0,
        )
        stop_prev = False
        await asyncio.sleep(interval_sec)

    await asyncio.sleep(0.15)
    await client.send_command_await(
        "Function",
        _stop_action_for_toy(toys, toy_id),
        time_sec=0,
        toy=toy_id,
    )


async def _play_sine_combo(
    client: SocketAPIClient,
    toys: dict[str, Any],
    targets: list[tuple[str, str]],
    *,
    duration_sec: float,
    num_steps: int,
) -> None:
    rng = secrets.SystemRandom()
    phases = {target: rng.uniform(0, 2 * math.pi) for target in targets}
    by_toy: dict[str, list[str]] = {}
    for toy_id, feature in targets:
        by_toy.setdefault(toy_id, []).append(feature)

    interval = duration_sec / num_steps
    last_toy_id: str | None = None
    for i in range(num_steps + 1):
        t_norm = i / num_steps
        levels = {
            (toy_id, feature): max(
                0,
                min(20, int(10 + 10 * math.sin(math.pi * t_norm + phases[(toy_id, feature)]))),
            )
            for toy_id, feature in targets
        }
        for toy_id, features in by_toy.items():
            action = ",".join(f"{feature}:{levels[(toy_id, feature)]}" for feature in features)
            stop_prev = toy_id != last_toy_id
            client.send_command(
                "Function",
                action,
                time_sec=0,
                toy=toy_id,
                stop_previous=1 if stop_prev else 0,
            )
            last_toy_id = toy_id
        await asyncio.sleep(interval)

    await asyncio.sleep(0.15)
    for toy_id in by_toy:
        await client.send_command_await(
            "Function",
            _stop_action_for_toy(toys, toy_id),
            time_sec=0,
            toy=toy_id,
        )


async def _play_per_feature_wave(
    client: SocketAPIClient,
    toys: dict[str, Any],
    sequence: list[tuple[str, str]],
    *,
    feature_duration_sec: float,
    num_steps: int,
    log_fn: Callable[[str], None],
) -> None:
    log_fn(f"\n>>> 1. Per-motor sine wave ({feature_duration_sec}s each) — {len(sequence)} steps:")
    last_toy_id: str | None = None
    for index, (toy_id, feature) in enumerate(sequence, start=1):
        _announce_wave_step(toys, toy_id, feature, index, len(sequence), log_fn)
        await _play_sine_feature(
            client,
            toys,
            toy_id,
            feature,
            duration_sec=feature_duration_sec,
            num_steps=num_steps,
            stop_prev_first=(toy_id != last_toy_id),
        )
        last_toy_id = toy_id
        await asyncio.sleep(0.3)


async def _play_combo_phases(
    client: SocketAPIClient,
    toys: dict[str, Any],
    *,
    combo_duration_sec: float,
    num_steps: int,
    log_fn: Callable[[str], None],
) -> None:
    all_targets = _toy_targets(toys)
    if len(all_targets) < 2:
        return

    toy_list = list(toys.items())
    two_motor_toys = [(toy_id, toy) for toy_id, toy in toys.items() if len(features_for_toy(toy)) >= 2]
    if two_motor_toys:
        toy_id, toy = two_motor_toys[0]
        features = features_for_toy(toy)[:2]
        log_fn(
            f"\n>>> 2. Two motors together ({toy.get('name') or toy_id}: {features}) — "
            f"{combo_duration_sec}s, random phases:"
        )
        await _play_sine_combo(
            client,
            toys,
            [(toy_id, feature) for feature in features],
            duration_sec=combo_duration_sec,
            num_steps=num_steps,
        )
        await asyncio.sleep(0.5)

    if len(toy_list) >= 2:
        (toy1_id, toy1), (toy2_id, toy2) = toy_list[:2]
        targets = [(toy1_id, features_for_toy(toy1)[0]), (toy2_id, features_for_toy(toy2)[0])]
        log_fn(
            f"\n>>> 3. Two toys together ({toy1.get('name') or toy1_id}, {toy2.get('name') or toy2_id}) — "
            f"{combo_duration_sec}s, random phases:"
        )
        await _play_sine_combo(
            client,
            toys,
            targets,
            duration_sec=combo_duration_sec,
            num_steps=num_steps,
        )
        await asyncio.sleep(0.5)

    log_fn(f"\n>>> 4. All motors together — {combo_duration_sec}s, random phases:")
    await _play_sine_combo(
        client,
        toys,
        all_targets,
        duration_sec=combo_duration_sec,
        num_steps=num_steps,
    )
    await asyncio.sleep(0.5)


async def run_socket_function_demo(
    client: SocketAPIClient,
    toys: dict[str, Any],
    *,
    feature_duration_sec: float = 5.0,
    num_steps: int = 100,
    combo_duration_sec: float = 4.0,
    log_fn: Callable[[str], None] = log,
) -> None:
    """Sine wave + combos demo executed via SocketAPIClient.send_command calls."""
    sequence = _build_toy_feature_sequence(toys)
    await _play_per_feature_wave(
        client,
        toys,
        sequence,
        feature_duration_sec=feature_duration_sec,
        num_steps=num_steps,
        log_fn=log_fn,
    )
    await _play_combo_phases(
        client,
        toys,
        combo_duration_sec=combo_duration_sec,
        num_steps=num_steps,
        log_fn=log_fn,
    )

    await asyncio.sleep(0.2)
    for toy_id in toys:
        await client.send_command_await(
            "Function",
            _stop_action_for_toy(toys, toy_id),
            time_sec=0,
            toy=toy_id,
        )
    log_fn(">>> Done.")


"""
LAN/Game-Mode integration demo scenarios and helpers.

These are orchestration helpers for integration tests. They call the public library
API and intentionally do not assert protocol correctness.
"""

from __future__ import annotations

import math
import os
import secrets
import time
from typing import Any, Callable

from lovensepy import LANClient, SyncPatternPlayer, features_for_toy
from lovensepy._models import GetToysResponse


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_lan_toys(resp: GetToysResponse | None) -> dict[str, dict[str, Any]]:
    """Normalize typed GetToysResponse into {toy_id: toy_dict}."""
    toys: dict[str, dict[str, Any]] = {}
    if not resp or resp.data is None:
        return toys
    for toy in resp.data.toys:
        toys[str(toy.id)] = toy.model_dump()
    return toys


def lan_verify_ssl_from_env() -> bool:
    return os.environ.get("LOVENSE_VERIFY_SSL", "0").lower() in ("1", "true", "yes")


def build_lan_client_from_env(app_name: str) -> LANClient:
    """Build LANClient from env vars used by integration tests."""
    ip = os.environ["LOVENSE_LAN_IP"]
    https_port = os.environ.get("LOVENSE_LAN_HTTPS_PORT")
    port = int(os.environ.get("LOVENSE_LAN_PORT", "20011"))
    verify_ssl = lan_verify_ssl_from_env()

    if https_port:
        return LANClient(
            app_name,
            ip,
            use_https=True,
            ssl_port=int(https_port),
            verify_ssl=verify_ssl,
        )

    # Lovense Remote: 20011 is HTTP, 30011 is HTTPS.
    if port == 30011:
        return LANClient(app_name, ip, use_https=True, ssl_port=port, verify_ssl=verify_ssl)

    return LANClient(app_name, ip, port=port)


def build_toy_feature_sequence(toys: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    sequence: list[tuple[str, str]] = []
    for tid, t in toys.items():
        for feat in features_for_toy(t):
            sequence.append((tid, feat))
    return sequence


def _toy_name(toy: dict[str, Any], fallback: str) -> str:
    return toy.get("name") or toy.get("nickName") or fallback


def _stop_all_features(toys: dict[str, dict[str, Any]], toy_id: str) -> dict[str, int]:
    return {feature: 0 for feature in features_for_toy(toys[toy_id])}


def _log_toy_inventory(
    toys: dict[str, dict[str, Any]],
    *,
    header: str,
    log_fn: Callable[[str], None],
) -> None:
    log_fn(header)
    for toy_id, toy in toys.items():
        name = _toy_name(toy, "—")
        model = toy.get("toyType") or name
        log_fn(f"    {toy_id}: {name} ({model}) — {features_for_toy(toy)}")


def _play_player_sequence(
    player: SyncPatternPlayer,
    toys: dict[str, dict[str, Any]],
    sequence: list[tuple[str, str]],
    *,
    feature_duration_sec: float,
    log_fn: Callable[[str], None],
) -> None:
    log_fn(f"\n>>> 1. Per-motor sine wave ({feature_duration_sec}s each) — {len(sequence)} steps:")
    last_toy_id: str | None = None
    for index, (toy_id, feature) in enumerate(sequence, start=1):
        log_fn(f"    [{index}/{len(sequence)}] {_toy_name(toys[toy_id], toy_id)} — {feature}")
        player.play_sine_wave(
            toy_id,
            feature,
            duration_sec=feature_duration_sec,
            stop_prev_first=(toy_id != last_toy_id),
        )
        last_toy_id = toy_id
        time.sleep(0.3)


def _stop_player_for_all_toys(
    player: SyncPatternPlayer,
    toys: dict[str, dict[str, Any]],
    *,
    delay_sec: float = 0.2,
) -> None:
    time.sleep(delay_sec)
    for toy_id in toys:
        player.stop(toy_id)


def run_sync_pattern_player_demo(
    player: SyncPatternPlayer,
    toys: dict[str, dict[str, Any]],
    *,
    feature_duration_sec: float = 5.0,
    combo_duration_sec: float = 4.0,
    log_fn: Callable[[str], None] = log,
) -> None:
    """Sine wave + combos demo executed via SyncPatternPlayer."""
    sequence = build_toy_feature_sequence(toys)
    _log_toy_inventory(
        toys,
        header=f"\n>>> [LOCAL ONLY] {len(toys)} toy(s) via SyncPatternPlayer:",
        log_fn=log_fn,
    )
    _play_player_sequence(
        player,
        toys,
        sequence,
        feature_duration_sec=feature_duration_sec,
        log_fn=log_fn,
    )

    toy_list = list(toys.items())
    all_targets = [(tid, f) for tid, t in toys.items() for f in features_for_toy(t)]
    if len(all_targets) < 2:
        _stop_player_for_all_toys(player, toys)
        log_fn(">>> Done.")
        return

    if len(all_targets) >= 2:
        two_motor_toys = [(tid, t) for tid, t in toys.items() if len(features_for_toy(t)) >= 2]
        if two_motor_toys:
            tid, t = two_motor_toys[0]
            feats = features_for_toy(t)[:2]
            targets_2m = [(tid, f) for f in feats]
            name = t.get("name") or t.get("nickName") or tid
            log_fn(
                f"\n>>> 2. Two motors together ({name}: {feats}) — {combo_duration_sec}s:"
            )
            player.play_combo(targets_2m, duration_sec=combo_duration_sec)
            time.sleep(0.5)

        if len(toy_list) >= 2:
            t1_id, t1 = toy_list[0]
            t2_id, t2 = toy_list[1]
            f1, f2 = features_for_toy(t1)[0], features_for_toy(t2)[0]
            n1, n2 = t1.get("name") or t1_id, t2.get("name") or t2_id
            log_fn(f"\n>>> 3. Two toys together ({n1}, {n2}) — {combo_duration_sec}s:")
            player.play_combo([(t1_id, f1), (t2_id, f2)], duration_sec=combo_duration_sec)
            time.sleep(0.5)

        log_fn(f"\n>>> 4. All motors together — {combo_duration_sec}s:")
        player.play_combo(all_targets, duration_sec=combo_duration_sec)
        time.sleep(0.5)

    _stop_player_for_all_toys(player, toys)
    log_fn(">>> Done.")


def run_lan_function_demo(
    client: LANClient,
    toys: dict[str, dict[str, Any]],
    *,
    feature_duration_sec: float = 5.0,
    num_steps: int = 100,
    combo_duration_sec: float = 4.0,
    log_fn: Callable[[str], None] = log,
) -> None:
    """Sine wave + combos demo executed via LANClient.function_request."""
    sequence = build_toy_feature_sequence(toys)
    _log_toy_inventory(toys, header=f"\n>>> Detected {len(toys)} toy(s):", log_fn=log_fn)

    interval = feature_duration_sec / num_steps
    log_fn(
        f"\n>>> 1. Per-motor sine wave ({feature_duration_sec}s each) — {len(sequence)} steps:"
    )
    last_toy_id: str | None = None
    for idx, (tid, feat) in enumerate(sequence):
        name = toys[tid].get("name") or toys[tid].get("nickName") or tid
        log_fn(f"    [{idx + 1}/{len(sequence)}] {name} — {feat}")
        feats = features_for_toy(toys[tid])
        stop_prev = tid != last_toy_id
        for i in range(num_steps + 1):
            t = (i / num_steps) * feature_duration_sec
            level = int(10 + 10 * math.sin(math.pi * t))
            level = max(0, min(20, level))
            action = {f: (level if f == feat else 0) for f in feats}
            client.function_request(action, time=0, toy_id=tid, stop_previous=stop_prev)
            stop_prev = False
            time.sleep(interval)
        last_toy_id = tid
        time.sleep(0.15)
        client.function_request(_stop_all_features(toys, tid), time=0, toy_id=tid)
        time.sleep(0.3)

    rng = secrets.SystemRandom()
    all_targets = [(tid, f) for tid, t in toys.items() for f in features_for_toy(t)]
    toy_list = list(toys.items())
    if len(all_targets) >= 2:
        two_motor_toys = [(tid, t) for tid, t in toys.items() if len(features_for_toy(t)) >= 2]
        if two_motor_toys:
            tid, t = two_motor_toys[0]
            feats = features_for_toy(t)[:2]
            targets_2m = [(tid, f) for f in feats]
            name = t.get("name") or t.get("nickName") or tid
            log_fn(
                f"\n>>> 2. Two motors together ({name}: {feats}) — {combo_duration_sec}s, random phases:"
            )
            phases = {t: rng.uniform(0, 2 * math.pi) for t in targets_2m}
            for i in range(num_steps + 1):
                t_norm = i / num_steps
                levels = {
                    t: max(0, min(20, int(10 + 10 * math.sin(math.pi * t_norm + phases[t]))))
                    for t in targets_2m
                }
                action = {f: levels[(tid, f)] for f in feats}
                client.function_request(action, time=0, toy_id=tid, stop_previous=False)
                time.sleep(combo_duration_sec / num_steps)
            time.sleep(0.15)
            client.function_request(_stop_all_features(toys, tid), time=0, toy_id=tid)
            time.sleep(0.5)

        if len(toy_list) >= 2:
            t1_id, t1 = toy_list[0]
            t2_id, t2 = toy_list[1]
            f1, f2 = features_for_toy(t1)[0], features_for_toy(t2)[0]
            n1, n2 = t1.get("name") or t1_id, t2.get("name") or t2_id
            log_fn(
                f"\n>>> 3. Two toys together ({n1}, {n2}) — {combo_duration_sec}s, random phases:"
            )
            targets_2t = [(t1_id, f1), (t2_id, f2)]
            phases = {t: rng.uniform(0, 2 * math.pi) for t in targets_2t}
            last_tid: str | None = None
            for i in range(num_steps + 1):
                t_norm = i / num_steps
                for tid, feat in targets_2t:
                    level = max(
                        0,
                        min(
                            20,
                            int(10 + 10 * math.sin(math.pi * t_norm + phases[(tid, feat)])),
                        ),
                    )
                    stop_prev = tid != last_tid
                    client.function_request({feat: level}, time=0, toy_id=tid, stop_previous=stop_prev)
                    last_tid = tid
                time.sleep(combo_duration_sec / num_steps)
            time.sleep(0.15)
            for tid in (t1_id, t2_id):
                client.function_request(_stop_all_features(toys, tid), time=0, toy_id=tid)
            time.sleep(0.5)

        log_fn(f"\n>>> 4. All motors together — {combo_duration_sec}s, random phases:")
        by_toy: dict[str, list[str]] = {}
        for tid, feat in all_targets:
            by_toy.setdefault(tid, []).append(feat)
        phases = {t: rng.uniform(0, 2 * math.pi) for t in all_targets}
        last_tid_4: str | None = None
        for i in range(num_steps + 1):
            t_norm = i / num_steps
            for tid, feats in by_toy.items():
                levels = {
                    f: max(
                        0,
                        min(
                            20,
                            int(10 + 10 * math.sin(math.pi * t_norm + phases[(tid, f)])),
                        ),
                    )
                    for f in feats
                }
                stop_prev = tid != last_tid_4
                client.function_request(levels, time=0, toy_id=tid, stop_previous=stop_prev)
                last_tid_4 = tid
            time.sleep(combo_duration_sec / num_steps)
        time.sleep(0.15)
        for tid in toys:
            client.function_request(_stop_all_features(toys, tid), time=0, toy_id=tid)
        time.sleep(0.5)

    time.sleep(0.2)
    for tid in toys:
        client.function_request(_stop_all_features(toys, tid), time=0, toy_id=tid)
    log_fn(">>> Done.")


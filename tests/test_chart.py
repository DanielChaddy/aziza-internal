"""Deterministic gate for the Helm chart's load-bearing invariants.

Pure-Python: reads the templates as text. No cluster, no `helm` binary, no network, no DB — so it
runs in the same gate as everything else and holds even where a rendered manifest cannot be
obtained. It asserts the properties whose violation is SILENT: a chart that ships any of these
wrong is accepted by the API server and simply behaves badly.
"""

from __future__ import annotations

import pathlib
import re

from aziza_adk import demo_data, hours, staff_data

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CHART = _ROOT / "deploy" / "helm" / "aziza"


def _code(path: pathlib.Path) -> str:
    """Read a chart file with whole comment lines removed.

    The templates carry comments naming exactly these invariants ("NOT /healthz", "/simulate is the
    route that must stay off it"), so a naive substring search matches the explanation and fails on
    a correct chart.
    """
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


_STS = _code(_CHART / "templates" / "statefulset.yaml")
_ING = _code(_CHART / "templates" / "ingress.yaml")
_CRON = _code(_CHART / "templates" / "cronjob-summary.yaml")
_HELPERS = _code(_CHART / "templates" / "_helpers.tpl")
_VALUES = _code(_CHART / "values.yaml")


# --- the probe split ---------------------------------------------------------
# /healthz round-trips the database. Liveness on it turns a Postgres blip into CrashLoopBackOff
# whose backoff grows to five minutes, so the webhook stays down AFTER Postgres recovers.


def test_startup_and_liveness_do_not_target_healthz() -> None:
    assert "readinessProbe:" in _STS
    assert "/healthz" not in _STS.split("readinessProbe:")[0]


def test_readiness_does_target_healthz() -> None:
    assert "/healthz" in _STS.split("readinessProbe:")[1]


def test_readiness_timeout_exceeds_the_platform_health_budget() -> None:
    """channel_telegram/webhook.py allows HEALTH_TIMEOUT_S = 2.0, so the k8s default of 1s flaps."""
    assert "timeoutSeconds: 4" in _STS.split("readinessProbe:")[1]


# --- at most one process -----------------------------------------------------
# channel_telegram/dedupe.py:17 and locks.py:12 are module-level and loop-local. A second replica
# re-runs a retried turn and stops serializing a sender's turns, both without any error.


def test_webhook_is_a_statefulset_not_a_deployment() -> None:
    assert "kind: StatefulSet" in _STS
    assert "kind: Deployment" not in _STS


def test_replica_count_is_one_and_not_a_value() -> None:
    assert "replicas: 1" in _STS
    assert ".Values" not in _STS.split("replicas:")[1].split("\n")[0]


def test_termination_grace_outlives_a_capped_turn() -> None:
    """config.py caps a turn at 60s; a shorter grace SIGKILLs mid-turn after the 200 went out."""
    assert "terminationGracePeriodSeconds: 75" in _STS


# --- what the internet can reach --------------------------------------------


def test_simulate_is_not_routed() -> None:
    """/simulate runs a turn as any sender it is given and authenticates nobody."""
    assert "/simulate" not in _ING


def test_ingress_is_an_allowlist_with_no_catch_all() -> None:
    for path in ("/webhook", "/healthz", "/health"):
        assert f'"{path}"' in _ING or f"path: {path}" in _ING
    assert 'path: "/"' not in _ING
    assert "\n          - path: /\n" not in _ING


# --- the deployed artifact is identifiable -----------------------------------


def test_an_empty_image_tag_fails_the_render() -> None:
    """Without this a rollback names :latest, which pins no artifact."""
    assert "fail" in _HELPERS
    assert "image.tag is required" in _HELPERS


def test_values_ships_no_default_tag() -> None:
    assert 'tag: ""' in _VALUES


# --- secrets are never rendered ---------------------------------------------
# The chart references an out-of-band Secret by name, so `helm template` and `helm get manifest`
# cannot leak a credential.


def test_no_secret_value_appears_in_the_chart() -> None:
    for path in _CHART.rglob("*"):
        if not path.is_file():
            continue
        body = path.read_text(encoding="utf-8")
        for key in ("GOOGLE_API_KEY:", "TELEGRAM_BOT_TOKEN:", "TELEGRAM_WEBHOOK_SECRET:"):
            assert key not in body, f"{path.name} names {key}"


def test_no_workload_mounts_a_service_account_token() -> None:
    for body in (_STS, _CRON):
        assert "automountServiceAccountToken: false" in body


# --- the end-of-day message -------------------------------------------------


def test_summary_declares_the_salon_timezone_rather_than_converting() -> None:
    assert "timeZone:" in _CRON


#: cron counts Sunday as 0; `date.weekday()` counts Monday as 0.
_CRON_TO_WEEKDAY = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}


def _scheduled() -> dict[int, int]:
    """{weekday: hour} the end-of-day message is scheduled for, read off values.yaml."""
    fires: dict[int, int] = {}
    for line in _VALUES.splitlines():
        if not (m := re.search(r'"(\d+) (\d+) \* \* ([0-9,-]+)"', line)):
            continue
        hour, days = int(m.group(2)), m.group(3)
        for part in days.split(","):
            lo, _, hi = part.partition("-")
            for cron_day in range(int(lo), int(hi or lo) + 1):
                fires[_CRON_TO_WEEKDAY[cron_day]] = hour
    return fires


def test_the_summary_fires_when_the_recording_window_shuts() -> None:
    """The schedule and `hours.SCHEDULE` are two statements of one fact, and a drift between them
    is silent: the message would go out while entries could still arrive, or an hour late."""
    fires = _scheduled()
    expected = {
        day: closes + int(hours.GRACE.total_seconds() // 3600)
        for day, (_, closes) in hours.SCHEDULE.items()
    }
    assert fires == expected


def test_nothing_is_scheduled_on_a_day_the_salon_is_shut() -> None:
    """Sunday and Monday have no day to report."""
    assert set(_scheduled()) == set(hours.SCHEDULE)


def test_the_summary_sends_and_everyone_registered_can_receive() -> None:
    """`live` attempts a send to whoever the seed registers, and an invented id sends nowhere —
    while `simulate` writes no claim, so the day would still read as unreported."""
    assert "sendMode: live" in _VALUES
    invented = {p["telegram_user_id"] for p in demo_data.SPECIALISTS}
    assert not {p["telegram_user_id"] for p in staff_data.STAFF} & invented

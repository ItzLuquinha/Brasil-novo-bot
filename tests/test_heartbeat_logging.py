from __future__ import annotations

import ast
import logging
import time
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _heartbeat_failure_method():
    source = ast.parse((ROOT / "app/tasks/worker.py").read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "_report_heartbeat_failure"
    )
    function.decorator_list = []
    function.returns = None
    for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
        argument.annotation = None
    namespace = {"time": time, "logger": logging.getLogger("bn_bot.tasks")}
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, "heartbeat_failure_test.py", "exec"), namespace)
    return namespace[function.name]


def _worker_for_test():
    worker = SimpleNamespace(
        _heartbeat_failure_started_at=None,
        _heartbeat_last_warning_at=0.0,
        _heartbeat_suppressed_failures=0,
        HEARTBEAT_WARNING_INTERVAL_SECONDS=300.0,
    )
    worker._report_heartbeat_failure = MethodType(_heartbeat_failure_method(), worker)
    return worker


def test_heartbeat_logs_are_throttled_during_continuous_redis_outage(monkeypatch, caplog) -> None:
    worker = _worker_for_test()
    clock = {"now": 10.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    with caplog.at_level(logging.WARNING, logger="bn_bot.tasks"):
        worker._report_heartbeat_failure("TimeoutError")
        clock["now"] = 40.0
        worker._report_heartbeat_failure("TimeoutError")
        clock["now"] = 70.0
        worker._report_heartbeat_failure("TimeoutError")

    records = [record for record in caplog.records if record.name == "bn_bot.tasks"]
    assert len(records) == 1
    assert worker._heartbeat_suppressed_failures == 2


def test_heartbeat_emits_periodic_summary_and_counts_suppressed_failures(monkeypatch, caplog) -> None:
    worker = _worker_for_test()
    clock = {"now": 10.0}
    monkeypatch.setattr(time, "monotonic", lambda: clock["now"])

    with caplog.at_level(logging.WARNING, logger="bn_bot.tasks"):
        worker._report_heartbeat_failure("TimeoutError")
        clock["now"] = 40.0
        worker._report_heartbeat_failure("TimeoutError")
        clock["now"] = 311.0
        worker._report_heartbeat_failure("TimeoutError")

    records = [record for record in caplog.records if record.name == "bn_bot.tasks"]
    assert len(records) == 2
    assert "suppressed_repeats=1" in records[-1].getMessage()

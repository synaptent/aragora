"""Source-checkout declarations read with a TOML library and without one (Python 3.10 without
tomli), the thread-local marker that a declared registration is running, and the retry of a
registration that raised ImportError."""

from __future__ import annotations

import importlib.metadata
import logging
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from aragora.utils import declared_registrations
from aragora.utils.declared_registrations import SOURCE_PYPROJECT, DeclaredRegistrations

FIXTURE = """\
[project]
name = "aragora"  # the distribution
readme = {text = '''
[project.entry-points."demo.group"]
hidden = "inside.the.readme:register"
''', content-type = "text/markdown"}
dependencies = [
    "aiohttp>=3.9",
]

[[tool.example.items]]
name = "not-the-project"

[project.entry-points."demo.group"]
first = "pkg.first:register"
'second' = 'pkg.second:register'  # single-quoted

[project.entry-points.'other.group']
other = "pkg.other:register"
"""

HAS_TOML = sys.version_info >= (3, 11) or declared_registrations._toml_module() is not None


@pytest.fixture(params=["toml-library", "no-toml-library"])
def reader(request, monkeypatch):
    if request.param == "toml-library":
        if not HAS_TOML:
            pytest.skip("no TOML library on this interpreter")
    else:
        monkeypatch.setattr(declared_registrations, "_toml_module", lambda: None)
    return request.param


def _declared(group, path):
    return [
        (ep.name, ep.value, ep.group)
        for ep in DeclaredRegistrations(group, source_pyproject=path)._source_declarations()
    ]


def test_both_readers_return_the_group_entries_in_file_order(reader, tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text(FIXTURE, encoding="utf-8")

    assert _declared("demo.group", path) == [
        ("first", "pkg.first:register", "demo.group"),
        ("second", "pkg.second:register", "demo.group"),
    ]
    assert _declared("other.group", path) == [("other", "pkg.other:register", "other.group")]
    assert _declared("absent.group", path) == []


def test_both_readers_ignore_another_distribution(reader, tmp_path):
    path = tmp_path / "pyproject.toml"
    path.write_text(FIXTURE.replace('name = "aragora"', 'name = "other"'), encoding="utf-8")

    assert _declared("demo.group", path) == []


@pytest.mark.skipif(not HAS_TOML, reason="needs a TOML library for the reference reading")
def test_without_a_toml_library_every_aragora_group_reads_the_same(monkeypatch):
    toml = declared_registrations._toml_module()
    assert toml is not None
    project = toml.loads(SOURCE_PYPROJECT.read_text(encoding="utf-8"))["project"]
    groups = sorted(g for g in project.get("entry-points", {}) if g.startswith("aragora."))
    assert groups, "aragora's pyproject declares no entry-point groups"
    with_library = {group: _declared(group, SOURCE_PYPROJECT) for group in groups}

    monkeypatch.setattr(declared_registrations, "_toml_module", lambda: None)

    assert {group: _declared(group, SOURCE_PYPROJECT) for group in groups} == with_library
    assert all(with_library.values())


def _running():
    return declared_registrations.declared_registrations_running()


def _declare(monkeypatch, registrations):
    """Serve ``registrations`` (group -> registration callable) as installed entry points."""
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            [
                SimpleNamespace(
                    name=group, value=f"tests.declared:{group}", load=lambda: registrations[group]
                )
            ]
            if group in registrations
            else []
        ),
    )


def test_declared_registrations_running_spans_nested_loads_on_this_thread_only(
    monkeypatch, tmp_path
):
    seen = []
    outer = DeclaredRegistrations("demo.outer", source_pyproject=tmp_path / "missing.toml")
    inner = DeclaredRegistrations("demo.inner", source_pyproject=tmp_path / "missing.toml")

    def register_outer():
        inner.load()
        seen.append(("outer, after the inner load", _running()))
        other = threading.Thread(target=lambda: seen.append(("another thread", _running())))
        other.start()
        other.join()

    def register_inner():
        seen.append(("inner", _running()))

    _declare(monkeypatch, {"demo.outer": register_outer, "demo.inner": register_inner})

    assert _running() is False
    outer.load()
    assert seen == [
        ("inner", True),
        ("outer, after the inner load", True),
        ("another thread", False),
    ]
    assert _running() is False


def test_declared_registrations_running_ends_when_a_registration_error_escapes(
    monkeypatch, tmp_path
):
    class PluginBug(Exception):
        pass

    def broken():
        raise PluginBug("plugin defect")

    _declare(monkeypatch, {"demo.broken": broken})

    with pytest.raises(PluginBug):
        DeclaredRegistrations("demo.broken", source_pyproject=tmp_path / "missing.toml").load()
    assert _running() is False


def _serve(monkeypatch, group, loads):
    """Serve ``loads`` (entry-point name -> its ``load``) as the installed entry points of ``group``."""
    entry_points = [
        SimpleNamespace(name=name, value=f"tests.declared:{name}", load=load)
        for name, load in loads.items()
    ]
    served = group
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: entry_points if group == served else [],
    )


def _loader(tmp_path, group):
    return DeclaredRegistrations(group, source_pyproject=tmp_path / "missing.toml")


class Flaky:
    """A registration whose module import (``stage="import"``) or call (``stage="call"``) raises
    ImportError while ``blocked``."""

    def __init__(self, stage="call"):
        self.stage = stage
        self.blocked = True
        self.attempts = 0
        self.registered = 0

    def load(self):
        if self.stage == "import":
            self.attempts += 1
            if self.blocked:
                raise ImportError("blocked module")
        return self.register

    def register(self):
        if self.stage == "call":
            self.attempts += 1
            if self.blocked:
                raise ImportError("blocked dependency")
        self.registered += 1


@pytest.mark.parametrize("stage", ["import", "call"])
def test_a_registration_that_raised_import_error_runs_again_on_the_next_load(
    monkeypatch, tmp_path, stage
):
    ok = []
    flaky = Flaky(stage)
    _serve(monkeypatch, "demo.retry", {"ok": lambda: lambda: ok.append("ok"), "flaky": flaky.load})
    declared = _loader(tmp_path, "demo.retry")

    declared.load()
    assert (len(ok), flaky.attempts, flaky.registered) == (1, 1, 0)
    declared.load()
    assert (len(ok), flaky.attempts, flaky.registered) == (1, 2, 0)

    flaky.blocked = False
    declared.load()
    assert (len(ok), flaky.attempts, flaky.registered) == (1, 3, 1)
    declared.load()
    assert (len(ok), flaky.attempts, flaky.registered) == (1, 3, 1)
    assert declared.loaded


@pytest.mark.parametrize(
    "error",
    [AttributeError, LookupError, OSError, RuntimeError, SyntaxError, TypeError, ValueError],
)
def test_a_registration_that_failed_with_another_error_runs_only_once(monkeypatch, tmp_path, error):
    calls = []

    def broken():
        calls.append("broken")
        raise error("registration defect")

    _serve(monkeypatch, "demo.broken", {"broken": lambda: broken})
    declared = _loader(tmp_path, "demo.broken")

    declared.load()
    declared.load()
    assert calls == ["broken"]


def test_an_escaping_error_is_not_retried_and_an_import_error_beside_it_is(monkeypatch, tmp_path):
    class PluginBug(Exception):
        pass

    calls = []

    def broken():
        calls.append("broken")
        raise PluginBug("plugin defect")

    flaky = Flaky()
    _serve(monkeypatch, "demo.mixed", {"broken": lambda: broken, "flaky": flaky.load})
    declared = _loader(tmp_path, "demo.mixed")

    with pytest.raises(PluginBug):
        declared.load()
    assert (calls, flaky.attempts) == (["broken"], 1)

    flaky.blocked = False
    declared.load()
    declared.load()
    assert (calls, flaky.attempts, flaky.registered) == (["broken"], 2, 1)
    assert _running() is False


def test_declared_registrations_running_spans_a_retry_and_ends_when_its_error_escapes(
    monkeypatch, tmp_path
):
    class PluginBug(Exception):
        pass

    seen = []

    def register():
        seen.append(_running())
        if len(seen) == 1:
            raise ImportError("blocked dependency")
        raise PluginBug("defect found on the retry")

    _serve(monkeypatch, "demo.retry", {"flaky": lambda: register})
    declared = _loader(tmp_path, "demo.retry")

    declared.load()
    assert _running() is False
    with pytest.raises(PluginBug):
        declared.load()
    assert seen == [True, True]
    assert _running() is False

    declared.load()
    assert seen == [True, True]


def test_a_registration_that_uses_the_hook_does_not_retry_another_during_the_same_load(
    monkeypatch, tmp_path
):
    flaky = Flaky()
    lookups = []
    declared = _loader(tmp_path, "demo.reentrant")

    def look_up():
        lookups.append(flaky.attempts)
        declared.load()

    _serve(monkeypatch, "demo.reentrant", {"flaky": flaky.load, "user": lambda: look_up})

    declared.load()
    assert (flaky.attempts, lookups) == (1, [1])

    flaky.blocked = False
    declared.load()
    assert (flaky.attempts, flaky.registered, lookups) == (2, 1, [1])


def test_concurrent_loads_retry_a_failed_registration_once(monkeypatch, tmp_path):
    attempts = []

    def register():
        attempts.append(threading.get_ident())
        if len(attempts) == 1:
            raise ImportError("blocked dependency")
        # Hold the lock long enough for the other threads to queue behind this retry.
        time.sleep(0.05)

    _serve(monkeypatch, "demo.threads", {"flaky": lambda: register})
    declared = _loader(tmp_path, "demo.threads")
    declared.load()

    barrier = threading.Barrier(8)

    def look_up():
        barrier.wait()
        declared.load()

    threads = [threading.Thread(target=look_up) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(attempts) == 2


def test_a_registration_that_keeps_raising_import_error_warns_only_the_first_time(
    monkeypatch, tmp_path, caplog
):
    flaky = Flaky()
    _serve(monkeypatch, "demo.quiet", {"flaky": flaky.load})
    declared = _loader(tmp_path, "demo.quiet")

    with caplog.at_level(logging.DEBUG, logger=declared_registrations.__name__):
        for _ in range(3):
            declared.load()

    assert flaky.attempts == 3
    assert [
        record.levelno for record in caplog.records if "tests.declared:flaky" in record.getMessage()
    ] == [logging.WARNING, logging.DEBUG, logging.DEBUG]

"""Source-checkout declarations read with a TOML library and without one (Python 3.10 without
tomli), and the thread-local marker that a declared registration is running."""

from __future__ import annotations

import importlib.metadata
import sys
import threading
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

"""Synthea loader takes its bundle directory from an argument or env var (#422)."""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "load_synthea_to_hapi.py"


@pytest.fixture(scope="module")
def loader():
    spec = importlib.util.spec_from_file_location("load_synthea_to_hapi", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_argument_wins_over_env(loader):
    got = loader.resolve_synthea_dir(["from_arg"], {"SYNTHEA_FHIR_DIR": "from_env"})
    assert got == Path("from_arg")


def test_env_used_when_no_argument(loader):
    got = loader.resolve_synthea_dir([], {"SYNTHEA_FHIR_DIR": "from_env"})
    assert got == Path("from_env")


def test_neither_set_exits_with_clear_message(loader):
    with pytest.raises(SystemExit) as exc:
        loader.resolve_synthea_dir([], {})
    assert "SYNTHEA_FHIR_DIR" in str(exc.value)


def test_empty_env_counts_as_unset(loader):
    with pytest.raises(SystemExit):
        loader.resolve_synthea_dir([], {"SYNTHEA_FHIR_DIR": ""})


def test_cli_without_config_exits_before_any_network_call():
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "SYNTHEA_FHIR_DIR" in result.stderr + result.stdout


def test_script_has_no_user_home_path():
    assert not re.search(r"/Users/[A-Za-z0-9_]+", SCRIPT.read_text())


def test_main_block_passes_argv_and_env_to_loader(monkeypatch, tmp_path):
    import asyncio
    import runpy

    seen = []

    def fake_run(coro):
        seen.append(coro.cr_frame.f_locals["synthea_dir"])
        coro.close()

    monkeypatch.setattr(asyncio, "run", fake_run)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), str(tmp_path / "arg")])
    monkeypatch.setenv("SYNTHEA_FHIR_DIR", str(tmp_path / "env"))
    runpy.run_path(str(SCRIPT), run_name="__main__")
    assert seen == [tmp_path / "arg"]

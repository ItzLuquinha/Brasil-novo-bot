import os
from pathlib import Path

import pytest

from app.core import runtime


def test_runtime_venv_missing_is_clear_on_windows_and_permitted_in_managed_runtimes(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.os, "name", "nt")
    with pytest.raises(SystemExit, match=r".venv não foi encontrado"):
        runtime.ensure_project_venv(tmp_path)
    monkeypatch.setattr(runtime.os, "name", "posix")
    assert runtime.ensure_project_venv(tmp_path) is None


def test_runtime_venv_does_not_reexec_when_already_using_expected_interpreter(tmp_path, monkeypatch):
    venv = tmp_path / ".venv"
    interpreter = venv / (Path("Scripts/python.exe") if os.name == "nt" else Path("bin/python"))
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    monkeypatch.setattr(runtime.sys, "prefix", str(venv))
    monkeypatch.setattr(runtime.os, "name", os.name)
    monkeypatch.setattr(runtime.os, "execv", lambda *args: pytest.fail("não deve reiniciar dentro da .venv"))
    assert runtime.ensure_project_venv(tmp_path) is None

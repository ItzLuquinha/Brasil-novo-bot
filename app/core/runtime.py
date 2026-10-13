from __future__ import annotations

import os
import sys
from pathlib import Path


def ensure_project_venv(project_root: Path) -> None:
    """Re-execute with the project's virtualenv when it exists and is not active."""
    project_root = project_root.absolute()
    venv_root = project_root / ".venv"
    if not venv_root.exists():
        if os.name == "nt":
            raise SystemExit(
                "O ambiente virtual .venv não foi encontrado. Na raiz do projeto, execute "
                '`py -3.12 -m venv .venv` e depois '
                r'`.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`. '
                "Em seguida, rode `python main.py` novamente."
            )
        return

    interpreter = venv_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not interpreter.is_file():
        raise SystemExit(
            f"A pasta .venv existe, mas o interpretador esperado não foi encontrado: {interpreter}. "
            "Recrie o ambiente virtual e reinstale as dependências."
        )

    expected_prefix = os.path.normcase(os.path.abspath(str(venv_root))).casefold()
    current_prefix = os.path.normcase(os.path.abspath(sys.prefix)).casefold()
    try:
        current_prefix_is_venv = os.path.commonpath([expected_prefix, current_prefix]) == expected_prefix
    except ValueError:
        current_prefix_is_venv = False
    if current_prefix_is_venv:
        return

    executable = str(interpreter)
    os.execv(executable, [executable, *sys.argv])

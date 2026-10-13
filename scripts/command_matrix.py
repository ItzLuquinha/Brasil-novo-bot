from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.command_matrix import audit_summary


def main() -> int:
    ok, cases, issues = audit_summary()
    if not ok:
        for issue in issues:
            print(f"FAIL {issue}")
        return 1
    print(f"PASS command matrix: {len(cases)} command handlers audited individually")
    for case in cases:
        print(f"OK /{case.qualified_name} · {case.file}:{case.function} · params={case.parameter_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

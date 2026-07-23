#!/usr/bin/env python3
"""Validate SQL template files before copying into main-gui.

main-gui is known to strip characters like <, <=, <>, >= from SQL and break queries.
Run this on your local .txt templates *before* exporting sales CSVs.

Usage:
  python scripts/validate_main_gui_sql.py sql/main-gui-templates
  python scripts/validate_main_gui_sql.py "D:/path/to/main-gui/templates"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FORBIDDEN_CHARS = ("<", ">")
FORBIDDEN_PATTERNS = [
    (re.compile(r"<="), "<="),
    (re.compile(r">="), ">="),
    (re.compile(r"<>"), "<>"),
    (re.compile(r"TransferType\s+'Order'"), "TransferType 'Order' (corrupted <> operator)"),
    (re.compile(r"GETDATE\(\)\s+0\s+THEN"), "GETDATE() 0 THEN (corrupted < operator)"),
    (re.compile(r"GETDATE\(\)\s+DATEADD"), "GETDATE() DATEADD (missing operator after GETDATE())"),
    (re.compile(r"\brn\s+3\b"), "rn 3 (corrupted <= 3)"),
    (re.compile(r"SampleEnd\s+cw\.SampleStart"), "SampleEnd cw.SampleStart (corrupted comparison)"),
]

TRANSFER_EXCLUSION = re.compile(
    r"(?:NOT\s*\(\s*t\.TransferType\s*=\s*'Order'\s*\)|"
    r"CASE\s+WHEN\s+t\.TransferType\s*=\s*'Order'\s+THEN\s+0\s+ELSE\s+1\s+END\s*=\s*1)"
)

REQUIRED_BY_FILE = {
    "sales 8-30.txt": [
        (re.compile(r"DATEADD\(day,\s*8,\s*ck\.CheckinDate\)\s+AS\s+SampleStart"), "8-30 SampleStart (+8 days)"),
        (re.compile(r"N'8-30'\s+AS\s+WindowType"), "WindowType = 8-30"),
        (re.compile(r"CAST\(GETDATE\(\) AS DATE\) BETWEEN DATEADD"), "safe GETDATE() window check"),
        (re.compile(r"WHERE ck\.rn BETWEEN 1 AND 3"), "safe rn filter"),
    ],
    "sales 30.txt": [
        (re.compile(r"DATEADD\(day,\s*1,\s*ck\.CheckinDate\)\s+AS\s+SampleStart"), "30 SampleStart (+1 day)"),
        (re.compile(r"N'30'\s+AS\s+WindowType"), "WindowType = 30"),
        (re.compile(r"CAST\(GETDATE\(\) AS DATE\) BETWEEN DATEADD"), "safe GETDATE() window check"),
        (re.compile(r"WHERE ck\.rn BETWEEN 1 AND 3"), "safe rn filter"),
    ],
    "sales 15.txt": [
        (re.compile(r"N'15'\s+AS\s+WindowType"), "WindowType = 15"),
        (re.compile(r"CAST\(GETDATE\(\) AS DATE\) BETWEEN DATEADD"), "safe GETDATE() window check"),
        (re.compile(r"WHERE re\.rn BETWEEN 1 AND 3"), "safe rn filter"),
    ],
    "sales 8-30-po-only.txt": [
        (re.compile(r"DATEADD\(day,\s*8,\s*ck\.CheckinDate\)\s+AS\s+SampleStart"), "8-30 SampleStart (+8 days)"),
        (re.compile(r"N'8-30'\s+AS\s+WindowType"), "WindowType = 8-30"),
    ],
}


def strip_sql_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines)


def validate_file(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    sql_body = strip_sql_comments(text)

    for ch in FORBIDDEN_CHARS:
        if ch in sql_body:
            errors.append(f"contains forbidden character {ch!r} (main-gui will corrupt SQL)")

    for pattern, label in FORBIDDEN_PATTERNS:
        if pattern.search(sql_body):
            errors.append(f"matches corrupted pattern: {label}")

    # Two full export queries pasted into one file (common copy-paste mistake).
    if len(re.findall(r"FROM\s+FinalResult\b", sql_body, flags=re.IGNORECASE)) > 1:
        errors.append("contains more than one final SELECT (file may be duplicated)")

    for name, checks in REQUIRED_BY_FILE.items():
        if path.name.lower() == name.lower():
            for pattern, label in checks:
                if not pattern.search(text):
                    errors.append(f"missing required pattern: {label}")

    if path.name.lower() in ("sales 8-30.txt", "sales 30.txt", "sales 15.txt"):
        if not TRANSFER_EXCLUSION.search(text):
            errors.append("missing Transfer exclusion (CASE WHEN ... OR NOT (...))")

    if path.name.lower() == "sales 8-30-po-only.txt" and re.search(r"dbo\.Transfers", text, flags=re.IGNORECASE):
        errors.append("po-only template must not reference dbo.Transfers")

    if path.name.lower() in ("sales 8-30.txt", "sales 30.txt"):
        if "AvgDailyDemand_3Checkins_Avg" not in text:
            errors.append("missing output column AvgDailyDemand_3Checkins_Avg")

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2

    root = Path(argv[1])
    if not root.exists():
        print(f"Path not found: {root}")
        return 2

    files = sorted(root.glob("*.txt"))
    if not files:
        print(f"No .txt files under {root}")
        return 2

    failed = 0
    for path in files:
        errors = validate_file(path)
        if errors:
            failed += 1
            print(f"FAIL  {path.name}")
            for err in errors:
                print(f"      - {err}")
        else:
            print(f"OK    {path.name}")

    if failed:
        print(f"\n{failed} file(s) failed validation.")
        return 1

    print(f"\nAll {len(files)} file(s) look safe for main-gui.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

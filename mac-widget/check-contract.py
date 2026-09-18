#!/usr/bin/env python3
"""
check-contract.py — verify that status.json and the Swift models still agree.

The monitor (Python) and the widget (Swift) meet only at status.json. Nothing in either
language's compiler enforces that contract, so a rename on one side breaks the widget silently
on the user's desktop. This script is that missing check: it reads the JSON keys the Swift
`CodingKeys` decode and compares them with what the published file actually contains.

Run manually, from VS Code ("Validate status.json against the Swift models"), or in CI.

Exit code 0 = the contract holds, 1 = it does not.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
STATUS = REPO / "status.json"
MODELS = HERE / "Models.swift"
TARGETS = REPO / "scraper" / "targets.json"

VALID_STATUSES = {"OPEN", "INTEREST", "CLOSED", "UNKNOWN", "ERROR"}


def coding_keys(struct_name: str) -> dict:
    """Extract `case swiftName = "json_key"` pairs from a struct's CodingKeys enum."""
    text = MODELS.read_text(encoding="utf-8")
    if "struct %s" % struct_name not in text:
        raise SystemExit("Models.swift has no struct %s" % struct_name)
    block = text.split("struct %s" % struct_name, 1)[1]
    if "enum CodingKeys" not in block:
        raise SystemExit("struct %s has no CodingKeys enum" % struct_name)
    body = block.split("enum CodingKeys", 1)[1].split("}", 1)[0]
    pairs = re.findall(r'case (\w+)(?:\s*=\s*"([^"]+)")?', body)
    return {swift: (json_key or swift) for swift, json_key in pairs}


def main() -> int:
    problems = []

    if not STATUS.exists():
        print("status.json not found at %s" % STATUS)
        return 1
    document = json.loads(STATUS.read_text(encoding="utf-8"))

    # --- document level -----------------------------------------------------------------
    for json_key in coding_keys("StatusDocument").values():
        if json_key not in document:
            problems.append("status.json is missing document key %r" % json_key)

    programs = document.get("programs")
    if not isinstance(programs, list) or not programs:
        problems.append("status.json has no programmes")
        programs = []

    # --- every programme row ------------------------------------------------------------
    expected = coding_keys("ProgramStatus")
    for record in programs:
        for json_key in expected.values():
            if json_key not in record:
                problems.append("programme %r is missing %r" % (record.get("id", "?"), json_key))
        if record.get("status") not in VALID_STATUSES:
            problems.append("programme %r has an unknown status %r" % (record.get("id"), record.get("status")))
        if not str(record.get("apply_url", "")).startswith("https://"):
            problems.append("programme %r has a non-https apply_url" % record.get("id"))
        if not record.get("passport_label"):
            problems.append("programme %r has no passport_label (the widget shows a blank pill)" % record.get("id"))

    # --- summary must agree with the rows ------------------------------------------------
    summary = document.get("summary") or {}
    for status, key in (("OPEN", "open"), ("INTEREST", "interest"), ("CLOSED", "closed"),
                        ("UNKNOWN", "unknown"), ("ERROR", "error")):
        counted = sum(1 for record in programs if record.get("status") == status)
        if summary.get(key) != counted:
            problems.append("summary[%r]=%r but %d rows are %s" % (key, summary.get(key), counted, status))

    # --- catalogue and published file must cover the same programmes ----------------------
    if TARGETS.exists():
        expected_ids = [p["id"] for p in json.loads(TARGETS.read_text(encoding="utf-8"))["programs"]]
        published_ids = [record.get("id") for record in programs]
        if expected_ids != published_ids:
            problems.append("targets.json programmes %s != status.json programmes %s" % (expected_ids, published_ids))

    if problems:
        print("CONTRACT BROKEN (%d problem%s):" % (len(problems), "" if len(problems) == 1 else "s"))
        for problem in problems:
            print("  - %s" % problem)
        return 1

    print("Contract OK: %d programmes, %d decoded fields each, summary consistent."
          % (len(programs), len(expected)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

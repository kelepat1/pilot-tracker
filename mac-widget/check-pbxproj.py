#!/usr/bin/env python3
"""
check-pbxproj.py — static validation of the hand-written Xcode project file.

Xcode's own error for the failure this catches is:

    The "PBXGroup" with ID "…" has an invalid value for "children".
    An array of "PBXReference" was expected, but an element of type "PBXNativeTarget" … was specified.

That happens when two different objects share one 24-hex-character ID: the app's product file
reference and the app native target were both AA…0010, so the Products group resolved its child
to a target. Xcode refuses to open the project, but a *set* of IDs hides the problem — which is
exactly how it slipped through a structural check earlier.

This script therefore checks, without needing Xcode:
  1. every object ID is defined exactly once
  2. every referenced ID is defined
  3. each native target's productReference points at a PBXFileReference
  4. both products appear in the Products group
  5. the widget extension is embedded by the app target, and its Info.plist declares the
     widgetkit extension point

Exit code 0 = consistent, 1 = problems found.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PBXPROJ = HERE / "PilotCadetWidget.xcodeproj" / "project.pbxproj"
ID = r"AA[0-9A-F]{22}"


def main() -> int:
    if not PBXPROJ.exists():
        print("not found: %s" % PBXPROJ)
        return 1
    text = PBXPROJ.read_text(encoding="utf-8")
    problems = []

    # 1. definitions (an object definition is `\t\t<ID>` followed by an optional /* comment */)
    definitions = re.findall(r"^\t\t(%s)" % ID, text, re.M)
    counts = Counter(definitions)
    duplicates = sorted(i for i, n in counts.items() if n > 1)
    for duplicate in duplicates:
        problems.append("ID %s is defined %d times" % (duplicate, counts[duplicate]))

    # 2. references
    referenced = set(re.findall(r"\b(%s)\b" % ID, text))
    for dangling in sorted(referenced - set(definitions)):
        problems.append("ID %s is referenced but never defined" % dangling)

    # 3. native targets and their products
    targets = re.findall(r"(%s) /\* (\w+) \*/ = \{\s*isa = PBXNativeTarget;" % ID, text)
    file_refs = set(re.findall(r"^\t\t(%s) /\* [^*]+ \*/ = \{isa = PBXFileReference;" % ID, text, re.M))
    if not targets:
        problems.append("no PBXNativeTarget found")
    for target_id, target_name in targets:
        block = text.split("%s /* %s */ = {" % (target_id, target_name), 1)[1].split("\n\t\t};", 1)[0]
        match = re.search(r"productReference = (%s) /\* ([\w.]+) \*/;" % ID, block)
        if not match:
            problems.append("target %s has no productReference" % target_name)
            continue
        product_id, product_name = match.groups()
        if product_id in file_refs:
            print("  %-28s -> %s" % (target_name, product_name))
        else:
            problems.append(
                "target %s productReference %s is not a PBXFileReference (duplicate ID?)"
                % (target_name, product_id)
            )
        # 4. the product must be listed in the Products group
        if not re.search(r"^\t\t\t\t%s /\* %s \*/," % (product_id, re.escape(product_name)), text, re.M):
            problems.append("product %s is missing from the Products group" % product_name)

    # 5. extension embedding + Info.plist extension point
    if not re.search(r"dstSubfolderSpec = 13;", text):
        problems.append("the app target has no Embed Foundation Extensions copy phase (dstSubfolderSpec 13)")
    if not re.search(r"APPLICATION_EXTENSION_API_ONLY = YES;", text):
        problems.append("the widget extension does not set APPLICATION_EXTENSION_API_ONLY")
    info_plist = HERE / "Info.plist"
    if not info_plist.exists():
        problems.append("Info.plist is missing")
    elif "com.apple.widgetkit-extension" not in info_plist.read_text(encoding="utf-8"):
        problems.append("Info.plist does not declare com.apple.widgetkit-extension")
    if not re.search(r"INFOPLIST_FILE = Info\.plist;", text):
        problems.append("the widget extension does not set INFOPLIST_FILE")

    if problems:
        print("PROJECT FILE PROBLEMS (%d):" % len(problems))
        for problem in problems:
            print("  - %s" % problem)
        return 1

    print("pbxproj OK: %d objects, %d targets, no duplicate or dangling IDs." % (len(definitions), len(targets)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

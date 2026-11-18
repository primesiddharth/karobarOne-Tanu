#!/usr/bin/env python3
"""
check_ac_coverage.py — Verify that all assigned Acceptance Criteria have automated tests.
Source: microservice/contracts/ac_ownership.yaml
Searches services/<svc>/tests/acceptance/ and tests/e2e/ for test_ac_NNN_* functions.
"""
import os
import re
import sys
import yaml

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNERSHIP_FILE = os.path.join(ROOT_DIR, "contracts", "ac_ownership.yaml")


def find_test_ac_numbers(directory: str) -> set[int]:
    """Finds all test_ac_NNN_* test functions in python files under directory."""
    ac_numbers = set()
    if not os.path.exists(directory):
        return ac_numbers

    pattern = re.compile(r"def\s+test_ac_(\d{3})_")
    for root, _, files in os.walk(directory):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path, "r", encoding="utf-8", errors="ignore") as fp:
                    content = fp.read()
                    matches = pattern.findall(content)
                    for m in matches:
                        ac_numbers.add(int(m))
    return ac_numbers


def check_coverage(target_service: str | None = None) -> bool:
    if not os.path.exists(OWNERSHIP_FILE):
        print(f"Error: AC ownership file not found at {OWNERSHIP_FILE}", file=sys.stderr)
        return False

    with open(OWNERSHIP_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    services_config = data.get("services", {})
    e2e_dir = os.path.join(ROOT_DIR, "tests", "e2e")
    e2e_acs = find_test_ac_numbers(e2e_dir)

    all_passed = True
    services_to_check = [target_service] if target_service else services_config.keys()

    print("=" * 60)
    print("Acceptance Criteria Coverage Check")
    print("=" * 60)

    for svc in services_to_check:
        if svc not in services_config:
            print(f"Service '{svc}' not found in {OWNERSHIP_FILE}", file=sys.stderr)
            all_passed = False
            continue

        svc_cfg = services_config[svc]
        primary_acs = svc_cfg.get("primary_acs", [])
        partial_acs = svc_cfg.get("partial_acs", [])
        
        # Look for tests in service's acceptance dir
        svc_test_dir = os.path.join(ROOT_DIR, "services", svc, "tests", "acceptance")
        found_acs = find_test_ac_numbers(svc_test_dir)
        # Tests can also be in tests/e2e/
        found_acs.update(e2e_acs)

        missing = []
        for ac in primary_acs:
            if ac not in found_acs:
                missing.append(ac)

        status_str = "OK" if not missing else f"MISSING ({len(missing)})"
        print(f"[{status_str}] Service: {svc:<12} Primary: {len(primary_acs):<3} Tested: {len(found_acs):<3}")
        if missing:
            formatted_missing = [f"AC-{m:03d}" for m in sorted(missing)]
            print(f"   |-- Missing tests: {', '.join(formatted_missing)}")
            all_passed = False

    print("=" * 60)
    return all_passed


if __name__ == "__main__":
    svc_arg = sys.argv[1] if len(sys.argv) > 1 else None
    success = check_coverage(svc_arg)
    sys.exit(0 if success else 1)

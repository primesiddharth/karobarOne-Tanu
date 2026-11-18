import os
import ast
import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVICES_DIR = os.path.join(ROOT_DIR, "services")


def test_no_cross_service_imports():
    """
    FND-TST-033: Architecture import boundary test.
    Asserts that no code in services/<svc_a> imports services/<svc_b>.
    Communication must be via events or HTTP only.
    """
    if not os.path.exists(SERVICES_DIR):
        pytest.skip("No services directory present yet")

    services = [d for d in os.listdir(SERVICES_DIR) if os.path.isdir(os.path.join(SERVICES_DIR, d))]

    violations = []

    for svc in services:
        svc_path = os.path.join(SERVICES_DIR, svc)
        other_services = [s for s in services if s != svc]

        for root, _, files in os.walk(svc_path):
            for f in files:
                if f.endswith(".py"):
                    full_path = os.path.join(root, f)
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as fp:
                        content = fp.read()
                    try:
                        tree = ast.parse(content, filename=full_path)
                    except SyntaxError:
                        continue

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                for other in other_services:
                                    if alias.name.startswith(f"services.{other}") or alias.name.startswith(other):
                                        violations.append(f"{full_path} imports {alias.name}")
                        elif isinstance(node, ast.ImportFrom):
                            mod = node.module or ""
                            for other in other_services:
                                if mod.startswith(f"services.{other}") or mod == other or mod.startswith(f"{other}."):
                                    violations.append(f"{full_path} imports from {mod}")

    assert not violations, f"Cross-service import violations detected:\n" + "\n".join(violations)

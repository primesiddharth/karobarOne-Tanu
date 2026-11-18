# ==============================================================================
# File: tools/export_openapi.py
# Purpose: Exports OpenAPI schema to a temp location and diffs against committed contracts.
#          Fails on differences to enforce that contracts constrain the code (RULES.md §1).
# ==============================================================================
import argparse
import difflib
import sys
import tempfile
from pathlib import Path
import yaml

microservice_dir = Path(__file__).resolve().parent.parent
if str(microservice_dir) not in sys.path:
    sys.path.insert(0, str(microservice_dir))


def main() -> None:
    parser = argparse.ArgumentParser(description="Check or export OpenAPI schema against committed contracts.")
    parser.add_argument("service", nargs="?", default="iam", help="Service name (e.g., iam, tenant)")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly overwrite committed contract file")
    args = parser.parse_args()

    service_name = args.service
    svc_dir = microservice_dir / "services" / service_name
    if not svc_dir.exists():
        print(f"Error: Service directory does not exist: {svc_dir}", file=sys.stderr)
        sys.exit(1)

    if str(svc_dir) not in sys.path:
        sys.path.insert(0, str(svc_dir))

    # Clear cached app modules to ensure clean import
    for k in list(sys.modules.keys()):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]

    from app.main import app

    openapi_schema = app.openapi()
    generated_yaml = yaml.dump(openapi_schema, sort_keys=False)

    contracts_dir = microservice_dir / "contracts" / "openapi" / "services"
    committed_contract_file = contracts_dir / f"{service_name}.yaml"

    if args.overwrite:
        contracts_dir.mkdir(parents=True, exist_ok=True)
        with open(committed_contract_file, "w", encoding="utf-8") as f:
            f.write(generated_yaml)
        print(f"Exported {len(openapi_schema.get('paths', {}))} paths to {committed_contract_file}")
        sys.exit(0)

    # Write to a temporary file and diff against committed contract
    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        tmp.write(generated_yaml)
        tmp_path = Path(tmp.name)

    try:
        if not committed_contract_file.exists():
            print(
                f"Contract error: Committed contract {committed_contract_file} does not exist.\n"
                f"Generated schema saved temporarily at {tmp_path}.",
                file=sys.stderr,
            )
            sys.exit(1)

        committed_text = committed_contract_file.read_text(encoding="utf-8")
        if committed_text.strip() == generated_yaml.strip():
            print(f"OpenAPI contract check passed for {service_name}: matches {committed_contract_file}")
            sys.exit(0)

        # Output unified diff on mismatch
        diff = difflib.unified_diff(
            committed_text.splitlines(keepends=True),
            generated_yaml.splitlines(keepends=True),
            fromfile=f"committed: {committed_contract_file.name}",
            tofile=f"generated: {service_name}",
        )
        print(f"ERROR: OpenAPI contract drift detected for service '{service_name}':", file=sys.stderr)
        sys.stderr.writelines(diff)
        print(
            f"\nThe contract is supposed to constrain the code, not follow it (RULES.md §1).\n"
            f"If this update is an approved specification change, use --overwrite to update.",
            file=sys.stderr,
        )
        sys.exit(1)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


if __name__ == "__main__":
    main()

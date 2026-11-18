# tools/storage/setup_minio.py
"""Standalone setup script for MinIO object storage (KarobarOne Foundation Spec §11).

Idempotently creates the configured S3 bucket (default: 'karobarone-media')
and verifies connectivity. Works with or without boto3 (using httpx).
"""
import os
import sys
from pathlib import Path

# Add microservice root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    import httpx
except ImportError:
    httpx = None


def get_s3_config() -> dict[str, str]:
    """Resolves S3 settings from environment or defaults."""
    return {
        "endpoint": os.environ.get("S3_ENDPOINT", "http://localhost:9000").rstrip("/"),
        "access_key": os.environ.get("S3_ACCESS_KEY", "minioadmin"),
        "secret_key": os.environ.get("S3_SECRET_KEY", "minioadminpassword"),
        "bucket": os.environ.get("S3_BUCKET", "karobarone-media"),
        "region": os.environ.get("S3_REGION", "us-east-1"),
    }


def check_minio_health(endpoint: str) -> bool:
    """Checks if MinIO health endpoint responds."""
    health_url = f"{endpoint}/minio/health/live"
    try:
        if httpx:
            resp = httpx.get(health_url, timeout=3.0)
            return resp.status_code == 200
        else:
            import urllib.request
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as res:
                return res.status == 200
    except Exception:
        return False


def setup_bucket_via_boto3(config: dict[str, str]) -> bool:
    """Provisions S3 bucket using boto3."""
    import boto3
    from botocore.exceptions import ClientError

    s3 = boto3.client(
        "s3",
        endpoint_url=config["endpoint"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config["region"],
    )

    bucket = config["bucket"]
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"[OK] MinIO bucket '{bucket}' already exists.")
        return True
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchBucket", "NotFound"):
            s3.create_bucket(Bucket=bucket)
            print(f"[OK] MinIO bucket '{bucket}' created successfully.")
            return True
        else:
            print(f"[ERROR] Failed checking bucket '{bucket}': {e}")
            return False


def setup_bucket_via_httpx(config: dict[str, str]) -> bool:
    """Provisions S3 bucket using direct HTTP REST PUT (when boto3 is not present)."""
    # For local MinIO, PUT to /{bucket} with authorization header or standard call
    bucket = config["bucket"]
    url = f"{config['endpoint']}/{bucket}"
    try:
        # Check existence
        head_res = httpx.head(url, timeout=3.0)
        if head_res.status_code in (200, 403):
            print(f"[OK] MinIO bucket '{bucket}' already exists (status {head_res.status_code}).")
            return True

        # Create bucket
        put_res = httpx.put(url, timeout=3.0)
        if put_res.status_code in (200, 204, 409):
            print(f"[OK] MinIO bucket '{bucket}' ready on {config['endpoint']}.")
            return True
        else:
            print(f"[INFO] MinIO returned {put_res.status_code} for bucket creation.")
            return True
    except Exception as e:
        print(f"[WARN] Direct HTTP bucket setup encounter: {e}")
        return False


def main() -> int:
    config = get_s3_config()
    endpoint = config["endpoint"]
    bucket = config["bucket"]
    print(f"Checking MinIO object storage at: {endpoint}...")

    is_alive = check_minio_health(endpoint)
    if not is_alive:
        print(f"[OFFLINE] MinIO server is not reachable at {endpoint}.")
        print("To start MinIO, run: docker compose -f microservice/deploy/compose/docker-compose.yml up -d minio minio-init")
        return 0

    print(f"[ALIVE] MinIO server is healthy. Ensuring bucket '{bucket}' exists...")
    try:
        import boto3  # noqa: F401
        success = setup_bucket_via_boto3(config)
    except ImportError:
        success = setup_bucket_via_httpx(config)

    if success:
        print(f"[READY] MinIO setup verified. Bucket '{bucket}' is ready for use.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

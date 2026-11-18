#!/usr/bin/env python3
"""
gen_keys.py — Generate RSA-2048 keypairs for asymmetric JWT signing and JWKS.
Usage:
    python tools/gen_keys.py [--kid <key_id>] [--write-env [path]]
"""
import sys
import uuid
import json
import base64
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def generate_keypair(kid: str | None = None) -> dict:
    key_id = kid or f"key-{uuid.uuid4().hex[:8]}"
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    # Generate JWK format for public key
    public_numbers = public_key.public_numbers()
    def to_base64url(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, byteorder="big")
        return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")

    jwk = {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": key_id,
        "n": to_base64url(public_numbers.n),
        "e": to_base64url(public_numbers.e),
    }

    return {
        "kid": key_id,
        "private_pem": private_pem,
        "public_pem": public_pem,
        "jwk": jwk,
    }


def write_to_env(keys: dict, env_path: Path) -> None:
    """Appends or updates JWT_KID, JWT_PRIVATE_KEY, and JWT_PUBLIC_KEY in specified .env file."""
    escaped_priv = keys["private_pem"].replace("\n", "\\n")
    escaped_pub = keys["public_pem"].replace("\n", "\\n")

    lines = []
    if env_path.exists():
        existing = env_path.read_text(encoding="utf-8").splitlines()
        for line in existing:
            if line.startswith(("JWT_KID=", "JWT_PRIVATE_KEY=", "JWT_PUBLIC_KEY=")):
                continue
            lines.append(line)

    lines.append(f'JWT_KID="{keys["kid"]}"')
    lines.append(f'JWT_PRIVATE_KEY="{escaped_priv}"')
    lines.append(f'JWT_PUBLIC_KEY="{escaped_pub}"')

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[OK] Wrote JWT keys to {env_path}")


def main():
    kid = None
    write_env = False
    env_file = Path(".env")

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--kid" and i + 1 < len(args):
            kid = args[i + 1]
            i += 2
        elif args[i] == "--write-env":
            write_env = True
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                env_file = Path(args[i + 1])
                i += 2
            else:
                i += 1
        else:
            i += 1

    keys = generate_keypair(kid)

    if write_env:
        write_to_env(keys, env_file)

    print("=" * 60)
    print(f"Generated RSA Keypair (kid: {keys['kid']})")
    print("=" * 60)
    print("\n[JWT_PRIVATE_KEY] (Put in IAM service env):")
    print(keys["private_pem"])
    print("[JWT_PUBLIC_KEY] (Put in other services env):")
    print(keys["public_pem"])
    print("[JWK format]:")
    print(json.dumps(keys["jwk"], indent=2))
    print("=" * 60)


if __name__ == "__main__":
    main()

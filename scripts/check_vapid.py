import base64
import hashlib
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(os.getenv("ENV_FILE", ROOT / ".env"))


def load_env_file(path):
    if load_dotenv is not None:
        load_dotenv(path)
        return
    if not path.exists():
        return
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def base64url_decode_unpadded(value):
    value = (value or "").strip()
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def base64url_encode_unpadded(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def fingerprint(data):
    if not data:
        return ""
    return hashlib.sha256(data).hexdigest()[:16]


def private_key_source(private_key_file, private_key_value):
    if private_key_file:
        key_path = Path(private_key_file)
        if not key_path.is_absolute():
            key_path = ROOT / key_path
        return f"file:{key_path}"
    if private_key_value:
        return "environment:VAPID_PRIVATE_KEY"
    return "not configured"


def read_private_key(private_key_file, private_key_value):
    if private_key_file:
        key_path = Path(private_key_file)
        if not key_path.is_absolute():
            key_path = ROOT / key_path
        return key_path.read_bytes()
    if private_key_value:
        value = private_key_value.strip()
        if "\\n" in value and "-----BEGIN" in value:
            value = value.replace("\\n", "\n")
        return value.encode("utf-8")
    return None


def main():
    load_env_file(ENV_FILE)

    public_key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    private_key_value = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    private_key_file = os.getenv("VAPID_PRIVATE_KEY_FILE", "vapid_private_key.pem").strip()

    public_bytes = None
    public_error = ""
    if public_key:
        try:
            public_bytes = base64url_decode_unpadded(public_key)
            if len(public_bytes) != 65 or public_bytes[0] != 4:
                raise ValueError("not an uncompressed P-256 public key")
        except Exception as exc:
            public_error = str(exc)

    derived_bytes = None
    private_error = ""
    try:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
            load_pem_private_key,
        )

        private_bytes = read_private_key(private_key_file, private_key_value)
        if private_bytes:
            private = load_pem_private_key(private_bytes, password=None)
            derived_bytes = private.public_key().public_bytes(
                Encoding.X962,
                PublicFormat.UncompressedPoint,
            )
    except Exception as exc:
        private_error = str(exc)

    pair_match = bool(public_bytes and derived_bytes and public_bytes == derived_bytes)

    print("## VAPID diagnostics")
    print()
    print(f"Public key source: {'environment:VAPID_PUBLIC_KEY' if public_key else 'not configured'}")
    print(f"Private key source: {private_key_source(private_key_file, private_key_value)}")
    print(f"Public key loaded: {'YES' if public_bytes else 'NO'}")
    print(f"Private key loaded: {'YES' if derived_bytes else 'NO'}")
    print(f"Public fingerprint: {fingerprint(public_bytes) or 'not available'}")
    print(f"Derived fingerprint: {fingerprint(derived_bytes) or 'not available'}")
    print(f"Configured public key: {public_key or 'not configured'}")
    print(
        "Private-derived public key: "
        f"{base64url_encode_unpadded(derived_bytes) if derived_bytes else 'not available'}"
    )
    print(f"Pair match: {'YES' if pair_match else 'NO'}")
    if public_error:
        print(f"Public key error: {public_error}")
    if private_error:
        print(f"Private key error: {private_error}")


if __name__ == "__main__":
    main()

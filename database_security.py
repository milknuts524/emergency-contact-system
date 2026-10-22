"""SQLCipher connections and authenticated encryption for automatic exports."""
import os
from pathlib import Path
import re
import secrets

try:
    from sqlcipher3 import dbapi2 as sqlite
except ImportError:
    import sqlite3 as sqlite


EXPORT_MAGIC = b"EMERGENCY-CSV-1\n"


def encryption_enabled():
    mode = os.getenv("DB_ENCRYPTION", "sqlcipher").lower()
    if mode not in {"sqlcipher", "plain"}:
        raise RuntimeError("DB_ENCRYPTION must be sqlcipher or plain")
    return mode == "sqlcipher"


def require_cipher():
    conn = sqlite.connect(":memory:")
    try:
        if not conn.execute("PRAGMA cipher_version").fetchone():
            raise RuntimeError("SQLCipher is unavailable. Install requirements.txt first.")
    finally:
        conn.close()


def key_path():
    return Path(os.getenv("DB_KEY_FILE", "secrets/database.key"))


def read_key(path=None):
    path = Path(path) if path is not None else key_path()
    if path.is_dir():
        raise RuntimeError("DB_KEY_FILE points to a directory, not a key file. Restore the original key file; do not generate a replacement for an existing encrypted database.")
    if not path.exists():
        raise RuntimeError("Database key is missing. Restore the original DB_KEY_FILE; do not generate a replacement for an existing encrypted database.")
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        raise RuntimeError("Database key is missing or unreadable. Restore DB_KEY_FILE.") from None
    if not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise RuntimeError("Database key must contain exactly 64 hexadecimal characters.")
    return bytes.fromhex(value)


def create_key(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents replacing an existing database's key.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as output:
        output.write(secrets.token_hex(32) + "\n")
    return path


def apply_key(conn, key):
    # Only validated, fixed-length hex is interpolated; no passwords in SQL/logs.
    conn.execute('PRAGMA key = "x\'' + key.hex() + '\'"')
    conn.execute("PRAGMA cipher_memory_security = ON")
    conn.execute("PRAGMA temp_store = MEMORY")


def connect_database(path, *, encrypted=None, key_file=None, must_exist=False, readonly=False):
    encrypted = encryption_enabled() if encrypted is None else encrypted
    path = Path(path)
    if path.is_dir():
        raise RuntimeError("DB_PATH points to a directory, not a database file.")
    if (must_exist or readonly) and not path.is_file():
        raise RuntimeError("Database file does not exist.")
    if (must_exist or readonly) and path.stat().st_size == 0:
        raise RuntimeError("Database file is empty. Check DB_PATH and restore the correct database; no empty replacement was created.")
    key = None
    if encrypted:
        require_cipher()
        key = read_key(key_file)
        if path.exists():
            with path.open("rb") as source:
                if source.read(16) == b"SQLite format 3\x00":
                    raise RuntimeError("Plaintext database found. Stop the app and run scripts/secure_storage.py migrate.")
    if must_exist or readonly:
        # SQLite URI modes prevent a race from silently creating a new file.
        mode = "ro" if readonly else "rw"
        conn = sqlite.connect(path.resolve().as_uri() + "?mode=" + mode, uri=True, timeout=15)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite.connect(str(path), timeout=15)
    try:
        if encrypted:
            apply_key(conn, key)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        conn.row_factory = sqlite.Row
        return conn
    except Exception:
        conn.close()
        raise RuntimeError("Database cannot be opened. Check the key and database; no plaintext fallback was used.") from None


def encrypt_export(content, key=None):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    key = read_key() if key is None else key
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    export_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=EXPORT_MAGIC).derive(key)
    return EXPORT_MAGIC + salt + nonce + AESGCM(export_key).encrypt(nonce, content, EXPORT_MAGIC)


def decrypt_export(content, key=None):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    if not content.startswith(EXPORT_MAGIC) or len(content) < len(EXPORT_MAGIC) + 44:
        raise ValueError("Not an encrypted emergency CSV export")
    key = read_key() if key is None else key
    offset = len(EXPORT_MAGIC)
    salt, nonce = content[offset:offset + 16], content[offset + 16:offset + 28]
    export_key = HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=EXPORT_MAGIC).derive(key)
    return AESGCM(export_key).decrypt(nonce, content[offset + 28:], EXPORT_MAGIC)

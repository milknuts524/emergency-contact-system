"""Explicit storage migration/backup operations, independent of app startup."""
import os
from pathlib import Path

from database_security import (
    connect_database, create_key, read_key, require_cipher,
)


def reserve_file(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)


def verify_database(conn):
    if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
        raise RuntimeError("Database integrity verification failed.")
    if conn.execute("PRAGMA cipher_integrity_check").fetchall():
        raise RuntimeError("Database encryption integrity verification failed.")


def database_summary(conn, schema="main"):
    # Identifiers come from SQLite metadata, quoted before use.
    tables = conn.execute(f'SELECT name, sql FROM {schema}.sqlite_master WHERE type="table" ORDER BY name').fetchall()
    counts = {}
    for name, _ in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        counts[name] = conn.execute(f'SELECT count(*) FROM {schema}.{quoted}').fetchone()[0]
    metadata = conn.execute(f'SELECT type, name, tbl_name, sql FROM {schema}.sqlite_master ORDER BY type, name').fetchall()
    return ([tuple(row) for row in metadata], counts)


def migrate_database(source, target, key_file):
    source, target, key_file = Path(source), Path(target), Path(key_file)
    if source.resolve() == target.resolve():
        raise ValueError("Source and target must be different files.")
    if key_file.resolve() in {source.resolve(), target.resolve()}:
        raise ValueError("The key file must be separate from both database files.")
    # Check this before any key creation: a missing key for an existing database
    # must never be replaced by an unrelated newly generated key.
    if os.path.lexists(target):
        raise FileExistsError("Migration target already exists. Verify the existing database with its original key; no key or database was changed.")
    if key_file.is_dir():
        read_key(key_file)  # Report the directory error without renaming/deleting it.
    if not source.is_file():
        raise ValueError("Source database does not exist.")
    with source.open("rb") as input_file:
        if input_file.read(16) != b"SQLite format 3\x00":
            raise ValueError("Migration source must be a plaintext SQLite database.")
    require_cipher()
    reserve_file(target)
    conn = None
    try:
        if not os.path.lexists(key_file):
            create_key(key_file)
        key = read_key(key_file)
        conn = connect_database(source, encrypted=False, must_exist=True)
        conn.execute("PRAGMA temp_store = MEMORY")
        # sqlcipher_export preserves tables, indexes, triggers, and views.
        conn.execute("ATTACH DATABASE ? AS encrypted KEY ?", (str(target), "x'" + key.hex() + "'"))
        conn.execute("BEGIN IMMEDIATE")
        verify_database(conn)
        before = database_summary(conn)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        application = conn.execute("PRAGMA application_id").fetchone()[0]
        conn.execute("SELECT sqlcipher_export('encrypted')")
        conn.execute(f"PRAGMA encrypted.user_version = {version}")
        conn.execute(f"PRAGMA encrypted.application_id = {application}")
        if before != database_summary(conn, "encrypted"):
            raise RuntimeError("Migrated schema or record counts do not match.")
        conn.commit()
        conn.close()
        conn = None
        check = connect_database(target, encrypted=True, key_file=key_file, must_exist=True)
        try:
            verify_database(check)
            if before != database_summary(check):
                raise RuntimeError("Reopened database does not match the source.")
        finally:
            check.close()
    except Exception:
        if conn is not None:
            conn.close()
        target.unlink(missing_ok=True)
        raise


def backup_database(source, target, key_file):
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve():
        raise ValueError("Backup must use a different file.")
    # Always open the source first: missing/wrong keys must not leave a backup.
    src = connect_database(source, encrypted=True, key_file=key_file, must_exist=True)
    try:
        reserve_file(target)
        dest = None
        try:
            dest = connect_database(target, encrypted=True, key_file=key_file)
            src.backup(dest)
            verify_database(dest)
            dest.close()
            dest = None
            reopened = connect_database(target, encrypted=True, key_file=key_file, must_exist=True)
            try:
                verify_database(reopened)
            finally:
                reopened.close()
        except Exception:
            if dest is not None:
                dest.close()
            target.unlink(missing_ok=True)
            raise
    finally:
        src.close()

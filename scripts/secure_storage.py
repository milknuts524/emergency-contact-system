"""Manage encrypted storage without putting keys on the command line."""
import argparse
import os
from pathlib import Path
import sys
import socket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def config_path(path):
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main():
    os.chdir(ROOT)
    from dotenv import load_dotenv, set_key
    env_file = Path(os.getenv("ENV_FILE", ".env"))
    load_dotenv(env_file)
    from database_security import connect_database, decrypt_export, key_path
    from storage_tools import backup_database, migrate_database, reserve_file, verify_database
    parser = argparse.ArgumentParser(description="Encrypted database migration, backup and recovery")
    parser.add_argument("action", choices=["migrate", "verify", "check", "backup", "restore", "decrypt-csv"])
    parser.add_argument("--source", type=Path, default=Path(os.getenv("DB_PATH", "emergency.db")))
    parser.add_argument("--target", type=Path)
    parser.add_argument("--key-file", type=Path, default=key_path())
    parser.add_argument("--activate", action="store_true", help="Update .env after verified migration")
    args = parser.parse_args()
    try:
        if args.activate and args.action != "migrate":
            raise ValueError("--activate is only available for migration.")
        if args.action == "migrate":
            try:
                with socket.create_connection(("127.0.0.1", 8000), timeout=0.5):
                    raise RuntimeError("Stop the application (including Docker) before migrating.")
            except OSError:
                pass
            target = args.target or args.source.with_name(args.source.stem + ".encrypted.db")
            migrate_database(args.source, target, args.key_file)
            if args.activate:
                # These settings are applied only after successful reopen/verification.
                # No secret key bytes are written into .env.
                set_key(env_file, "DB_PATH", config_path(target))
                set_key(env_file, "DB_KEY_FILE", config_path(args.key_file))
                set_key(env_file, "DB_ENCRYPTION", "sqlcipher")
                env_file.chmod(0o600)
            print("Encrypted database created and verified. Original plaintext file was retained.")
            print("Back up the key separately, then test startup and recovery before retiring plaintext copies.")
        elif args.action in {"verify", "check"}:
            conn = connect_database(args.source, encrypted=True, key_file=args.key_file, must_exist=True, readonly=True)
            try:
                if args.action == "verify":
                    verify_database(conn)
                else:
                    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='members'").fetchone():
                        raise RuntimeError("Configured database is not an initialized emergency-contact database (members table missing). Check DB_PATH.")
            finally:
                conn.close()
            print("Encrypted database verified.")
        elif args.action in {"backup", "restore"}:
            if args.target is None:
                raise ValueError("--target is required. Existing files will never be overwritten.")
            backup_database(args.source, args.target, args.key_file)
            print("Encrypted " + args.action + " created and verified.")
        else:
            if args.target is None:
                raise ValueError("--target is required for the recovered plaintext CSV.")
            from database_security import read_key
            content = decrypt_export(args.source.read_bytes(), read_key(args.key_file))
            reserve_file(args.target)
            args.target.write_bytes(content)
            print("CSV recovered. This output contains plaintext personal information.")
    except Exception as exc:
        # Library crypto errors can contain noisy internals; never dump key values.
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError, FileExistsError)) else type(exc).__name__
        parser.exit(1, "Storage operation failed: " + message + "\n")


if __name__ == "__main__":
    main()

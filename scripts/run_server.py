"""One native startup path with loopback binding and explicit proxy trust."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    os.chdir(ROOT)
    from dotenv import load_dotenv
    load_dotenv(os.getenv("ENV_FILE", ".env"))
    from database_security import connect_database, encryption_enabled
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not encryption_enabled():
        parser.exit(1, "Encrypted storage is required for this launcher. Run scripts/secure_storage.py migrate first.\n")
    try:
        conn = connect_database(os.getenv("DB_PATH", "emergency.db"), must_exist=True)
        conn.close()
    except RuntimeError as exc:
        parser.exit(1, str(exc) + "\n")
    if args.check:
        print("Encrypted storage is ready.")
        return
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1,::1")


if __name__ == "__main__":
    main()

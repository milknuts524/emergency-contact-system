"""Run with: python -m unittest discover -s tests (requires httpx)."""
import os
from contextlib import contextmanager
from pathlib import Path
import tempfile

# Never open the operational database or .env during these tests.
_test_dir = tempfile.TemporaryDirectory()
os.environ['DB_PATH'] = str(Path(_test_dir.name) / 'test.db')
os.environ['ENV_FILE'] = str(Path(_test_dir.name) / 'missing.env')
os.environ['AUTO_EXPORT_DIR'] = str(Path(_test_dir.name) / 'auto_exports')
os.environ['ENABLED_PLUGINS'] = 'disaster_board2'

from fastapi.testclient import TestClient
import main


@contextmanager
def connection():
    conn = main.get_conn()
    try:
        with conn:
            yield conn
    finally:
        conn.close()

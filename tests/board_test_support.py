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
os.environ['DB_ENCRYPTION'] = os.getenv('TEST_DB_ENCRYPTION', 'plain')
os.environ['DB_KEY_FILE'] = str(Path(_test_dir.name) / 'database.key')
os.environ['DB_ALLOW_INITIALIZE'] = '1'
if os.environ['DB_ENCRYPTION'] == 'sqlcipher':
    from database_security import create_key
    create_key(os.environ['DB_KEY_FILE'])
os.environ['ALLOWED_HOSTS'] = 'testserver,localhost,127.0.0.1'

# Provision test storage explicitly; application startup may not create it.
from database_security import connect_database
_initial = connect_database(os.environ['DB_PATH'])
_initial.execute('VACUUM')
_initial.close()

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

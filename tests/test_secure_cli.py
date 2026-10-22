import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from database_security import create_key

ROOT = Path(__file__).resolve().parents[1]


class SecureCLITest(unittest.TestCase):
    def test_migration_activation_backup_restore_and_csv_recovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'plain.db'
            conn = sqlite3.connect(source)
            conn.execute('CREATE TABLE sample (name TEXT)')
            conn.execute("INSERT INTO sample VALUES ('test')")
            conn.commit()
            conn.close()
            env = dict(os.environ, ENV_FILE=str(root / '.env'))
            key, target = root / 'key', root / 'encrypted.db'
            def run(*args):
                result = subprocess.run([sys.executable, 'scripts/secure_storage.py', *args], cwd=ROOT, env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result
            run('migrate', '--source', str(source), '--target', str(target), '--key-file', str(key), '--activate')
            from dotenv import dotenv_values
            config = dotenv_values(root / '.env')
            self.assertEqual(config['DB_ENCRYPTION'], 'sqlcipher')
            self.assertEqual(config['DB_PATH'], target.resolve().as_posix())
            self.assertNotIn(key.read_text().strip(), (root / '.env').read_text())
            run('verify', '--source', str(target), '--key-file', str(key))
            run('backup', '--source', str(target), '--target', str(root / 'backup.db'), '--key-file', str(key))
            run('restore', '--source', str(root / 'backup.db'), '--target', str(root / 'restored.db'), '--key-file', str(key))
            from database_security import encrypt_export, read_key
            (root / 'csv.enc').write_bytes(encrypt_export(b'name\ntest\n', read_key(key)))
            run('decrypt-csv', '--source', str(root / 'csv.enc'), '--target', str(root / 'csv.csv'), '--key-file', str(key))
            self.assertEqual((root / 'csv.csv').read_bytes(), b'name\ntest\n')

    def test_every_plugin_initializes_and_admin_pages_open_on_encrypted_db(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            create_key(root / 'key')
            env = dict(os.environ, ENV_FILE=str(root / 'missing.env'), DB_PATH=str(root / 'app.db'),
                       DB_ENCRYPTION='sqlcipher', DB_KEY_FILE=str(root / 'key'),
                       DB_ALLOW_INITIALIZE='1',
                       AUTO_EXPORT_DIR=str(root / 'exports'), ALLOWED_HOSTS='testserver',
                       ENABLED_PLUGINS='calendar,survey,viewer,phonebook,bed_status,disaster_board2',
                       CALENDAR_ICS_URL='')
            code = '''
from database_security import connect_database
import os
initial = connect_database(os.environ['DB_PATH'])
initial.execute('VACUUM')
initial.close()
from fastapi.testclient import TestClient
import main
main.app.dependency_overrides[main.check_admin] = lambda: True
with TestClient(main.app, base_url='https://testserver') as client:
    for path in ('/', '/admin', '/admin/settings', '/admin/phonebook', '/admin/viewer', '/admin/surveys', '/admin/bed-status', '/admin/disaster-board2'):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert response.headers['strict-transport-security'] == 'max-age=2592000'
        assert response.headers['cache-control'] == 'no-store'
'''
            result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotEqual((root / 'app.db').read_bytes()[:16], b'SQLite format 3\x00')
            self.assertFalse(list((root / 'exports').glob('*.csv')))
            self.assertTrue(list((root / 'exports').glob('*.csv.enc')))

    def test_application_rejects_missing_and_empty_storage_without_initializing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            create_key(root / 'key')
            env = dict(os.environ, ENV_FILE=str(root / 'missing.env'), DB_PATH=str(root / 'app.db'),
                       DB_ENCRYPTION='sqlcipher', DB_KEY_FILE=str(root / 'key'), ENABLED_PLUGINS='', DB_ALLOW_INITIALIZE='0')
            for create_empty in (False, True):
                if create_empty:
                    (root / 'app.db').touch()
                result = subprocess.run([sys.executable, '-c', 'import main'], cwd=ROOT, env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                if create_empty:
                    self.assertEqual((root / 'app.db').stat().st_size, 0)
                else:
                    self.assertFalse((root / 'app.db').exists())

    def test_valid_but_unrelated_encrypted_database_is_not_initialized(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = create_key(root / 'key')
            from database_security import connect_database
            conn = connect_database(root / 'unrelated.db', encrypted=True, key_file=key)
            conn.execute('CREATE TABLE unrelated (value TEXT)')
            conn.commit()
            conn.close()
            before = (root / 'unrelated.db').read_bytes()
            env = dict(os.environ, ENV_FILE=str(root / 'missing.env'), DB_PATH=str(root / 'unrelated.db'),
                       DB_ENCRYPTION='sqlcipher', DB_KEY_FILE=str(key), ENABLED_PLUGINS='', DB_ALLOW_INITIALIZE='0')
            result = subprocess.run([sys.executable, '-c', 'import main'], cwd=ROOT, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('not an initialized', result.stderr)
            self.assertEqual(before, (root / 'unrelated.db').read_bytes())

"""Opt-in Docker regression using isolated volumes, never operational storage.

Build emergency-contact-storage-fix:test, then set RUN_DOCKER_TESTS=1.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.getenv('RUN_DOCKER_TESTS') == '1', 'opt-in Docker integration')
class DockerStorageTest(unittest.TestCase):
    def test_real_compose_mounts_migration_health_and_missing_key_safety(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            data, keys = root / 'data', root / 'secrets'
            data.mkdir()
            keys.mkdir()
            config = json.loads(subprocess.check_output(
                ['docker', 'compose', '--profile', 'maintenance', 'config', '--format', 'json'], cwd=ROOT))
            config.pop('networks', None)
            config['name'] = 'storage-check-' + uuid.uuid4().hex[:10]
            for service in config['services'].values():
                service.pop('build', None)
                service.pop('container_name', None)
                service.pop('ports', None)
                service.pop('networks', None)
                service['network_mode'] = 'none'
                service['image'] = 'emergency-contact-storage-fix:test'
                service['environment']['ENV_FILE'] = '/app/data/missing.env'
                for mount in service['volumes']:
                    if mount['target'] == '/app/data':
                        mount['source'] = str(data)
                    elif mount['target'] == '/run/secrets':
                        mount['source'] = str(keys)
                service['volumes'] = [mount for mount in service['volumes']
                                      if mount['target'] in {'/app/data', '/run/secrets'}]
            config['services']['emergency-contact']['environment']['ENABLED_PLUGINS'] = ''
            config['services']['emergency-contact']['healthcheck'].update(
                interval='1s', start_period='1s', retries=3)
            path = root / 'compose.json'
            path.write_text(json.dumps(config))
            base = ['docker', 'compose', '-f', str(path)]

            def run(*args, succeeds=True):
                result = subprocess.run([*base, *args], cwd=ROOT, capture_output=True, text=True, timeout=90)
                if succeeds:
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                return result

            try:
                setup = '''
import os, sqlite3
os.environ.update(DB_PATH='/app/data/emergency.db', DB_ENCRYPTION='plain', DB_ALLOW_INITIALIZE='1')
c=sqlite3.connect('/app/data/emergency.db'); c.execute('VACUUM'); c.close()
import main
c=main.get_conn()
c.execute("INSERT INTO members(name,code,active) VALUES ('fixture','fixture-code',1)")
c.commit(); c.close()
'''
                run('run', '--rm', '--entrypoint', 'python', 'storage-tools', '-c', setup)
                original = (data / 'emergency.db').read_bytes()
                key = keys / 'database.key'
                key.mkdir()
                migration = ('run', '--rm', 'storage-tools', 'migrate', '--source', '/app/data/emergency.db',
                             '--target', '/app/data/emergency.encrypted.db')
                result = run(*migration, succeeds=False)
                self.assertIn('directory', result.stderr + result.stdout)
                self.assertTrue(key.is_dir())
                self.assertFalse((data / 'emergency.encrypted.db').exists())
                key.rmdir()  # Only the deliberately-created empty fixture directory.
                run(*migration)
                key_bytes = key.read_bytes()
                self.assertEqual((data / 'emergency.db').read_bytes(), original)
                run('run', '--rm', 'storage-tools', 'verify')
                run('run', '--rm', 'storage-tools', 'backup', '--target', '/app/data/backup.db')
                run('run', '--rm', 'storage-tools', 'restore', '--source', '/app/data/backup.db', '--target', '/app/data/restored.db')
                run('up', '-d', '--wait', '--wait-timeout', '40', 'emergency-contact')
                run('exec', '-T', 'emergency-contact', 'python', 'scripts/secure_storage.py', 'check')
                key.unlink()
                run('run', '--rm', 'storage-tools', 'check', succeeds=False)
                run(*migration, succeeds=False)
                self.assertFalse(key.exists())
                key.write_bytes(key_bytes)
                run('run', '--rm', 'storage-tools', 'verify')
            finally:
                subprocess.run([*base, 'down', '--remove-orphans'], cwd=ROOT, capture_output=True, timeout=30)

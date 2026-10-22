"""Security regression checks against temporary files and the isolated database."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from board_test_support import main, connection, TestClient
from plugins.viewer import router, service

if not any(getattr(route, 'path', '') == '/viewer/{item_id}/file' for route in main.app.routes):
    main.app.include_router(router.router)


class SecurityTest(unittest.TestCase):
    def test_documents_require_membership_and_active_publication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            uploads = root / 'uploads' / 'viewer'
            uploads.mkdir(parents=True)
            (uploads / 'private.pdf').write_bytes(b'%PDF-1.4\nprivate test document')
            (root / 'public.txt').write_text('public')
            static = next(route.app for route in main.app.routes if getattr(route, 'path', '') == '/static')
            with patch.object(static, 'all_directories', [str(root)]), patch.dict(os.environ, {'VIEWER_UPLOAD_DIR': str(uploads)}), patch.object(service, 'UPLOAD_DIR', uploads):
                with connection() as conn:
                    service.init_db(conn)
                    conn.execute('DELETE FROM viewer_items')
                    conn.execute("INSERT OR REPLACE INTO members(name, code, active) VALUES ('test', 'security-test', 1)")
                    item = conn.execute("INSERT INTO viewer_items(title, file_path, file_type, is_active) VALUES ('test', '/static/uploads/viewer/private.pdf', 'pdf', 1)").lastrowid
                with TestClient(main.app, base_url='https://testserver') as client:
                    self.assertEqual(client.get('/static/public.txt').status_code, 200)
                    self.assertEqual(client.get('/static/uploads/viewer/private.pdf').status_code, 404)
                    self.assertEqual(client.get(f'/viewer/{item}/file').status_code, 404)
                    client.cookies.set('member_code', 'security-test')
                    response = client.get(f'/viewer/{item}/file')
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers['cache-control'], 'no-store')
                    self.assertEqual(response.headers['referrer-policy'], 'no-referrer')
                    with connection() as conn:
                        conn.execute('UPDATE viewer_items SET is_active=0 WHERE id=?', (item,))
                    self.assertEqual(client.get(f'/viewer/{item}/file').status_code, 404)
                    self.assertEqual(client.get('/static/uploads/viewer/private.pdf').status_code, 404)
                self.assertIsNone(service.local_file_path('/static/uploads/viewer/../private.pdf'))

    def test_member_cookie_flags(self):
        with connection() as conn:
            conn.execute("INSERT OR REPLACE INTO members(name, code, active) VALUES ('test', 'security-cookie', 1)")
        with TestClient(main.app, base_url='https://testserver') as client:
            response = client.get('/user/security-cookie')
            self.assertEqual(response.status_code, 200)
            cookie = response.headers['set-cookie'].lower()
            self.assertIn('httponly', cookie)
            self.assertIn('secure', cookie)

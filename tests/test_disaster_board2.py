"""Uses the shared isolated test database; no operational data is accessed."""
import unittest

from board_test_support import main, connection, TestClient
from plugins.disaster_board2 import service


class DisasterBoard2Test(unittest.TestCase):
    def setUp(self):
        main.ENABLED_PLUGINS = ['disaster_board2']
        self.client = TestClient(main.app)
        self.client.cookies.set('member_code', 'aaa')
        main.app.dependency_overrides[main.check_admin] = lambda: True
        with connection() as conn:
            service.init_db(conn)
            conn.execute('DELETE FROM disaster_board2_replies')
            conn.execute('DELETE FROM disaster_board2_posts')
            conn.execute('DELETE FROM members')
            conn.executemany('INSERT INTO members(name, code, active) VALUES (?, ?, ?)', [('職員A', 'aaa', 1), ('職員B', 'bbb', 1), ('退職者', 'zzz', 0)])
            main.set_disaster_mode(conn, 'disaster')
        self.assertEqual(self.client.get('/disaster-board2').status_code, 200)
        self.csrf = self.client.cookies['disaster_board2_csrf']

    def tearDown(self):
        self.client.close()
        main.app.dependency_overrides.clear()

    def post(self, path, **values):
        return self.client.post(path, data={'csrf': self.csrf, **values}, follow_redirects=False)

    def create(self, admin=False):
        path = '/admin/disaster-board2' if admin else '/disaster-board2'
        response = self.post(path, title='出勤経路について', body='<script>alert(1)</script>\n迂回が必要です', category='出勤', member_id='999', author='偽名')
        self.assertEqual(response.status_code, 303)
        return response.headers['location'].split('?')[0]

    def test_custom_author_and_other_category(self):
        response = self.post('/disaster-board2', title='連絡', body='本文', category='その他', author_name='山田 太郎')
        self.assertEqual(response.status_code, 303)
        path = response.headers['location'].split('?')[0]
        self.assertIn('山田 太郎', self.client.get(path).text)
        self.assertIn('その他', self.client.get(path).text)
        self.assertEqual(self.post(path + '/reply', body='返信', author_name='佐藤 花子').status_code, 303)
        self.assertIn('佐藤 花子', self.client.get(path).text)
        self.assertEqual(self.post(path + '/reply', body='返信', author_name='a' * 101).status_code, 422)
        with connection() as conn:
            row = conn.execute('SELECT member_id, author_name FROM disaster_board2_posts').fetchone()
            member = conn.execute("SELECT id FROM members WHERE code='aaa'").fetchone()
            self.assertEqual(row['member_id'], member['id'])
            self.assertEqual(row['author_name'], '山田 太郎')

    def test_smartphone_home_links_to_staff_posting_form(self):
        self.client.headers['user-agent'] = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1'
        home = self.client.get('/user/aaa')
        self.assertEqual(home.status_code, 200)
        self.assertIn('href="/disaster-board2"', home.text)
        board = self.client.get('/disaster-board2')
        self.assertEqual(board.status_code, 200)
        self.assertIn('新しく投稿する', board.text)
        self.assertIn('action="/disaster-board2"', board.text)
        self.assertIn('name="body"', board.text)
        with connection() as conn:
            main.set_disaster_mode(conn, 'normal')
        self.assertNotIn('href="/disaster-board2"', self.client.get('/user/aaa').text)

    def test_staff_can_post_and_reply_under_registered_names(self):
        path = self.create()
        self.client.cookies.set('member_code', 'bbb')
        self.assertEqual(self.post(path + '/reply', body='別の経路で向かいます', author='偽名').status_code, 303)
        page = self.client.get(path)
        self.assertEqual(page.headers['cache-control'], 'no-store')
        for text in ['職員A', '職員B', '別の経路で向かいます', '&lt;script&gt;']:
            self.assertIn(text, page.text)
        self.assertNotIn('<script>', page.text)
        self.assertNotIn('偽名', page.text)
        admin_path = self.create(admin=True)
        self.assertEqual(self.post(admin_path + '/reply', body='本部からの返信').status_code, 303)
        self.assertIn('管理者', self.client.get(admin_path).text)
        self.assertIn('本部からの返信', self.client.get(admin_path.replace('/admin', '')).text)

    def test_moderation_hides_content_and_closes_replies(self):
        path = self.create()
        self.post(path + '/reply', body='非表示対象の本文')
        with connection() as conn:
            reply_id = conn.execute('SELECT id FROM disaster_board2_replies').fetchone()[0]
        admin_path = '/admin' + path
        self.assertEqual(self.post(admin_path + '/moderate', action='hide', reply_id=reply_id).status_code, 303)
        self.assertNotIn('非表示対象の本文', self.client.get(path).text)
        self.assertIn('非表示対象の本文', self.client.get(admin_path).text)
        self.assertEqual(self.post(admin_path + '/moderate', action='close').status_code, 303)
        self.assertEqual(self.post(path + '/reply', body='遅い返信').status_code, 409)
        self.assertEqual(self.post(admin_path + '/moderate', action='hide').status_code, 303)
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertNotIn('出勤経路について', self.client.get('/disaster-board2').text)
        self.assertEqual(self.post(path + '/reply', body='非表示後').status_code, 404)
        self.assertEqual(self.post(admin_path + '/reply', body='管理者から').status_code, 409)

    def test_normal_mode_and_next_incident(self):
        path = self.create()
        with connection() as conn:
            main.set_disaster_mode(conn, 'normal')
        for url in ['/disaster-board2', path]:
            self.assertEqual(self.client.get(url).status_code, 403)
        for url in [path + '/reply', '/admin' + path + '/reply']:
            self.assertEqual(self.post(url, body='停止中').status_code, 403)
        for url in ['/disaster-board2', '/admin/disaster-board2']:
            self.assertEqual(self.post(url, title='件名', body='本文', category='安否').status_code, 403)
        self.assertEqual(self.post('/admin' + path + '/moderate', action='hide').status_code, 403)
        self.assertEqual(self.client.get('/admin' + path).status_code, 200)
        with connection() as conn:
            main.set_disaster_mode(conn, 'disaster')
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.post(path + '/reply', body='次回').status_code, 404)
        self.assertEqual(self.post('/admin' + path + '/reply', body='次回').status_code, 409)
        self.assertNotIn('出勤経路について', self.client.get('/disaster-board2').text)

    def test_authentication_disabled_plugin_and_validation(self):
        path = self.create()
        self.assertEqual(self.post(path + '/reply', body=' ', csrf=self.csrf).status_code, 422)
        self.assertEqual(self.post(path + '/reply', body='a' * 2001).status_code, 422)
        self.assertEqual(self.post(path + '/reply', body='本文', csrf='invalid').status_code, 403)
        for title, category in [(' ', '安否'), ('a' * 101, '安否'), ('件名', '私信')]:
            self.assertEqual(self.post('/disaster-board2', title=title, body='本文', category=category).status_code, 422)
        self.assertEqual(self.client.get('/disaster-board2?page=0').status_code, 422)
        for code in ['zzz', 'unknown']:
            self.client.cookies.set('member_code', code)
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.post(path + '/reply', body='本文').status_code, 404)
            self.assertEqual(self.post('/disaster-board2', title='件名', body='本文', category='安否').status_code, 404)
        self.client.cookies.set('member_code', 'aaa')
        main.app.dependency_overrides.clear()
        for suffix in ['', path.replace('/disaster-board2', '')]:
            self.assertEqual(self.client.get('/admin/disaster-board2' + suffix).status_code, 401)
        self.assertEqual(self.post('/admin' + path + '/moderate', action='hide').status_code, 401)
        self.assertEqual(self.post('/admin' + path + '/reply', body='本文').status_code, 401)
        self.assertEqual(self.post('/admin/disaster-board2', title='件名', body='本文', category='安否').status_code, 401)
        main.ENABLED_PLUGINS = []
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.post(path + '/reply', body='本文').status_code, 404)

    def test_pagination_and_reply_belongs_to_post(self):
        path = self.create()
        other = self.create()
        for number in range(21):
            self.assertEqual(self.post(path + '/reply', body=f'返信番号{number:02}').status_code, 303)
        response = self.post(path + '/reply', body='最新返信')
        self.assertIn('page=2', response.headers['location'])
        self.assertIn('最新返信', self.client.get(response.headers['location']).text)
        self.assertNotIn('返信番号20', self.client.get(path).text)
        self.assertIn('返信番号20', self.client.get(path + '?page=2').text)
        with connection() as conn:
            reply_id = conn.execute('SELECT MIN(id) FROM disaster_board2_replies').fetchone()[0]
        self.assertEqual(self.post('/admin' + other + '/moderate', action='hide', reply_id=reply_id).status_code, 404)
        self.assertIn('返信番号00', self.client.get(path).text)

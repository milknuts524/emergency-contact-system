import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from database_security import (
    connect_database, create_key, decrypt_export, encrypt_export, read_key,
)
from storage_tools import backup_database, database_summary, migrate_database, verify_database


class EncryptedStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'plain.db'
        self.target = self.root / 'encrypted.db'
        self.key = self.root / 'database.key'
        conn = sqlite3.connect(self.source)
        conn.executescript('''
            CREATE TABLE members (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, data BLOB);
            CREATE INDEX member_name ON members(name);
            CREATE TABLE audit (value TEXT);
            CREATE TRIGGER added AFTER INSERT ON members BEGIN INSERT INTO audit VALUES (new.name); END;
            CREATE VIEW names AS SELECT name FROM members;
            PRAGMA user_version=7;
            PRAGMA application_id=123;
        ''')
        conn.execute('INSERT INTO members(name,data) VALUES (?,?)', ('個人情報テスト', b'\x00\xffblob'))
        conn.commit()
        conn.close()

    def tearDown(self):
        self.temp.cleanup()

    def migrate(self):
        migrate_database(self.source, self.target, self.key)

    def test_migration_keeps_source_schema_data_and_metadata(self):
        original = self.source.read_bytes()
        self.migrate()
        self.assertEqual(original, self.source.read_bytes())
        self.assertNotEqual(self.target.read_bytes()[:16], b'SQLite format 3\x00')
        self.assertNotIn('個人情報テスト'.encode(), self.target.read_bytes())
        source = sqlite3.connect(self.source)
        try:
            before = database_summary(source)
        finally:
            source.close()
        conn = connect_database(self.target, encrypted=True, key_file=self.key)
        try:
            self.assertEqual(before, database_summary(conn))
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 7)
            self.assertEqual(conn.execute('PRAGMA application_id').fetchone()[0], 123)
            self.assertEqual(conn.execute('SELECT data FROM members').fetchone()[0], b'\x00\xffblob')
            conn.execute("INSERT INTO members(name) VALUES ('second')")
            conn.commit()
            self.assertEqual(conn.execute('SELECT count(*) FROM audit').fetchone()[0], 2)
        finally:
            conn.close()
        plain = sqlite3.connect(self.target)
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                plain.execute('SELECT * FROM members').fetchall()
        finally:
            plain.close()

    def test_missing_wrong_keys_and_plaintext_never_fall_back(self):
        self.migrate()
        other = create_key(self.root / 'wrong.key')
        for key in (other, self.root / 'missing.key'):
            with self.assertRaises(RuntimeError):
                connect_database(self.target, encrypted=True, key_file=key)
        with self.assertRaises(RuntimeError):
            connect_database(self.source, encrypted=True, key_file=self.key)
        with patch.dict(os.environ, {'DB_ENCRYPTION': 'sqlcipher', 'DB_KEY_FILE': str(self.root / 'missing.key')}):
            with self.assertRaises(RuntimeError):
                connect_database(self.root / 'never-created.db')
            self.assertFalse((self.root / 'never-created.db').exists())

    def test_existing_target_key_and_source_cannot_be_overwritten(self):
        self.migrate()
        original_key = self.key.read_bytes()
        original_target = self.target.read_bytes()
        with self.assertRaises(FileExistsError):
            self.migrate()
        with self.assertRaises(FileExistsError):
            create_key(self.key)
        with self.assertRaises(ValueError):
            migrate_database(self.source, self.source, self.key)
        self.assertEqual(original_key, self.key.read_bytes())
        self.assertEqual(original_target, self.target.read_bytes())

    def test_encrypted_backup_restore_includes_committed_wal_changes(self):
        self.migrate()
        live = connect_database(self.target, encrypted=True, key_file=self.key)
        try:
            live.execute('PRAGMA journal_mode=WAL')
            live.execute("INSERT INTO members(name) VALUES ('wal record')")
            live.commit()
            backup = self.root / 'backup.db'
            backup_database(self.target, backup, self.key)
            restored = self.root / 'restored.db'
            backup_database(backup, restored, self.key)
            conn = connect_database(restored, encrypted=True, key_file=self.key)
            try:
                verify_database(conn)
                self.assertEqual(conn.execute('SELECT count(*) FROM members').fetchone()[0], 2)
            finally:
                conn.close()
            self.assertNotEqual(backup.read_bytes()[:16], b'SQLite format 3\x00')
            with self.assertRaises(FileExistsError):
                backup_database(self.target, backup, self.key)
        finally:
            live.close()

    def test_csv_roundtrip_tamper_and_wrong_key(self):
        self.migrate()
        key = read_key(self.key)
        content = '名前,電話番号\n職員,0000000000\n'.encode()
        ciphertext = encrypt_export(content, key)
        self.assertNotEqual(ciphertext, encrypt_export(content, key))
        self.assertNotIn(content, ciphertext)
        self.assertEqual(decrypt_export(ciphertext, key), content)
        for value, trial_key in ((ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]), key), (ciphertext, b'0' * 32)):
            with self.assertRaises(Exception):
                decrypt_export(value, trial_key)

    def test_directory_instead_of_key_is_preserved_and_explained(self):
        self.key.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'directory'):
            self.migrate()
        self.assertTrue(self.key.is_dir())
        self.assertEqual(list(self.key.iterdir()), [])
        self.assertFalse(self.target.exists())

    def test_existing_encrypted_database_never_causes_key_regeneration(self):
        self.migrate()
        original = self.target.read_bytes()
        self.key.unlink()
        with self.assertRaisesRegex(FileExistsError, 'target already exists'):
            self.migrate()
        self.assertFalse(self.key.exists())
        self.assertEqual(original, self.target.read_bytes())

    def test_nonexistent_empty_and_directory_db_are_not_initialized(self):
        for target in (self.root / 'missing.db', self.root / 'empty.db', self.root / 'directory.db'):
            if target.name == 'empty.db':
                target.touch()
            if target.name == 'directory.db':
                target.mkdir()
            with self.assertRaises(RuntimeError):
                connect_database(target, encrypted=False, must_exist=True)
        self.assertFalse((self.root / 'missing.db').exists())
        self.assertEqual((self.root / 'empty.db').stat().st_size, 0)

    def test_readonly_storage_check_cannot_modify_data(self):
        self.migrate()
        original = self.target.read_bytes()
        conn = connect_database(self.target, encrypted=True, key_file=self.key, must_exist=True, readonly=True)
        try:
            verify_database(conn)
            with self.assertRaises(Exception):
                conn.execute('DELETE FROM members')
        finally:
            conn.close()
        self.assertEqual(original, self.target.read_bytes())

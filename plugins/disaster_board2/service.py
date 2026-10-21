from datetime import datetime

CATEGORIES = ("安否", "出勤", "支援要請", "災害対応連絡", "その他")


def now():
    return datetime.now().isoformat(timespec="seconds")


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS disaster_board2_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            closed_at TEXT,
            archived_at TEXT,
            hidden_at TEXT
        );
        CREATE TABLE IF NOT EXISTS disaster_board2_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            member_id INTEGER,
            body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            hidden_at TEXT
        );
        CREATE INDEX IF NOT EXISTS disaster_board2_reply_post
            ON disaster_board2_replies(post_id, id);
    """)

    for table in ("disaster_board2_posts", "disaster_board2_replies"):
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "author_name" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN author_name TEXT NOT NULL DEFAULT ''")
    conn.commit()


def author_query(table):
    # Table names are internal constants, never request parameters.
    return f"""SELECT t.*, COALESCE(NULLIF(t.author_name, ''), CASE WHEN t.member_id IS NULL THEN '管理者'
        ELSE COALESCE(m.name, '登録解除済み職員') END) AS author
        FROM {table} t LEFT JOIN members m ON m.id=t.member_id"""

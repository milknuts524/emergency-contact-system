from datetime import datetime


STATUSES = {
    "available": {
        "symbol": "○",
        "label": "空床あり",
        "message": "受け入れ相談可能です",
        "class_name": "available",
    },
    "inquiry": {
        "symbol": "△",
        "label": "要問い合わせ",
        "message": "状況により対応可能です。お問い合わせください",
        "class_name": "inquiry",
    },
    "full": {
        "symbol": "×",
        "label": "満床",
        "message": "現在、受け入れ困難です",
        "class_name": "full",
    },
}

DEFAULT_STATUS = "inquiry"
DEFAULT_PUBLIC_NOTE = "実際の受け入れ可否は、患者様の状態や診療体制により異なります。"


def now_text():
    return datetime.now().isoformat(timespec="seconds")


def normalize_status(value):
    value = (value or "").strip()
    if value in STATUSES:
        return value
    return DEFAULT_STATUS


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bed_status_current (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            status TEXT NOT NULL,
            public_note TEXT,
            internal_note TEXT,
            updated_by TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bed_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL,
            public_note TEXT,
            internal_note TEXT,
            updated_by TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    now = now_text()
    conn.execute(
        """
        INSERT OR IGNORE INTO bed_status_current (
            id,
            status,
            public_note,
            internal_note,
            updated_by,
            updated_at
        )
        VALUES (1, ?, ?, '', '', ?)
        """,
        (DEFAULT_STATUS, DEFAULT_PUBLIC_NOTE, now)
    )
    conn.commit()


def with_display_fields(row):
    item = dict(row)
    status_key = normalize_status(item.get("status"))
    status = STATUSES[status_key]
    item["status"] = status_key
    item["symbol"] = status["symbol"]
    item["label"] = status["label"]
    item["message"] = status["message"]
    item["class_name"] = status["class_name"]
    return item


def get_current(conn):
    row = conn.execute(
        "SELECT * FROM bed_status_current WHERE id = 1"
    ).fetchone()
    if not row:
        init_db(conn)
        row = conn.execute(
            "SELECT * FROM bed_status_current WHERE id = 1"
        ).fetchone()
    return with_display_fields(row)


def update_status(conn, status, public_note="", internal_note="", updated_by=""):
    status = normalize_status(status)
    public_note = (public_note or "").strip()
    internal_note = (internal_note or "").strip()
    updated_by = (updated_by or "").strip()
    now = now_text()
    conn.execute(
        """
        UPDATE bed_status_current
        SET status = ?,
            public_note = ?,
            internal_note = ?,
            updated_by = ?,
            updated_at = ?
        WHERE id = 1
        """,
        (status, public_note, internal_note, updated_by, now)
    )
    conn.execute(
        """
        INSERT INTO bed_status_history (
            status,
            public_note,
            internal_note,
            updated_by,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (status, public_note, internal_note, updated_by, now)
    )


def list_history(conn, limit=20):
    rows = conn.execute(
        """
        SELECT *
        FROM bed_status_history
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()
    return [with_display_fields(row) for row in rows]

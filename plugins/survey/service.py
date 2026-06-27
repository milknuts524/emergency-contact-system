import csv
import io
import json
from datetime import datetime


RESPONSE_TYPES = {
    "attendance": {
        "label": "出欠確認",
        "choices": ["出席", "欠席", "未定"],
    },
    "yes_no": {
        "label": "はい/いいえ",
        "choices": ["はい", "いいえ"],
    },
    "multi_choice": {
        "label": "選択式",
        "choices": [],
    },
    "free_text": {
        "label": "自由記載",
        "choices": [],
    },
}


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS surveys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            target_group TEXT,
            response_type TEXT NOT NULL,
            choices_json TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            deadline_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS survey_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            survey_id INTEGER NOT NULL,
            member_id INTEGER NOT NULL,
            response_value TEXT,
            comment TEXT,
            responded_at TEXT,
            UNIQUE(survey_id, member_id),
            FOREIGN KEY(survey_id) REFERENCES surveys(id),
            FOREIGN KEY(member_id) REFERENCES members(id)
        )
    """)
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(surveys)").fetchall()
    }
    if "target_type" not in columns:
        conn.execute("ALTER TABLE surveys ADD COLUMN target_type TEXT DEFAULT 'role_group'")
    if "target_id" not in columns:
        conn.execute("ALTER TABLE surveys ADD COLUMN target_id INTEGER")
    conn.execute("""
        UPDATE surveys
        SET target_type = CASE
            WHEN target_group IS NULL OR target_group = '' OR target_group = '全員' THEN 'all'
            ELSE 'role_group'
        END
        WHERE target_type IS NULL OR target_type = ''
    """)
    conn.commit()


def normalize_choices(text):
    choices = []
    seen = set()
    for line in (text or "").splitlines():
        choice = line.strip()
        if not choice or choice in seen:
            continue
        choices.append(choice)
        seen.add(choice)
    return choices


def survey_choices(survey):
    response_type = survey["response_type"]
    if response_type in ("attendance", "yes_no"):
        return RESPONSE_TYPES[response_type]["choices"]
    if response_type == "multi_choice":
        try:
            choices = json.loads(survey["choices_json"] or "[]")
        except json.JSONDecodeError:
            choices = []
        return [str(choice) for choice in choices if str(choice).strip()]
    return []


def survey_target_type(survey):
    target_type = survey["target_type"] if "target_type" in survey.keys() else ""
    if target_type:
        return target_type
    target_group = (survey["target_group"] or "").strip()
    return "all" if not target_group or target_group == "全員" else "role_group"


def target_type_label(target_type):
    return {
        "all": "全員",
        "role_group": "職種グループ",
        "notification_group": "通知グループ",
    }.get(target_type, target_type)


def target_label(conn, survey):
    target_type = survey_target_type(survey)
    if target_type == "all":
        return "全員"
    if target_type == "notification_group":
        group = conn.execute(
            "SELECT name FROM notification_groups WHERE id = ?",
            (survey["target_id"],)
        ).fetchone()
        return group["name"] if group else "通知グループなし"
    return survey["target_group"] or "未設定"


def member_in_notification_group(conn, member_id, group_id):
    return bool(conn.execute(
        """
        SELECT 1
        FROM member_notification_groups
        WHERE member_id = ?
          AND group_id = ?
        LIMIT 1
        """,
        (member_id, group_id)
    ).fetchone())


def is_survey_for_member(conn, survey, member):
    target_type = survey_target_type(survey)
    if target_type == "all":
        return True
    if target_type == "notification_group":
        target_id = survey["target_id"] if "target_id" in survey.keys() else None
        return bool(target_id) and member_in_notification_group(conn, member["id"], target_id)
    target_group = (survey["target_group"] or "").strip()
    return not target_group or target_group == "全員" or target_group == (member["group_name"] or "")


def is_survey_open(survey):
    if survey["is_active"] != 1:
        return False
    deadline = survey["deadline_at"] or ""
    if not deadline:
        return True
    try:
        return datetime.now() <= datetime.fromisoformat(deadline.replace("T", " "))
    except ValueError:
        return True


def list_target_groups(conn):
    rows = conn.execute("""
        SELECT DISTINCT group_name
        FROM members
        WHERE active = 1
          AND group_name IS NOT NULL
          AND group_name != ''
        ORDER BY group_name
    """).fetchall()
    return ["全員"] + [row["group_name"] for row in rows]


def list_role_groups(conn):
    return [
        group
        for group in list_target_groups(conn)
        if group != "全員"
    ]


def list_notification_groups(conn):
    return conn.execute("""
        SELECT *
        FROM notification_groups
        WHERE active = 1
          AND name != '全員'
        ORDER BY name
    """).fetchall()


def get_member_surveys(conn, member):
    rows = conn.execute("""
        SELECT
            s.*,
            sr.response_value,
            sr.responded_at
        FROM surveys s
        LEFT JOIN survey_responses sr
          ON sr.survey_id = s.id
         AND sr.member_id = ?
        WHERE s.is_active = 1
          AND (s.deadline_at IS NULL OR s.deadline_at = '' OR s.deadline_at >= ?)
          AND (
            s.target_type = 'all'
            OR (s.target_type IS NULL AND (s.target_group IS NULL OR s.target_group = '' OR s.target_group = '全員'))
            OR (COALESCE(s.target_type, 'role_group') = 'role_group' AND s.target_group = ?)
            OR (
                s.target_type = 'notification_group'
                AND EXISTS (
                    SELECT 1
                    FROM member_notification_groups mng
                    WHERE mng.member_id = ?
                      AND mng.group_id = s.target_id
                )
            )
          )
        ORDER BY
          CASE WHEN sr.id IS NULL THEN 0 ELSE 1 END,
          s.deadline_at IS NULL,
          s.deadline_at,
          s.created_at DESC
    """, (
        member["id"],
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        member["group_name"] or "",
        member["id"],
    )).fetchall()
    return [
        {
            "id": row["id"],
            "title": row["title"],
            "description": row["description"] or "",
            "deadline_at": row["deadline_at"] or "",
            "answered": bool(row["responded_at"]),
            "response_value": row["response_value"] or "",
        }
        for row in rows
    ]


def get_survey(conn, survey_id):
    return conn.execute(
        "SELECT * FROM surveys WHERE id = ?",
        (survey_id,)
    ).fetchone()


def get_member_by_code(conn, code):
    return conn.execute(
        "SELECT * FROM members WHERE code = ? AND active = 1",
        (code,)
    ).fetchone()


def response_summary(conn, survey):
    target_type = survey_target_type(survey)
    if target_type == "all":
        target_members = conn.execute(
            "SELECT * FROM members WHERE active = 1 ORDER BY group_name, name"
        ).fetchall()
    elif target_type == "notification_group":
        target_members = conn.execute("""
            SELECT DISTINCT m.*
            FROM members m
            JOIN member_notification_groups mng ON mng.member_id = m.id
            WHERE m.active = 1
              AND mng.group_id = ?
            ORDER BY m.group_name, m.name
        """, (survey["target_id"],)).fetchall()
    else:
        target_group = survey["target_group"] or ""
        target_members = conn.execute(
            "SELECT * FROM members WHERE active = 1 AND group_name = ? ORDER BY name",
            (target_group,)
        ).fetchall()

    responses = conn.execute("""
        SELECT sr.*, m.name, m.group_name
        FROM survey_responses sr
        JOIN members m ON m.id = sr.member_id
        WHERE sr.survey_id = ?
        ORDER BY sr.responded_at DESC
    """, (survey["id"],)).fetchall()
    responded_ids = {response["member_id"] for response in responses}
    unanswered = [
        member
        for member in target_members
        if member["id"] not in responded_ids
    ]
    counts = {}
    for response in responses:
        key = response["response_value"] or "未入力"
        counts[key] = counts.get(key, 0) + 1

    return {
        "target_members": target_members,
        "responses": responses,
        "unanswered": unanswered,
        "counts": counts,
    }


def survey_csv_text(conn, survey):
    summary = response_summary(conn, survey)
    responses_by_member = {
        response["member_id"]: response
        for response in summary["responses"]
    }
    target_type = survey_target_type(survey)
    target_name = target_label(conn, survey)
    output = io.StringIO()
    writer = csv.writer(output)
    output.write("\ufeff")
    writer.writerow([
        "survey_id",
        "title",
        "target_type",
        "target_name",
        "member_id",
        "name",
        "group_name",
        "response_status",
        "response_value",
        "comment",
        "responded_at",
    ])
    for member in summary["target_members"]:
        response = responses_by_member.get(member["id"])
        writer.writerow([
            survey["id"],
            survey["title"],
            target_type,
            target_name,
            member["id"],
            member["name"],
            member["group_name"],
            "回答済み" if response else "未回答",
            response["response_value"] if response else "",
            response["comment"] if response else "",
            response["responded_at"] if response else "",
        ])
    return output.getvalue()

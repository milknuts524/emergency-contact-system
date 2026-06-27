from datetime import date, datetime, time, timedelta, timezone
import os
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


CALENDAR_CACHE_SECONDS = 600
CALENDAR_HORIZON_DAYS = 183
LOCAL_TIMEZONE = ZoneInfo("Asia/Tokyo")

_cache = {
    "url": "",
    "fetched_at": "",
    "expires_at": None,
    "events": [],
    "error": "",
}


def get_calendar_ics_url():
    return os.getenv("CALENDAR_ICS_URL", "").strip()


def get_calendar_status():
    return {
        "ics_url": get_calendar_ics_url(),
        "last_fetch_at": _cache["fetched_at"],
        "last_error": _cache["error"],
    }


def _unfold_ics_lines(text):
    lines = []
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] += raw_line[1:]
        else:
            lines.append(raw_line)
    return lines


def _parse_content_line(line):
    if ":" not in line:
        return None, {}, ""
    name_part, value = line.split(":", 1)
    parts = name_part.split(";")
    name = parts[0].upper()
    params = {}
    for part in parts[1:]:
        if "=" in part:
            key, param_value = part.split("=", 1)
            params[key.upper()] = param_value
    return name, params, value


def _clean_text(value):
    return (
        (value or "")
        .replace("\\n", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def _parse_ics_datetime(value, params):
    value = (value or "").strip()
    if not value:
        return None, False

    if params.get("VALUE", "").upper() == "DATE" or len(value) == 8:
        parsed_date = datetime.strptime(value[:8], "%Y%m%d").date()
        return datetime.combine(parsed_date, time.min, tzinfo=LOCAL_TIMEZONE), True

    tzid = params.get("TZID", "")
    if value.endswith("Z"):
        parsed = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
        return parsed.replace(tzinfo=timezone.utc).astimezone(LOCAL_TIMEZONE), False

    parsed = datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    if tzid:
        try:
            return parsed.replace(tzinfo=ZoneInfo(tzid)).astimezone(LOCAL_TIMEZONE), False
        except Exception:
            pass
    return parsed.replace(tzinfo=LOCAL_TIMEZONE), False


def _parse_ics_events(text):
    events = []
    current = None

    for line in _unfold_ics_lines(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current:
                events.append(current)
            current = None
            continue
        if current is None:
            continue

        name, params, value = _parse_content_line(line)
        if name == "DTSTART":
            current["start"], current["all_day"] = _parse_ics_datetime(value, params)
        elif name == "DTEND":
            current["end"], _ = _parse_ics_datetime(value, params)
        elif name == "SUMMARY":
            current["title"] = _clean_text(value)
        elif name == "LOCATION":
            current["location"] = _clean_text(value)
        elif name == "DESCRIPTION":
            current["description"] = _clean_text(value)

    return events


def _format_event(event):
    start = event["start"]
    end = event.get("end")
    all_day = event.get("all_day", False)
    if all_day:
        start_time = ""
        end_time = ""
    else:
        start_time = start.strftime("%H:%M")
        end_time = end.strftime("%H:%M") if end else ""

    description = event.get("description", "").strip()
    short_description = description.replace("\n", " ")
    if len(short_description) > 80:
        short_description = short_description[:80] + "..."

    return {
        "date": start.strftime("%Y-%m-%d"),
        "weekday": "月火水木金土日"[start.weekday()],
        "start_time": start_time,
        "end_time": end_time,
        "title": event.get("title", "予定"),
        "location": event.get("location", ""),
        "description": short_description,
    }


def _group_events(events, now, days=30, include_later=True):
    today = now.date()
    tomorrow = today + timedelta(days=1)
    week_until = today + timedelta(days=days)
    groups = [
        {"key": "today", "label": "今日", "events": []},
        {"key": "tomorrow", "label": "明日", "events": []},
        {"key": "week", "label": f"今後{days}日間", "events": []},
    ]
    if include_later:
        groups.append({"key": "later", "label": "今後半年", "events": []})

    for event in events:
        event_date = event["start"].date()
        formatted = _format_event(event)
        if event_date == today:
            groups[0]["events"].append(formatted)
        elif event_date == tomorrow:
            groups[1]["events"].append(formatted)
        elif event_date <= week_until:
            groups[2]["events"].append(formatted)
        elif include_later:
            groups[3]["events"].append(formatted)

    return [group for group in groups if group["events"]]


def fetch_calendar_events(force=False, days=30, include_later=True, horizon_days=CALENDAR_HORIZON_DAYS):
    url = get_calendar_ics_url()
    now = datetime.now(LOCAL_TIMEZONE)

    if not url:
        _cache["error"] = "CALENDAR_ICS_URL is not set"
        return {
            "ok": False,
            "error": "予定を取得できません",
            "groups": [],
            "last_fetch_at": _cache["fetched_at"],
            "ics_url": url,
        }

    if (
        not force
        and _cache["url"] == url
        and _cache["expires_at"] is not None
        and now < _cache["expires_at"]
    ):
        return {
            "ok": not bool(_cache["error"]),
            "error": "予定を取得できません" if _cache["error"] else "",
            "groups": _group_events(_cache["events"], now, days=days, include_later=include_later),
            "last_fetch_at": _cache["fetched_at"],
            "ics_url": url,
        }

    try:
        request = Request(url, headers={"User-Agent": "EmergencyContactSystem/1.0"})
        with urlopen(request, timeout=8) as response:
            content = response.read()
        text = content.decode("utf-8-sig")
        parsed_events = _parse_ics_events(text)
        horizon = now + timedelta(days=horizon_days)
        events = []
        for event in parsed_events:
            start = event.get("start")
            if not start:
                continue
            end = event.get("end") or start
            if end < now or start > horizon:
                continue
            events.append(event)
        events.sort(key=lambda item: item["start"])

        _cache.update({
            "url": url,
            "fetched_at": now.strftime("%Y-%m-%d %H:%M"),
            "expires_at": now + timedelta(seconds=CALENDAR_CACHE_SECONDS),
            "events": events,
            "error": "",
        })
    except Exception as exc:
        _cache.update({
            "url": url,
            "fetched_at": _cache["fetched_at"],
            "expires_at": now + timedelta(seconds=CALENDAR_CACHE_SECONDS),
            "events": [],
            "error": str(exc),
        })

    return {
        "ok": not bool(_cache["error"]),
        "error": "予定を取得できません" if _cache["error"] else "",
        "groups": _group_events(_cache["events"], now, days=days, include_later=include_later),
        "last_fetch_at": _cache["fetched_at"],
        "ics_url": url,
    }

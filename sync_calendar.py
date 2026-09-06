from __future__ import annotations

import html
import json
import os
import re
import ssl
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CANVAS_COURSE_RE = re.compile(r"/courses/(\d+)(?:/|$)")
CANVAS_ASSIGNMENT_RE = re.compile(r"/assignments/(\d+)(?:/|$)")
URL_RE = re.compile(r"https?://[^\s<>'\"]+")
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class IcsProperty:
    value: str
    params: dict[str, str]


@dataclass(frozen=True)
class EventRecord:
    uid: str
    title: str
    event_type: str
    starts_at: str
    ends_at: str | None
    all_day: bool
    course_id: str | None
    course: str | None
    assignment_id: str | None
    source_url: str | None
    location: str | None
    description: str | None
    rrule: str | None = None
    source: str = "canvas_ics"


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def load_aliases() -> dict[str, str]:
    raw = os.getenv("CANVAS_COURSE_ALIASES_JSON", "{}").strip() or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CANVAS_COURSE_ALIASES_JSON must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("CANVAS_COURSE_ALIASES_JSON must be a JSON object")
    return {str(k): str(v) for k, v in parsed.items() if str(v).strip()}


def unescape_ics_text(value: str) -> str:
    # RFC 5545 TEXT escaping. Order matters: decode escaped backslash last.
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
    )


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = unescape_ics_text(value)
    text = html.unescape(TAG_RE.sub(" ", text))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def unfold_ics(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    unfolded: list[str] = []
    for line in normalized.split("\n"):
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    return unfolded


def parse_property(line: str) -> tuple[str, IcsProperty] | None:
    if ":" not in line:
        return None
    left, value = line.split(":", 1)
    parts = left.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, param_value = part.split("=", 1)
            params[key.upper()] = param_value.strip('"')
    return name, IcsProperty(value=value, params=params)


def parse_vevents(ics_bytes: bytes) -> list[dict[str, list[IcsProperty]]]:
    text = ics_bytes.decode("utf-8-sig", errors="replace")
    if "BEGIN:VCALENDAR" not in text[:4096]:
        raise RuntimeError("Canvas calendar response was not an iCalendar feed")

    events: list[dict[str, list[IcsProperty]]] = []
    current: dict[str, list[IcsProperty]] | None = None

    for line in unfold_ics(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(current)
            current = None
            continue
        if current is None:
            continue
        parsed = parse_property(line)
        if parsed is None:
            continue
        name, prop = parsed
        current.setdefault(name, []).append(prop)

    return events


def first(event: dict[str, list[IcsProperty]], name: str) -> IcsProperty | None:
    values = event.get(name.upper(), [])
    return values[0] if values else None


def parse_ics_datetime(prop: IcsProperty, target_tz: ZoneInfo) -> tuple[date | datetime, bool]:
    value = prop.value.strip()
    value_type = prop.params.get("VALUE", "").upper()
    if value_type == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value[:8], "%Y%m%d").date(), True

    is_utc = value.endswith("Z")
    raw = value[:-1] if is_utc else value
    formats = ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M")
    parsed: datetime | None = None
    for fmt in formats:
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        raise ValueError(f"Unsupported iCalendar datetime: {value}")

    if is_utc:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        tzid = prop.params.get("TZID")
        if tzid:
            try:
                parsed = parsed.replace(tzinfo=ZoneInfo(tzid))
            except ZoneInfoNotFoundError:
                parsed = parsed.replace(tzinfo=target_tz)
        else:
            parsed = parsed.replace(tzinfo=target_tz)
    return parsed.astimezone(target_tz), False


def to_local_iso(value: date | datetime, tz: ZoneInfo) -> tuple[str, bool]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        return value.astimezone(tz).isoformat(), False
    return value.isoformat(), True


def candidate_urls(event: dict[str, list[IcsProperty]]) -> list[str]:
    urls: list[str] = []
    direct = first(event, "URL")
    if direct:
        urls.append(unescape_ics_text(direct.value))
    for field in ("DESCRIPTION", "LOCATION"):
        prop = first(event, field)
        if prop:
            urls.extend(URL_RE.findall(unescape_ics_text(prop.value)))
    return list(dict.fromkeys(urls))


def choose_canvas_url(urls: Iterable[str]) -> str | None:
    urls = list(urls)
    for url in urls:
        if "/courses/" in url:
            return url.rstrip(".,);]")
    return urls[0].rstrip(".,);]") if urls else None


def primary_datetime(record: EventRecord, tz: ZoneInfo) -> datetime:
    if record.all_day:
        d = date.fromisoformat(record.starts_at)
        return datetime.combine(d, time.min, tzinfo=tz)
    dt = datetime.fromisoformat(record.starts_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def parse_event(event: dict[str, list[IcsProperty]], tz: ZoneInfo, aliases: dict[str, str]) -> EventRecord | None:
    dtstart = first(event, "DTSTART")
    if not dtstart:
        return None

    start_value, all_day = parse_ics_datetime(dtstart, tz)
    starts_at = to_local_iso(start_value, tz)[0]

    dtend = first(event, "DTEND")
    ends_at = None
    if dtend:
        end_value, _ = parse_ics_datetime(dtend, tz)
        ends_at = to_local_iso(end_value, tz)[0]

    urls = candidate_urls(event)
    source_url = choose_canvas_url(urls)
    url_blob = " ".join(urls)

    course_match = CANVAS_COURSE_RE.search(url_blob)
    course_id = course_match.group(1) if course_match else None
    assignment_match = CANVAS_ASSIGNMENT_RE.search(url_blob)
    assignment_id = assignment_match.group(1) if assignment_match else None

    uid_prop = first(event, "UID")
    uid = uid_prop.value.strip() if uid_prop else ""
    event_type = "assignment" if assignment_id or "assignment" in uid.lower() else "event"

    summary = first(event, "SUMMARY")
    description = first(event, "DESCRIPTION")
    location = first(event, "LOCATION")
    rrule = first(event, "RRULE")

    title = clean_text(summary.value if summary else None) or "Untitled Canvas event"
    course = aliases.get(course_id) if course_id else None

    return EventRecord(
        uid=uid or f"generated:{title}:{starts_at}",
        title=title,
        event_type=event_type,
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=all_day,
        course_id=course_id,
        course=course,
        assignment_id=assignment_id,
        source_url=source_url,
        location=clean_text(location.value if location else None),
        description=clean_text(description.value if description else None),
        rrule=rrule.value if rrule else None,
    )


def fetch_calendar(feed_url: str) -> bytes:
    parsed = urlparse(feed_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("CANVAS_CALENDAR_FEED_URL must be a valid HTTPS URL")

    request = Request(feed_url, headers={"User-Agent": "academic-context-canvas-sync/1.0"})
    try:
        with urlopen(request, timeout=30, context=ssl.create_default_context()) as response:
            if response.status != 200:
                raise RuntimeError(f"Canvas calendar request returned HTTP {response.status}")
            content = response.read()
    except HTTPError as exc:
        raise RuntimeError(f"Canvas calendar request returned HTTP {exc.code}") from None
    except URLError as exc:
        # Avoid interpolating exc because some implementations include the credential-bearing URL.
        raise RuntimeError("Canvas calendar request failed") from exc

    if b"BEGIN:VCALENDAR" not in content[:4096]:
        raise RuntimeError("Canvas calendar response was not an iCalendar feed")
    return content


def parse_calendar(
    ics_bytes: bytes,
    tz: ZoneInfo,
    aliases: dict[str, str],
    window_start: datetime,
    window_end: datetime,
) -> list[EventRecord]:
    records: list[EventRecord] = []
    seen: set[tuple[str, str]] = set()
    for event in parse_vevents(ics_bytes):
        record = parse_event(event, tz, aliases)
        if record is None:
            continue
        when = primary_datetime(record, tz)
        if not (window_start <= when <= window_end):
            continue
        key = (record.uid, record.starts_at)
        if key in seen:
            continue
        seen.add(key)
        records.append(record)

    records.sort(key=lambda r: primary_datetime(r, tz))
    return records


def record_to_dict(record: EventRecord) -> dict[str, Any]:
    data = asdict(record)
    if record.event_type == "assignment":
        data["due_at"] = record.starts_at
    return data


def build_context(records: list[EventRecord], now: datetime, upcoming_days: int, tz: ZoneInfo) -> str:
    future = [r for r in records if primary_datetime(r, tz) >= now]
    next_7 = [r for r in future if primary_datetime(r, tz) <= now + timedelta(days=7)]
    next_window = [r for r in future if primary_datetime(r, tz) <= now + timedelta(days=upcoming_days)]

    by_day: dict[date, list[EventRecord]] = defaultdict(list)
    for record in next_window:
        by_day[primary_datetime(record, tz).date()].append(record)

    course_counts = Counter((r.course or (f"course {r.course_id}" if r.course_id else "unmapped")) for r in next_window)
    recurring_count = sum(1 for r in records if r.rrule)

    lines = [
        "# Canvas Academic Context",
        "",
        f"Last synced: {now.isoformat()}",
        "Source: Canvas iCal feed (read-only snapshot)",
        "Freshness rule: treat this file as stale if `Last synced` is older than the planning task permits.",
        "",
        "## Workload Summary",
        "",
        f"- Due/events in next 7 days: {len(next_7)}",
        f"- Due/events in next {upcoming_days} days: {len(next_window)}",
    ]

    if course_counts:
        lines.append("- Upcoming by course:")
        for course, count in sorted(course_counts.items()):
            lines.append(f"  - {course}: {count}")

    lines.extend(["", f"## Next {upcoming_days} Days", ""])
    if not by_day:
        lines.append("No Canvas assignments or calendar events are currently in this window.")
    else:
        for day in sorted(by_day):
            # strftime %-d is supported by the Linux runner used by this workflow.
            lines.append(f"### {day.strftime('%A, %B %-d, %Y')}")
            lines.append("")
            for record in by_day[day]:
                dt = primary_datetime(record, tz)
                course = record.course or (f"course {record.course_id}" if record.course_id else "Canvas")
                kind = "Assignment" if record.event_type == "assignment" else "Event"
                when = "All day" if record.all_day else dt.strftime("%-I:%M %p %Z")
                lines.append(f"- **{course} — {record.title}**")
                lines.append(f"  - {kind}; {when}")
                if record.source_url:
                    lines.append(f"  - Canvas: {record.source_url}")
            lines.append("")

    lines.extend([
        "## Coverage Notes",
        "",
        "- This snapshot contains Canvas calendar assignments and events only.",
        "- Canvas To-Do items, module completion, submission state, and grades require the Canvas API and are not inferred here.",
        "- `calendar.json` is the normalized evidence source when exact metadata is needed.",
    ])
    if recurring_count:
        lines.append(f"- {recurring_count} source event(s) contain RRULE recurrence metadata; this Phase 1 parser preserves RRULE but does not synthesize missing recurrence instances.")
    lines.append("")
    return "\n".join(lines)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run_sync(ics_bytes: bytes | None = None, now: datetime | None = None) -> dict[str, Any]:
    tz_name = os.getenv("CANVAS_TIMEZONE", "America/Chicago")
    tz = ZoneInfo(tz_name)
    now = now.astimezone(tz) if now else datetime.now(tz)

    past_days = env_int("CANVAS_PAST_DAYS", 30)
    future_days = env_int("CANVAS_FUTURE_DAYS", 366)
    upcoming_days = env_int("CANVAS_UPCOMING_DAYS", 30)
    output_dir = Path(os.getenv("CANVAS_OUTPUT_DIR", "canvas"))
    aliases = load_aliases()

    if ics_bytes is None:
        feed_url = os.getenv("CANVAS_CALENDAR_FEED_URL", "").strip()
        if not feed_url:
            raise RuntimeError("CANVAS_CALENDAR_FEED_URL is required")
        ics_bytes = fetch_calendar(feed_url)

    window_start = now - timedelta(days=past_days)
    window_end = now + timedelta(days=future_days)
    records = parse_calendar(ics_bytes, tz, aliases, window_start, window_end)

    all_data = [record_to_dict(r) for r in records]
    upcoming_records = [
        r for r in records
        if now <= primary_datetime(r, tz) <= now + timedelta(days=upcoming_days)
    ]
    upcoming_data = [record_to_dict(r) for r in upcoming_records]

    sync_status = {
        "status": "ok",
        "source": "canvas_ics",
        "last_synced": now.isoformat(),
        "timezone": tz_name,
        "record_count": len(records),
        "upcoming_record_count": len(upcoming_records),
        "coverage": {
            "past_days": past_days,
            "future_days": future_days,
            "upcoming_days": upcoming_days,
        },
        "limitations": [
            "Canvas To-Do items are not present in iCal feeds.",
            "Submission state, grades, and module completion are not available from iCal alone.",
            "RRULE metadata is preserved but recurrence instances are not synthesized by this Phase 1 parser.",
        ],
    }

    atomic_write_json(output_dir / "calendar.json", all_data)
    atomic_write_json(output_dir / "upcoming.json", upcoming_data)
    atomic_write_json(output_dir / "sync_status.json", sync_status)
    atomic_write_text(output_dir / "ACADEMIC_CONTEXT.md", build_context(records, now, upcoming_days, tz))

    return sync_status


def main() -> int:
    try:
        status = run_sync()
    except Exception as exc:
        print(f"Canvas sync failed: {exc}", file=sys.stderr)
        return 1

    print(
        "Canvas sync complete: "
        f"{status['record_count']} records; "
        f"{status['upcoming_record_count']} upcoming."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

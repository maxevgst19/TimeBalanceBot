from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.bot.notifier import _note_message


def test_day_note_is_sent_after_nine_and_escaped():
    tz = ZoneInfo("Europe/Moscow")
    note = {"event_id": None, "text": "Взять <форму>"}
    assert _note_message(note, [], datetime(2026, 11, 9, 8, 59, tzinfo=tz)) is None
    assert "&lt;форму&gt;" in _note_message(note, [], datetime(2026, 11, 9, 9, tzinfo=tz))


def test_event_note_is_sent_in_fifteen_minute_window():
    now = datetime(2026, 11, 9, 15, 45, tzinfo=ZoneInfo("Europe/Moscow"))
    block = SimpleNamespace(kind="event", source_id="event-1", title="Секция", starts_at=now + timedelta(minutes=15))
    note = {"event_id": "event-1", "text": "Взять воду"}
    assert "Секция" in _note_message(note, [block], now)
    assert _note_message(note, [block], now - timedelta(seconds=1)) is None
    assert _note_message(note, [block], now + timedelta(minutes=16)) is None

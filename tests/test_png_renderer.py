from datetime import datetime
from types import SimpleNamespace

from PIL import ImageFont

from iris_timelineexport_module.timeline_handler import png_renderer as renderer


def _fake_event(*, dt, tz, title, category_name, comment):
    return SimpleNamespace(
        event_date=dt,
        event_tz=tz,
        event_title=title,
        category=[SimpleNamespace(name=category_name)],
        custom_attributes={
            "Timeline Export": {
                "Export Comment": {"value": comment},
            }
        },
    )


def test_hex_to_rgb_valid_and_invalid_values():
    assert renderer._hex_to_rgb("#AE0C0C") == (174, 12, 12)
    assert renderer._hex_to_rgb("AE0C0C") == (174, 12, 12)
    assert renderer._hex_to_rgb("#XYZ123") is None
    assert renderer._hex_to_rgb("#123") is None


def test_parse_comment_detects_levels():
    items = renderer._parse_comment("line0\n- line1\n-- line2")
    assert [item.level for item in items] == [1, 1, 2]
    assert [item.text for item in items] == ["line0", "line1", "line2"]


def test_to_utc_with_offset_string_converts_correctly():
    dt = datetime(2026, 4, 20, 12, 0, 0)
    utc = renderer._to_utc(dt, "+02:00")
    assert utc == datetime(2026, 4, 20, 10, 0, 0)


def test_to_utc_with_named_timezone_converts_correctly():
    dt = datetime(2026, 4, 20, 12, 0, 0)
    utc = renderer._to_utc(dt, "Europe/Zurich")
    assert utc == datetime(2026, 4, 20, 10, 0, 0)


def test_wrap_splits_single_very_long_word():
    font = ImageFont.load_default()
    text = "A" * 120
    lines = renderer._wrap(text, font, max_px=20)
    assert len(lines) > 1
    assert "".join(lines) == text


def test_render_empty_returns_png_bytes():
    data = renderer._render_empty("Case X", 800, "#AE0C0C")
    assert isinstance(data, bytes)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_with_events_returns_png_bytes():
    events = [
        _fake_event(
            dt=datetime(2026, 4, 20, 12, 0, 0),
            tz="+00:00",
            title="Initial Access",
            category_name="Compromise",
            comment="- IOC observed\n-- child note",
        ),
        _fake_event(
            dt=datetime(2026, 4, 20, 13, 0, 0),
            tz="+00:00",
            title="Credential Use",
            category_name="Privilege Escalation",
            comment="Summary line",
        ),
    ]

    data = renderer.render(events, "Case Example", title_hex="#AE0C0C")
    assert isinstance(data, bytes)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_render_with_invalid_title_color_falls_back_and_logs_warning(caplog):
    event = _fake_event(
        dt=datetime(2026, 4, 20, 12, 0, 0),
        tz="+00:00",
        title="Some Title",
        category_name="Category",
        comment="note",
    )

    with caplog.at_level("WARNING"):
        data = renderer.render([event], "Case With Invalid Color", title_hex="#BAD")

    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert "Invalid title_hex value" in caplog.text


def test_render_with_missing_category_uses_unknown():
    event = SimpleNamespace(
        event_date=datetime(2026, 4, 20, 12, 0, 0),
        event_tz="+00:00",
        event_title="No Category Event",
        category=[],
        custom_attributes={
            "Timeline Export": {
                "Export Comment": {"value": "comment"},
            }
        },
    )

    data = renderer.render([event], "Case No Category")
    assert data.startswith(b"\x89PNG\r\n\x1a\n")

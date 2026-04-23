"""
Ensures the 'Timeline Export' custom-attribute tab exists for the
'event' entity type and propagates it to all existing events.
Also manages a 'Timeline Export' tab on the case level for the
anonymization map.

IRIS ships with an empty CustomAttribute record for 'event'
(attribute_content={}).  We merge our tab into that record so it
co-exists with any other module's tabs.
"""

from __future__ import annotations

ATTRIBUTE_FOR           = "event"
ATTRIBUTE_TAB           = "Timeline Export"
FIELD_INCLUDE           = "Include in Export"
FIELD_HIGHLIGHT         = "Highlight"
FIELD_COMMENT           = "Export Comment"
FIELD_HINT              = "Comment format"
FIELD_OVERRIDE_CATEGORY = "Override Event Category"

# ── Case-level attributes ────────────────────────────────────────────────────
CASE_ATTRIBUTE_FOR       = "case"
CASE_ATTRIBUTE_TAB       = "Timeline Export"
CASE_FIELD_ANON_MAP      = "Anonymization Map"
CASE_FIELD_ANON_HINT     = "Anonymization hint"

_OUR_CASE_TAB_TEMPLATE = {
    CASE_FIELD_ANON_MAP: {
        "type": "input_textfield",
        "value": "",
        "mandatory": False,
    },
    CASE_FIELD_ANON_HINT: {
        "type": "html",
        "value": (
            "<small class='text-muted'>One substitution per line: "
            "<code>original=replacement</code>. "
            "Escape a literal <code>=</code> in the original with <code>\\=</code> "
            "(e.g. <code>example.com?a\\=1=&lt;redacted&gt;</code>). "
            "Lines starting with <code>#</code> are ignored.</small>"
        ),
    },
}

# Guards repeated full-table backfill within the same worker process lifetime.
# Once every existing event has been checked after startup, there is no need to
# scan the whole table on every subsequent hook-registration call.
_backfill_done: bool = False
_case_backfill_done: bool = False

_OUR_TAB_TEMPLATE = {
    FIELD_INCLUDE: {
        "type": "input_checkbox",
        "value": False,
        "mandatory": False,
    },
    FIELD_HIGHLIGHT: {
        "type": "input_checkbox",
        "value": False,
        "mandatory": False,
    },
    FIELD_COMMENT: {
        "type": "input_textfield",
        "value": "",
        "mandatory": False,
    },
    FIELD_HINT: {
        "type": "html",
        "value": "<small class='text-muted'>Prefix lines with <code>-</code> for level-1 bullets or <code>--</code> for level-2 bullets.</small>",
    },
    FIELD_OVERRIDE_CATEGORY: {
        "type": "input_string",
        "value": "",
        "mandatory": False,
    },
}


def ensure_attribute_exists(logger) -> None:
    """Create or update the Timeline Export custom-attribute for events."""
    try:
        from app import db
        from app.models.models import CustomAttribute
        from sqlalchemy.orm.attributes import flag_modified

        ca = CustomAttribute.query.filter(
            CustomAttribute.attribute_for == ATTRIBUTE_FOR
        ).first()

        if ca is None:
            # Shouldn't happen (IRIS post_init creates it), but handle it.
            ca = CustomAttribute()
            ca.attribute_for = ATTRIBUTE_FOR
            ca.attribute_display_name = "Events"
            ca.attribute_description = "Defines default attributes for Events"
            ca.attribute_content = {ATTRIBUTE_TAB: _OUR_TAB_TEMPLATE}
            db.session.add(ca)
            db.session.commit()
            logger.info("Created CustomAttribute for events with Timeline Export tab")
        else:
            content = ca.attribute_content or {}
            if ATTRIBUTE_TAB not in content:
                content[ATTRIBUTE_TAB] = _OUR_TAB_TEMPLATE
                ca.attribute_content = content
                flag_modified(ca, "attribute_content")
                db.session.commit()
                logger.info("Added Timeline Export tab to event custom attributes")
            else:
                changed = False
                for field_name, field_def in _OUR_TAB_TEMPLATE.items():
                    if field_name not in content[ATTRIBUTE_TAB]:
                        content[ATTRIBUTE_TAB][field_name] = field_def
                        changed = True
                        logger.info("Added missing field '%s' to Timeline Export tab", field_name)
                if changed:
                    ca.attribute_content = content
                    flag_modified(ca, "attribute_content")
                    db.session.commit()

        # Propagate to individual event records once per process lifetime.
        # Never calls update_all_attributes — that function resets entire tab
        # values with partial_overwrite=True, wiping user-entered data.
        global _backfill_done
        if not _backfill_done:
            _propagate_missing_fields(logger)
            _backfill_done = True

    except Exception:
        logger.exception("Failed to ensure Timeline Export custom attribute")


def _propagate_missing_fields(logger) -> None:
    """Add any fields from _OUR_TAB_TEMPLATE that are absent from existing event records.

    Handles two cases:
    - Tab entirely absent: adds the full template (preserving all other tabs).
    - Tab present but missing fields: adds only the missing fields.
    Never touches existing field values — purely additive.
    """
    try:
        from app import db
        from app.models.cases import CasesEvent
        from sqlalchemy.orm.attributes import flag_modified
        import copy

        events = CasesEvent.query.all()
        updated = 0
        for event in events:
            attrs = event.custom_attributes or {}
            tab = attrs.get(ATTRIBUTE_TAB)
            changed = False

            if tab is None:
                # Tab missing entirely — add it with default values
                attrs[ATTRIBUTE_TAB] = copy.deepcopy(_OUR_TAB_TEMPLATE)
                changed = True
            else:
                for field_name, field_def in _OUR_TAB_TEMPLATE.items():
                    if field_name not in tab:
                        tab[field_name] = field_def
                        changed = True

            if changed:
                event.custom_attributes = attrs
                flag_modified(event, "custom_attributes")
                updated += 1

        if updated:
            db.session.commit()
            logger.info("Backfilled missing Timeline Export fields on %d event(s)", updated)
    except Exception:
        logger.exception("Failed to backfill Timeline Export fields on existing events")


# ── Case-level attribute (anonymization map) ──────────────────────────────────


def ensure_case_attribute_exists(logger) -> None:
    """Create or update the Timeline Export custom-attribute tab for cases."""
    try:
        from app import db
        from app.models.models import CustomAttribute
        from sqlalchemy.orm.attributes import flag_modified

        ca = CustomAttribute.query.filter(
            CustomAttribute.attribute_for == CASE_ATTRIBUTE_FOR
        ).first()

        if ca is None:
            ca = CustomAttribute()
            ca.attribute_for = CASE_ATTRIBUTE_FOR
            ca.attribute_display_name = "Cases"
            ca.attribute_description = "Defines default attributes for Cases"
            ca.attribute_content = {CASE_ATTRIBUTE_TAB: _OUR_CASE_TAB_TEMPLATE}
            db.session.add(ca)
            db.session.commit()
            logger.info("Created case CustomAttribute with Timeline Export tab")
        else:
            content = ca.attribute_content or {}
            if CASE_ATTRIBUTE_TAB not in content:
                content[CASE_ATTRIBUTE_TAB] = _OUR_CASE_TAB_TEMPLATE
                ca.attribute_content = content
                flag_modified(ca, "attribute_content")
                db.session.commit()
                logger.info("Added Timeline Export tab to case custom attributes")
            else:
                changed = False
                for field_name, field_def in _OUR_CASE_TAB_TEMPLATE.items():
                    if field_name not in content[CASE_ATTRIBUTE_TAB]:
                        content[CASE_ATTRIBUTE_TAB][field_name] = field_def
                        changed = True
                        logger.info("Added missing case field '%s' to Timeline Export tab", field_name)
                if changed:
                    ca.attribute_content = content
                    flag_modified(ca, "attribute_content")
                    db.session.commit()

        # Propagate to individual case records once per process lifetime.
        global _case_backfill_done
        if not _case_backfill_done:
            _propagate_missing_case_fields(logger)
            _case_backfill_done = True

    except Exception:
        logger.exception("Failed to ensure case Timeline Export custom attribute")


def _propagate_missing_case_fields(logger) -> None:
    """Add the Timeline Export tab to all existing case records that lack it.

    Mirrors _propagate_missing_fields for events — purely additive, never
    overwrites existing values.
    """
    try:
        from app import db
        from app.models.cases import Cases
        from sqlalchemy.orm.attributes import flag_modified
        import copy

        cases = Cases.query.all()
        updated = 0
        for case in cases:
            attrs = case.custom_attributes or {}
            tab = attrs.get(CASE_ATTRIBUTE_TAB)
            changed = False

            if tab is None:
                attrs[CASE_ATTRIBUTE_TAB] = copy.deepcopy(_OUR_CASE_TAB_TEMPLATE)
                changed = True
            else:
                for field_name, field_def in _OUR_CASE_TAB_TEMPLATE.items():
                    if field_name not in tab:
                        tab[field_name] = field_def
                        changed = True

            if changed:
                case.custom_attributes = attrs
                flag_modified(case, "custom_attributes")
                updated += 1

        if updated:
            db.session.commit()
            logger.info("Backfilled missing Timeline Export fields on %d case(s)", updated)
    except Exception:
        logger.exception("Failed to backfill Timeline Export fields on existing cases")


def get_anon_map_raw(case_obj) -> str:
    """Return the raw anonymization map text from the case's custom attributes."""
    try:
        tab = (case_obj.custom_attributes or {}).get(CASE_ATTRIBUTE_TAB, {})
        return tab.get(CASE_FIELD_ANON_MAP, {}).get("value", "") or ""
    except Exception:
        return ""


def parse_anon_map(raw: str) -> dict:
    """Parse key=value lines into a substitution dict.

    Rules:
    - Separator is the first unescaped '='.
    - Literal '=' in the key must be escaped as '\\='.
    - After splitting, '\\=' is unescaped back to '=' in both key and value.
    - Lines starting with '#' are comments and are ignored.
    - Blank lines are ignored.
    - Keys and values are stripped of surrounding whitespace.

    Example:
        example.com?a\\=1 = <redacted>   ->  'example.com?a=1' -> '<redacted>'
        ACME Corp = Client A             ->  'ACME Corp' -> 'Client A'
    """
    result = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Find the first '=' that is NOT preceded by '\\'
        sep_idx = None
        i = 0
        while i < len(line):
            if line[i] == '\\' and i + 1 < len(line) and line[i + 1] == '=':
                i += 2  # skip escaped \=
                continue
            if line[i] == '=':
                sep_idx = i
                break
            i += 1
        if sep_idx is None:
            continue  # no separator found, skip line
        key   = line[:sep_idx].strip().replace('\\=', '=')
        value = line[sep_idx + 1:].strip()  # value is everything after the separator, no unescape needed
        if key:
            result[key] = value
    return result


def apply_anon_map(text: str, anon_map: dict) -> str:
    """Replace all occurrences of keys with their mapped values."""
    if not anon_map or not text:
        return text
    for key, value in anon_map.items():
        text = text.replace(key, value)
    return text


# ── Helpers to read per-event values ──────────────────────────────────────────

def _get_attribute_field(event, field_name: str, default):
    try:
        tab = (event.custom_attributes or {}).get(ATTRIBUTE_TAB, {})
        return tab.get(field_name, {}).get("value", default)
    except Exception:
        return default


def is_included(event) -> bool:
    return bool(_get_attribute_field(event, FIELD_INCLUDE, False))


def get_highlight(event) -> bool:
    return bool(_get_attribute_field(event, FIELD_HIGHLIGHT, False))


def get_comment(event) -> str:
    return _get_attribute_field(event, FIELD_COMMENT, "") or ""


def get_override_category(event) -> str:
    return (_get_attribute_field(event, FIELD_OVERRIDE_CATEGORY, "") or "").strip()


def parse_cat_colors(raw: str) -> dict:
    """Parse 'Category Name=#rrggbb' lines into a dict mapping category -> hex string.

    Rules:
    - Separator is the first '=' on the line.
    - Lines starting with '#' are ignored (comments).
    - Blank lines are ignored.
    - Keys and values are stripped of surrounding whitespace.
    """
    result = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        cat, _, hex_val = line.partition("=")
        cat = cat.strip()
        hex_val = hex_val.strip()
        if cat and hex_val:
            result[cat] = hex_val
    return result

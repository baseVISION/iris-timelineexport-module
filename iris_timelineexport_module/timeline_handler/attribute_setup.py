"""
Ensures the 'Timeline Export' custom-attribute tab exists for the
'event' entity type and propagates it to all existing events.

IRIS ships with an empty CustomAttribute record for 'event'
(attribute_content={}).  We merge our tab into that record so it
co-exists with any other module's tabs.
"""

from __future__ import annotations

ATTRIBUTE_FOR   = "event"
ATTRIBUTE_TAB   = "Timeline Export"
FIELD_INCLUDE   = "Include in Export"
FIELD_COMMENT   = "Export Comment"

# Guards repeated full-table backfill within the same worker process lifetime.
# Once every existing event has been checked after startup, there is no need to
# scan the whole table on every subsequent hook-registration call.
_backfill_done: bool = False

_OUR_TAB_TEMPLATE = {
    FIELD_INCLUDE: {
        "type": "input_checkbox",
        "value": False,
        "mandatory": False,
        "description": "Mark this event for inclusion in the timeline diagram export",
    },
    FIELD_COMMENT: {
        "type": "input_textarea",
        "value": "",
        "mandatory": False,
        "description": (
            "Details shown below this event in the diagram. "
            "Prefix lines with  -  for level-1 bullets or  --  for level-2 bullets."
        ),
    },
}


def ensure_attribute_exists(logger) -> None:
    """Create or update the Timeline Export custom-attribute for events."""
    try:
        from app import db
        from app.models.models import CustomAttribute
        from sqlalchemy.orm.attributes import flag_modified
        from app.datamgmt.manage.manage_attribute_db import update_all_attributes

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
            update_all_attributes(ATTRIBUTE_FOR, {}, partial_overwrite=True)
            return

        content = ca.attribute_content or {}

        # Backfill individual event records once per process lifetime.
        # (update_all_attributes only fills in missing *tabs*, not missing fields
        # within a tab that already exists on a record.)
        global _backfill_done
        if not _backfill_done:
            _propagate_missing_fields(logger)
            _backfill_done = True

        if ATTRIBUTE_TAB in content:
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
                update_all_attributes(ATTRIBUTE_FOR, {}, partial_overwrite=True)
        else:
            content[ATTRIBUTE_TAB] = _OUR_TAB_TEMPLATE
            ca.attribute_content = content
            flag_modified(ca, "attribute_content")
            db.session.commit()
            logger.info("Added Timeline Export tab to event custom attributes")
            update_all_attributes(ATTRIBUTE_FOR, {}, partial_overwrite=True)

    except Exception:
        logger.exception("Failed to ensure Timeline Export custom attribute")


def _propagate_missing_fields(logger) -> None:
    """Add any fields from _OUR_TAB_TEMPLATE that are absent from existing event records."""
    try:
        from app import db
        from app.models.cases import CasesEvent
        from sqlalchemy.orm.attributes import flag_modified

        events = CasesEvent.query.filter(CasesEvent.custom_attributes.isnot(None)).all()
        updated = 0
        for event in events:
            attrs = event.custom_attributes or {}
            tab = attrs.get(ATTRIBUTE_TAB)
            if tab is None:
                continue
            changed = False
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


# ── Helpers to read per-event values ──────────────────────────────────────────

def _get_attribute_field(event, field_name: str, default):
    try:
        tab = (event.custom_attributes or {}).get(ATTRIBUTE_TAB, {})
        return tab.get(field_name, {}).get("value", default)
    except Exception:
        return default


def is_included(event) -> bool:
    return bool(_get_attribute_field(event, FIELD_INCLUDE, False))


def get_comment(event) -> str:
    return _get_attribute_field(event, FIELD_COMMENT, "") or ""

from types import SimpleNamespace

from iris_timelineexport_module.timeline_handler import attribute_setup as attrs


def test_get_attribute_field_returns_default_for_missing_values():
    event = SimpleNamespace(custom_attributes={})
    value = attrs._get_attribute_field(event, attrs.FIELD_INCLUDE, False)
    assert value is False


def test_get_attribute_field_reads_nested_value():
    event = SimpleNamespace(
        custom_attributes={
            attrs.ATTRIBUTE_TAB: {
                attrs.FIELD_INCLUDE: {"value": True},
                attrs.FIELD_COMMENT: {"value": "note"},
            }
        }
    )
    assert attrs._get_attribute_field(event, attrs.FIELD_INCLUDE, False) is True
    assert attrs._get_attribute_field(event, attrs.FIELD_COMMENT, "") == "note"


def test_is_included_handles_missing_and_present_flag():
    missing = SimpleNamespace(custom_attributes={})
    enabled = SimpleNamespace(
        custom_attributes={
            attrs.ATTRIBUTE_TAB: {
                attrs.FIELD_INCLUDE: {"value": True},
            }
        }
    )
    assert attrs.is_included(missing) is False
    assert attrs.is_included(enabled) is True


def test_get_comment_returns_empty_for_none_or_missing():
    missing = SimpleNamespace(custom_attributes={})
    explicit_none = SimpleNamespace(
        custom_attributes={
            attrs.ATTRIBUTE_TAB: {
                attrs.FIELD_COMMENT: {"value": None},
            }
        }
    )
    with_text = SimpleNamespace(
        custom_attributes={
            attrs.ATTRIBUTE_TAB: {
                attrs.FIELD_COMMENT: {"value": "Export detail"},
            }
        }
    )

    assert attrs.get_comment(missing) == ""
    assert attrs.get_comment(explicit_none) == ""
    assert attrs.get_comment(with_text) == "Export detail"

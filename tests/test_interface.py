import datetime
import importlib
import logging
import sys
import warnings
from types import ModuleType, SimpleNamespace


class _FakeResult:
    def __init__(self, success, data=None, logs=None, message=""):
        self.success = success
        self.data = data
        self.logs = logs or []
        self.message = message


class _FakeIrisInterfaceStatus:
    @staticmethod
    def I2Success(data=None, logs=None, message=""):
        return _FakeResult(True, data=data, logs=logs, message=message)

    @staticmethod
    def I2Error(data=None, logs=None, message=""):
        return _FakeResult(False, data=data, logs=logs, message=message)


class _FakeIrisModuleTypes:
    module_processor = "module_processor"


class _FakeIrisModuleInterface:
    def __init__(self):
        self.log = logging.getLogger("test.interface")
        self.message_queue = []

    def register_to_hook(self, *args, **kwargs):
        return None

    def get_configuration_dict(self):
        return SimpleNamespace(is_success=lambda: False, get_data=lambda: {})


def _load_interface_module(monkeypatch):
    iris_interface_mod = ModuleType("iris_interface")
    iris_interface_mod.IrisInterfaceStatus = _FakeIrisInterfaceStatus

    iris_interface_submod = ModuleType("iris_interface.IrisModuleInterface")
    iris_interface_submod.IrisModuleInterface = _FakeIrisModuleInterface
    iris_interface_submod.IrisModuleTypes = _FakeIrisModuleTypes

    monkeypatch.setitem(sys.modules, "iris_interface", iris_interface_mod)
    monkeypatch.setitem(
        sys.modules,
        "iris_interface.IrisModuleInterface",
        iris_interface_submod,
    )

    module = importlib.import_module("iris_timelineexport_module.IrisTimelineExportInterface")
    return importlib.reload(module)


def test_hooks_handler_routes_manual_trigger(monkeypatch):
    module = _load_interface_module(monkeypatch)
    interface = module.IrisTimelineExportInterface()

    expected = _FakeResult(True, data="ok", logs=[])
    monkeypatch.setattr(interface, "_handle_export", lambda data: expected)

    result = interface.hooks_handler("on_manual_trigger_case", "Export Timeline Diagram", ["x"])
    assert result is expected


def test_hooks_handler_unknown_hook_returns_success(monkeypatch):
    module = _load_interface_module(monkeypatch)
    interface = module.IrisTimelineExportInterface()

    result = interface.hooks_handler("unknown_hook", "Unknown", {"x": 1})

    assert result.success is True
    assert result.data == {"x": 1}


def test_handle_export_success(monkeypatch):
    module = _load_interface_module(monkeypatch)
    interface = module.IrisTimelineExportInterface()

    class _CasesEvent:
        case_id = 0
        event_date = 0

    _event_date = datetime.datetime(2024, 1, 15, 10, 0)
    all_events = [
        SimpleNamespace(event_id=1, event_date=_event_date, event_tz="UTC"),
        SimpleNamespace(event_id=2, event_date=_event_date, event_tz="UTC"),
    ]

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return all_events

    _CasesEvent.query = _Query()

    app_models_cases = ModuleType("app.models.cases")
    app_models_cases.CasesEvent = _CasesEvent
    monkeypatch.setitem(sys.modules, "app.models.cases", app_models_cases)

    monkeypatch.setattr(module, "is_included", lambda ev: ev.event_id == 1)

    render_calls = []

    def _fake_render(marked, case_name, title_hex="#AE0C0C", earliest_date=None):
        render_calls.append({"count": len(marked), "case_name": case_name, "title_hex": title_hex})
        return b"png-bytes"

    monkeypatch.setattr(module, "render", _fake_render)
    monkeypatch.setattr(interface, "_save_to_datastore", lambda png, name, cid: 42)
    monkeypatch.setattr(
        interface,
        "get_configuration_dict",
        lambda: SimpleNamespace(
            is_success=lambda: True,
            get_data=lambda: {
                "timeline_title_color": "#112233",
            },
        ),
    )

    case = SimpleNamespace(case_id=7, name="Case Seven")
    result = interface._handle_export([case])

    assert result.success is True
    assert render_calls[0]["count"] == 1
    assert render_calls[0]["case_name"] == "Case Seven"
    assert render_calls[0]["title_hex"] == "#112233"
    assert any("/datastore/file/view/42?cid=7" in log for log in result.logs)


def test_handle_export_emits_no_deprecation_warning(monkeypatch):
    module = _load_interface_module(monkeypatch)
    interface = module.IrisTimelineExportInterface()

    class _CasesEvent:
        case_id = 0
        event_date = 0

    _event_date = datetime.datetime(2024, 1, 15, 10, 0)

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [SimpleNamespace(event_id=1, event_date=_event_date, event_tz="UTC")]

    _CasesEvent.query = _Query()

    app_models_cases = ModuleType("app.models.cases")
    app_models_cases.CasesEvent = _CasesEvent
    monkeypatch.setitem(sys.modules, "app.models.cases", app_models_cases)

    monkeypatch.setattr(module, "is_included", lambda ev: True)
    monkeypatch.setattr(module, "render", lambda *args, **kwargs: b"png-bytes")
    monkeypatch.setattr(interface, "_save_to_datastore", lambda *args, **kwargs: 100)

    case = SimpleNamespace(case_id=4, name="Case Four")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", DeprecationWarning)
        result = interface._handle_export([case])

    assert result.success is True
    assert not any(issubclass(w.category, DeprecationWarning) for w in caught)


def test_handle_export_query_failure_returns_error(monkeypatch):
    module = _load_interface_module(monkeypatch)
    interface = module.IrisTimelineExportInterface()

    app_models_cases = ModuleType("app.models.cases")

    class _FailingCasesEvent:
        class query:
            @staticmethod
            def filter(*args, **kwargs):
                raise RuntimeError("db failed")

    _FailingCasesEvent.case_id = 0
    _FailingCasesEvent.event_date = 0
    app_models_cases.CasesEvent = _FailingCasesEvent
    monkeypatch.setitem(sys.modules, "app.models.cases", app_models_cases)

    case = SimpleNamespace(case_id=9, name="Broken Case")
    result = interface._handle_export([case])

    assert result.success is False
    assert "Failed to query events" in result.message


def test_handle_export_render_failure_returns_error(monkeypatch):
    module = _load_interface_module(monkeypatch)
    interface = module.IrisTimelineExportInterface()

    class _CasesEvent:
        case_id = 0
        event_date = 0

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [SimpleNamespace(event_id=1)]

    _CasesEvent.query = _Query()
    app_models_cases = ModuleType("app.models.cases")
    app_models_cases.CasesEvent = _CasesEvent
    monkeypatch.setitem(sys.modules, "app.models.cases", app_models_cases)

    monkeypatch.setattr(module, "is_included", lambda ev: True)

    def _raise_render(*args, **kwargs):
        raise RuntimeError("render crash")

    monkeypatch.setattr(module, "render", _raise_render)

    case = SimpleNamespace(case_id=3, name="Case Three")
    result = interface._handle_export([case])

    assert result.success is False
    assert "Failed to render timeline PNG" in result.message


def test_handle_export_datastore_failure_returns_error(monkeypatch):
    module = _load_interface_module(monkeypatch)
    interface = module.IrisTimelineExportInterface()

    class _CasesEvent:
        case_id = 0
        event_date = 0

    _event_date = datetime.datetime(2024, 1, 15, 10, 0)

    class _Query:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args, **kwargs):
            return self

        def all(self):
            return [SimpleNamespace(event_id=1, event_date=_event_date, event_tz="UTC")]

    _CasesEvent.query = _Query()
    app_models_cases = ModuleType("app.models.cases")
    app_models_cases.CasesEvent = _CasesEvent
    monkeypatch.setitem(sys.modules, "app.models.cases", app_models_cases)

    monkeypatch.setattr(module, "is_included", lambda ev: True)
    monkeypatch.setattr(module, "render", lambda *args, **kwargs: b"png-bytes")
    monkeypatch.setattr(interface, "_save_to_datastore", lambda *args, **kwargs: None)

    case = SimpleNamespace(case_id=11, name="Case Eleven")
    result = interface._handle_export([case])

    assert result.success is False
    assert "Could not save" in result.message

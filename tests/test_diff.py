"""Unit tests for app.diff — pure snapshot comparison, no DB."""
from app.diff import Change, MethodRecord, compute_changes, method_key
from bank_api_parser.parsers.base_parser import HIDDEN_REASON_GHOST, HIDDEN_REASON_PRIVATE


def _m(service, http, path, fields=(), url="u", name="n", hidden=False, hidden_reason=None):
    return MethodRecord(
        service=service, http_method=http, path=path, name=name,
        url=url, fields=frozenset(fields), hidden=hidden, hidden_reason=hidden_reason,
    )


def test_method_key_uses_http_and_path():
    assert method_key(_m("S", "GET", "/a")) == "GET /a"


def test_method_key_falls_back_to_service_and_name_without_path():
    assert method_key(_m("S", "GET", "", name="Op")) == "S / GET Op"


def test_no_previous_snapshot_yields_no_changes():
    assert compute_changes(None, {"S": "url"}, [_m("S", "GET", "/a")]) == []


def test_identical_snapshots_yield_no_changes():
    methods = [_m("S", "GET", "/a", ["x"])]
    prev = ({"S": "url"}, methods)
    assert compute_changes(prev, {"S": "url"}, methods) == []


def test_service_added_and_removed():
    prev = ({"Old": "o"}, [])
    changes = compute_changes(prev, {"New": "n"}, [])
    assert Change("service", "added", "New", "New", "n") in changes
    assert Change("service", "removed", "Old", "Old", "o") in changes
    assert len(changes) == 2


def test_method_added_and_removed():
    prev = ({"S": ""}, [_m("S", "GET", "/old", url="uo")])
    changes = compute_changes(prev, {"S": ""}, [_m("S", "POST", "/new", url="un")])
    assert Change("method", "added", "POST /new", "S / POST /new", "un") in changes
    assert Change("method", "removed", "GET /old", "S / GET /old", "uo") in changes
    assert len(changes) == 2


def test_field_modification_lists_added_and_removed_sorted():
    prev = ({"S": ""}, [_m("S", "GET", "/a", ["keep", "gone", "b_gone"])])
    new = [_m("S", "GET", "/a", ["keep", "z_new", "a_new"])]
    (change,) = compute_changes(prev, {"S": ""}, new)
    assert change.change_type == "field"
    assert change.action == "modified"
    assert change.old_value == "-b_gone, -gone"
    assert change.new_value == "+a_new, +z_new"


def test_method_moved_between_services_is_not_a_change():
    prev = ({"A": "", "B": ""}, [_m("A", "GET", "/x")])
    assert compute_changes(prev, {"A": "", "B": ""}, [_m("B", "GET", "/x")]) == []


def test_duplicate_keys_in_snapshot_are_merged_not_double_reported():
    prev = ({"S": ""}, [])
    new = [_m("S", "GET", "/a"), _m("S", "GET", "/a")]
    changes = compute_changes(prev, {"S": ""}, new)
    assert [c.entity_name for c in changes] == ["GET /a"]


# ── Hidden services/methods (skрытые сервисы) ──────────────────────────────────

def test_method_key_ignores_hidden_flag():
    visible = _m("S", "GET", "/a")
    hidden = _m("S", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)
    assert method_key(visible) == method_key(hidden)


def test_new_hidden_method_is_a_hidden_add():
    prev = ({"S": ""}, [])
    new = [_m("S", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)]
    (change,) = compute_changes(prev, {"S": ""}, new)
    assert change.change_type == "method" and change.action == "added"
    assert change.hidden is True


def test_removed_hidden_method_is_a_hidden_removal():
    prev = ({"S": ""}, [_m("S", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_GHOST)])
    (change,) = compute_changes(prev, {"S": ""}, [])
    assert change.action == "removed" and change.hidden is True


def test_removed_visible_method_stays_a_visible_removal():
    prev = ({"S": ""}, [_m("S", "GET", "/a")])
    (change,) = compute_changes(prev, {"S": ""}, [])
    assert change.action == "removed" and change.hidden is False


def test_method_becoming_hidden_is_a_visible_removed_change():
    """The user really lost it from the dashboard — that must be a visible change."""
    prev = ({"S": ""}, [_m("S", "GET", "/a")])
    new = [_m("S", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)]
    changes = compute_changes(prev, {"S": ""}, new)
    assert [(c.change_type, c.action, c.hidden) for c in changes] == [("method", "removed", False)]


def test_method_becoming_visible_is_a_visible_added_change():
    prev = ({"S": ""}, [_m("S", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)])
    new = [_m("S", "GET", "/a")]
    changes = compute_changes(prev, {"S": ""}, new)
    assert [(c.change_type, c.action, c.hidden) for c in changes] == [("method", "added", False)]


def test_field_change_on_a_hidden_method_stays_hidden():
    prev = ({"S": ""}, [_m("S", "GET", "/a", ["x"], hidden=True, hidden_reason=HIDDEN_REASON_GHOST)])
    new = [_m("S", "GET", "/a", ["x", "y"], hidden=True, hidden_reason=HIDDEN_REASON_GHOST)]
    (change,) = compute_changes(prev, {"S": ""}, new)
    assert change.change_type == "field" and change.hidden is True


def test_field_change_on_a_visible_method_stays_visible():
    prev = ({"S": ""}, [_m("S", "GET", "/a", ["x"])])
    new = [_m("S", "GET", "/a", ["x", "y"])]
    (change,) = compute_changes(prev, {"S": ""}, new)
    assert change.hidden is False


def test_fully_hidden_new_service_is_a_hidden_service_add():
    prev = ({}, [])
    new_methods = [_m("Priv", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)]
    changes = compute_changes(prev, {"Priv": "u"}, new_methods)
    service_change = next(c for c in changes if c.change_type == "service")
    assert service_change.action == "added" and service_change.hidden is True


def test_partially_hidden_service_add_is_visible():
    prev = ({}, [])
    new_methods = [
        _m("Mix", "GET", "/a"),
        _m("Mix", "GET", "/b", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE),
    ]
    changes = compute_changes(prev, {"Mix": "u"}, new_methods)
    service_change = next(c for c in changes if c.change_type == "service")
    assert service_change.hidden is False


def test_empty_service_is_never_hidden():
    prev = ({}, [])
    changes = compute_changes(prev, {"Empty": "u"}, [])
    service_change = next(c for c in changes if c.change_type == "service")
    assert service_change.hidden is False


def test_service_removed_while_fully_hidden_is_a_hidden_removal():
    prev = ({"Priv": "u"}, [_m("Priv", "GET", "/a", hidden=True, hidden_reason=HIDDEN_REASON_PRIVATE)])
    changes = compute_changes(prev, {}, [])
    service_change = next(c for c in changes if c.change_type == "service")
    assert service_change.action == "removed" and service_change.hidden is True

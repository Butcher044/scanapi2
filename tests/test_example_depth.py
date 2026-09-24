"""
Defect 3: generated examples must not be truncated.

Old bug: `_schema_to_example` used `if depth >= 3: break` inside the property
loop, which aborted the loop entirely and dropped every remaining sibling
field, not just the ones that were actually too deep. Combined with a
`depth > 4` hard stop, this rendered many Tochka bodies as empty shells
(e.g. {"Data": {"Account": [{}]}}).

Fix: only the too-deep child is skipped (siblings keep iterating), the depth
limit is raised to 12, and a $ref cycle guard stops a self-referencing schema
from recursing forever.
"""
from bank_api_parser.parsers.base_parser import BaseParser


class _TestParser(BaseParser):
    def __init__(self):
        self.bank_name = "test"
        import logging
        self.logger = logging.getLogger("test")

    def parse(self):
        return None


def _p():
    return _TestParser()


def _nested_object(levels: int, leaf_properties: dict) -> dict:
    """Builds {"a": {"a": {... leaf_properties ...}}} `levels` deep."""
    schema = {"type": "object", "properties": leaf_properties}
    for _ in range(levels):
        schema = {"type": "object", "properties": {"a": schema}}
    return schema


def test_sibling_fields_survive_past_the_old_break_point():
    """3 levels of nesting used to hit `depth >= 3: break` and empty the object entirely."""
    schema = _nested_object(3, {
        "x": {"type": "string"},
        "y": {"type": "string"},
        "z": {"type": "string"},
    })
    result = _p()._schema_to_example(schema, {})
    leaf = result["a"]["a"]["a"]
    assert set(leaf) == {"x", "y", "z"}


def test_tochka_style_array_of_objects_is_not_an_empty_shell():
    """Mirrors GET /accounts -> {"Data": {"Account": [{}]}} that Tochka evidenced."""
    schema = {
        "type": "object",
        "properties": {
            "Data": {
                "type": "object",
                "properties": {
                    "Account": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "AccountId": {"type": "string"},
                                "Currency": {"type": "string"},
                                "Nickname": {"type": "string"},
                            },
                        },
                    }
                },
            }
        },
    }
    result = _p()._schema_to_example(schema, {})
    account = result["Data"]["Account"][0]
    assert account != {}
    assert set(account) == {"AccountId", "Currency", "Nickname"}


def test_depth_limit_is_raised_to_twelve():
    """A schema nested 10 levels deep (beyond the old depth>4 cutoff) must still render."""
    schema = _nested_object(10, {"leaf": {"type": "string"}})
    result = _p()._schema_to_example(schema, {})
    node = result
    for _ in range(10):
        node = node["a"]
    assert node == {"leaf": "string"}


def test_recursive_ref_does_not_recurse_forever():
    """A schema that references itself must terminate via the $ref cycle guard,
    not merely because the depth limit eventually kicks in."""
    spec = {
        "components": {
            "schemas": {
                "Node": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "example": "root"},
                        "children": {
                            "type": "array",
                            "items": {"$ref": "#/components/schemas/Node"},
                        },
                    },
                }
            }
        }
    }
    schema = {"$ref": "#/components/schemas/Node"}
    result = _p()._schema_to_example(schema, spec)
    assert result["name"] == "root"
    # the cycle guard must stop the *second* time "Node" is encountered on the
    # same branch, well before the depth limit — the nested item collapses to
    # nothing, so the array of children is empty.
    assert result["children"] == []

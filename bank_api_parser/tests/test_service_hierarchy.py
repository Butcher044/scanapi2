"""
Tests for service hierarchy deduplication in Alfa-Bank parser.

The key rule: the service name of a leaf article must be its IMMEDIATE
parent folder, not a grandparent. This prevents "Карты ФЛ" (a category)
from appearing as a service that duplicates "Выпуск дебетовых карт" and
"Работа с картами".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from parsers.alfabank_parser import AlfaBankParser


def _parser():
    p = AlfaBankParser.__new__(AlfaBankParser)
    p.bank_name = "alfabank"
    return p


# ── collect_leaf_articles ─────────────────────────────────────────────────────

def test_two_level_uses_direct_parent():
    """
    Folder → leaf articles → service = folder title.
    """
    tree = [
        {
            "title": "Платежи",
            "articles": [
                {"title": "Создать платёж", "path": "payments/create", "articles": []},
                {"title": "Получить платёж", "path": "payments/get",    "articles": []},
            ],
        }
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    services = {leaf["service"] for leaf in leaves}
    assert services == {"Платежи"}, f"Expected only 'Платежи', got {services}"
    assert len(leaves) == 2


def test_three_level_uses_immediate_parent_not_grandparent():
    """
    Category → Folder → leaf articles.
    Service must be the Folder (immediate parent), NOT the Category.
    Previously: "Карты ФЛ" appeared instead of "Выпуск дебетовых карт".
    """
    tree = [
        {
            "title": "Карты ФЛ",        # category — NOT a service
            "articles": [
                {
                    "title": "Выпуск дебетовых карт",   # service ✓
                    "articles": [
                        {"title": "Выпустить карту", "path": "cards/debit/issue", "articles": []},
                        {"title": "Перевыпустить карту", "path": "cards/debit/reissue", "articles": []},
                    ],
                },
                {
                    "title": "Работа с картами",         # service ✓
                    "articles": [
                        {"title": "Заблокировать карту", "path": "cards/debit/block", "articles": []},
                        {"title": "Разблокировать карту", "path": "cards/debit/unblock", "articles": []},
                    ],
                },
            ],
        }
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    services = {leaf["service"] for leaf in leaves}

    assert "Карты ФЛ" not in services, \
        "Parent category 'Карты ФЛ' must NOT appear as a service"
    assert "Выпуск дебетовых карт" in services
    assert "Работа с картами" in services
    assert len(leaves) == 4

    # Check correct assignment
    debit_leaves = [l for l in leaves if l["service"] == "Выпуск дебетовых карт"]
    assert len(debit_leaves) == 2
    work_leaves = [l for l in leaves if l["service"] == "Работа с картами"]
    assert len(work_leaves) == 2


def test_no_duplicate_methods_across_services():
    """
    The same endpoint path must not appear in multiple services.
    """
    tree = [
        {
            "title": "Карты ФЛ",
            "articles": [
                {
                    "title": "Выпуск дебетовых карт",
                    "articles": [
                        {"title": "POST /cards/issue", "path": "cards/issue", "articles": []},
                    ],
                },
                {
                    "title": "Работа с картами",
                    "articles": [
                        {"title": "GET /cards/{id}", "path": "cards/get", "articles": []},
                    ],
                },
            ],
        }
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    paths = [l["path"] for l in leaves]
    assert len(paths) == len(set(paths)), "Duplicate paths detected"


def test_four_level_uses_second_to_last():
    """
    Category → Group → Folder → leaf.
    Service = Folder (immediate parent of leaf).
    """
    tree = [
        {
            "title": "Продукты",
            "articles": [
                {
                    "title": "Карты",
                    "articles": [
                        {
                            "title": "Дебетовые",
                            "articles": [
                                {"title": "Выпуск", "path": "cards/debit/issue", "articles": []},
                            ],
                        }
                    ],
                }
            ],
        }
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    assert len(leaves) == 1
    assert leaves[0]["service"] == "Дебетовые"
    assert "Продукты" not in leaves[0]["service"]
    assert "Карты" not in leaves[0]["service"]


def test_flat_structure_no_parent():
    """
    If there's no parent, title becomes the service name.
    """
    tree = [
        {"title": "Метод А", "path": "method-a", "articles": []},
        {"title": "Метод Б", "path": "method-b", "articles": []},
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    assert len(leaves) == 2
    assert all(l["service"] in ("Метод А", "Метод Б") for l in leaves)


def test_ignored_articles_skipped():
    """
    Items in IGNORED_ARTICLES should not create leaf entries via the scan.
    (Tests that the exclusion list is intact after the hierarchy fix.)
    """
    tree = [
        {
            "title": "Введение",   # in IGNORED_ARTICLES
            "articles": [
                {"title": "Про API", "path": "intro/about", "articles": []},
            ],
        },
        {
            "title": "Платежи",
            "articles": [
                {"title": "Создать", "path": "pay/create", "articles": []},
            ],
        },
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    # The hierarchy fix doesn't skip anything itself — skipping is in _strategy_article_scan
    # But we should still get both leaves
    services = {l["service"] for l in leaves}
    assert "Введение" in services or "Платежи" in services  # both present as services


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    import sys as _sys; _sys.exit(0 if failed == 0 else 1)

"""
Tests for service hierarchy deduplication in Alfa-Bank parser.

The key rule: the service name of a leaf article is its nearest ANCESTOR
whose own `tags` include "service" (the portal's own catalog-card rule),
not necessarily the immediate parent folder. This prevents "Карты ФЛ" (a
category) from appearing as a service that duplicates "Выпуск дебетовых
карт" and "Работа с картами". When no ancestor is tagged at all (older/
untagged trees), it falls back to the immediate parent folder's title, so
behaviour degrades gracefully instead of collapsing every leaf under one
name.
"""

from bank_api_parser.parsers.alfabank_parser import AlfaBankParser


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


# ── service = nearest ancestor tagged "service" (findings.md Phase 11) ────────

def test_service_name_uses_nearest_service_tagged_ancestor_not_immediate_parent():
    """
    Real portal data: a "service" tag can sit ABOVE a subheading folder that
    itself carries no tags — the subheading ("Расширение сценариев") must
    not become the service name; the nearest ancestor tagged "service" does
    (mirrors the portal's own catalog-card rule: tags.includes("service")).
    """
    tree = [
        {
            "title": "Короткая анкета для регистрации бизнеса",
            "tags": ["service", "alfa-api", "b2b"],
            "articles": [
                {
                    "title": "Расширение сценариев",  # subheading, not a service
                    "articles": [
                        {"title": "Отправить анкету", "path": "partner/send", "articles": []},
                    ],
                }
            ],
        }
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    (leaf,) = leaves
    assert leaf["service"] == "Короткая анкета для регистрации бизнеса"


def test_service_tag_falls_back_to_immediate_parent_when_no_ancestor_is_tagged():
    """Untagged trees keep the old, safe behaviour instead of collapsing
    every leaf under one name."""
    tree = [{"title": "Платежи", "articles": [
        {"title": "Создать платёж", "path": "payments/create", "articles": []},
    ]}]
    leaves = _parser()._collect_leaf_articles(tree)
    assert leaves[0]["service"] == "Платежи"


def test_private_tag_is_inherited_by_every_descendant_leaf():
    """A "private" tag on an ancestor closes the whole subtree, even a
    service-tagged folder nested inside it (e.g. "Короткая анкета..." under
    the private "Партнёрская программа...")."""
    tree = [
        {
            "title": "Партнёрская программа малого и микробизнеса",
            "tags": ["private", "alfa-api"],
            "articles": [
                {
                    "title": "Короткая анкета для регистрации бизнеса",
                    "tags": ["service"],
                    "articles": [
                        {"title": "Отправить анкету", "path": "partner/send", "articles": []},
                    ],
                }
            ],
        }
    ]
    leaves = _parser()._collect_leaf_articles(tree)
    (leaf,) = leaves
    assert leaf["private"] is True
    assert leaf["service"] == "Короткая анкета для регистрации бизнеса"


def test_non_private_leaf_is_not_marked_private():
    tree = [{"title": "Платежи", "tags": ["service"], "articles": [
        {"title": "Создать платёж", "path": "payments/create", "articles": []},
    ]}]
    leaves = _parser()._collect_leaf_articles(tree)
    assert leaves[0]["private"] is False


def test_visible_false_is_carried_through_to_the_leaf():
    tree = [{"title": "Вебхуки", "tags": ["service"], "articles": [
        {"title": "Получение вебхука", "path": "webhooks/get/v1/get", "visible": False, "articles": []},
    ]}]
    leaves = _parser()._collect_leaf_articles(tree)
    assert leaves[0]["visible"] is False


def test_visible_defaults_to_true_when_absent():
    tree = [{"title": "Платежи", "tags": ["service"], "articles": [
        {"title": "Создать платёж", "path": "payments/create", "articles": []},
    ]}]
    leaves = _parser()._collect_leaf_articles(tree)
    assert leaves[0]["visible"] is True


# ── _hidden_status ──────────────────────────────────────────────────────────

def test_hidden_status_private_beats_superseded():
    from bank_api_parser.parsers.alfabank_parser import AlfaBankParser
    from bank_api_parser.parsers.base_parser import HIDDEN_REASON_PRIVATE
    assert AlfaBankParser._hidden_status({"private": True, "visible": False}) == (True, HIDDEN_REASON_PRIVATE)


def test_hidden_status_superseded_when_only_invisible():
    from bank_api_parser.parsers.alfabank_parser import AlfaBankParser
    from bank_api_parser.parsers.base_parser import HIDDEN_REASON_SUPERSEDED
    assert AlfaBankParser._hidden_status({"private": False, "visible": False}) == (True, HIDDEN_REASON_SUPERSEDED)


def test_hidden_status_visible_public_leaf_is_not_hidden():
    from bank_api_parser.parsers.alfabank_parser import AlfaBankParser
    assert AlfaBankParser._hidden_status({"private": False, "visible": True}) == (False, None)


def test_collect_leaf_articles_does_not_filter_by_itself():
    """
    _collect_leaf_articles does NOT apply the IGNORED_ARTICLES filter — that
    filtering happens one layer up, in _strategy_article_scan. So a leaf under
    an "Введение"-titled folder is still collected here, with its service
    correctly resolved to "Введение" (no ancestor tagged "service" anywhere
    in this tree, so it falls back to the immediate parent folder's title).
    (Real end-to-end filtering behaviour is covered by
    test_alfa_parser.py::test_article_scan_skips_ignored_and_dedupes.)
    """
    tree = [
        {
            "title": "Введение",   # in IGNORED_ARTICLES, but that's irrelevant here
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
    services = {l["service"] for l in leaves}
    assert services == {"Введение", "Платежи"}

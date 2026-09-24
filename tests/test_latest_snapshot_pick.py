"""Все места, которые выбирают «последний снимок банка», должны выбирать один и тот же.

Ревью БД воспроизвело расхождение на живом PostgreSQL: `created_at` — это время
НАЧАЛА транзакции (NOW()), а `id` — порядок выполнения INSERT. У двух пересекающихся
импортов одного банка они инвертируются, и тогда diff берёт за базу один снимок,
дашборд показывает другой, а чистка удаляет тот, который дашборд считает текущим.

Единственный авторитетный порядок — `id DESC` (SERIAL монотонен). Тест ловит
возврат к `created_at` в любом из четырёх мест.
"""
import asyncio
import inspect

from app import benchmark_repo
from app import repository as repo


class QueryCapture:
    """Фейковая asyncpg.Connection: запоминает SQL и возвращает пустой результат."""

    def __init__(self):
        self.queries: list[str] = []

    async def fetch(self, query, *args):
        self.queries.append(query)
        return []

    async def fetchrow(self, query, *args):
        self.queries.append(query)
        return None


def _capture(coro_factory) -> str:
    conn = QueryCapture()
    asyncio.run(coro_factory(conn))
    assert len(conn.queries) == 1
    return " ".join(conn.queries[0].split())


def test_diff_baseline_picks_the_newest_id():
    sql = _capture(lambda c: repo.get_latest_snapshot(c, "sber"))
    assert "ORDER BY id DESC" in sql
    assert "created_at DESC" not in sql


def test_cleanup_keeps_the_newest_ids():
    sql = _capture(lambda c: repo.get_snapshots_for_cleanup(c, "sber", keep=1))
    assert "ORDER BY id DESC" in sql
    assert "created_at DESC" not in sql


def test_benchmark_picks_the_newest_id_per_bank():
    sql = " ".join(inspect.getsource(benchmark_repo.latest_services).split())
    assert "ORDER BY bank, id DESC" in sql
    assert "created_at DESC" not in sql


def test_dashboard_queries_pick_the_newest_id_per_bank():
    """Дашборд и админка уже выбирают через MAX(id) — фиксируем, чтобы не уехало."""
    source = inspect.getsource(repo)
    assert "ORDER BY created_at DESC" not in source

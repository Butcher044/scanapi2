"""Benchmark API: capability × bank matrix for everyone, cell overrides for the admin."""
from __future__ import annotations

from datetime import datetime
from itertools import groupby
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StrictBool, field_validator

from app import benchmark, benchmark_repo, database
from app.banks import BANK_KEYS, bank_label
from app.benchmark_catalog import KEYS
from app.web_auth import require_admin

MSK = ZoneInfo("Europe/Moscow")

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


class OverrideIn(BaseModel):
    capability: str = Field(max_length=64)
    bank: str = Field(max_length=32)
    present: Optional[StrictBool]   # required; null = back to automatic

    @field_validator("capability")
    @classmethod
    def _known_capability(cls, value: str) -> str:
        if value not in KEYS:
            raise ValueError("неизвестная строка бенчмарка")
        return value

    @field_validator("bank")
    @classmethod
    def _known_bank(cls, value: str) -> str:
        if value not in BANK_KEYS:
            raise ValueError("неизвестный банк")
        return value


def _cell_view(cell: benchmark.Cell) -> dict:
    return {
        "present":  cell.present,
        "auto":     cell.auto,
        "override": cell.override,
        "evidence": [
            {"service": e.service, "matched": e.matched, "total": e.total, "by_name": e.by_name}
            for e in cell.evidence
        ],
    }


def _view(rows: list[Mapping], overrides: Mapping[tuple[str, str], bool]) -> dict:
    result = benchmark.build(benchmark.services_from_rows(rows), overrides, BANK_KEYS)
    snapshot_at: dict[str, datetime] = {r["bank"]: r["created_at"] for r in rows}
    banks = [
        {
            "key":         bank,
            "label":       bank_label(bank),
            "snapshot_at": snapshot_at[bank].astimezone(MSK).strftime("%d.%m.%Y %H:%M")
                           if bank in snapshot_at else None,
        }
        for bank in BANK_KEYS
    ]
    groups = [
        {
            "title": title,
            "rows": [
                {
                    "key":   row.capability.key,
                    "title": row.capability.title,
                    "cells": {bank: _cell_view(row.cells[bank]) for bank in BANK_KEYS},
                }
                for row in group_rows
            ],
        }
        for title, group_rows in groupby(result.rows, key=lambda r: r.capability.group)
    ]
    return {
        "banks":     banks,
        "groups":    groups,
        "unmatched": {bank: list(names) for bank, names in result.unmatched.items()},
    }


async def _load() -> dict:
    async with database.get_pool().acquire() as conn:
        rows = await benchmark_repo.latest_services(conn)
        overrides = await benchmark_repo.get_overrides(conn)
    return _view(rows, overrides)


@router.get("")
async def get_benchmark() -> dict:
    return await _load()


@router.put("/overrides", dependencies=[Depends(require_admin)])
async def put_override(body: OverrideIn) -> dict:
    async with database.get_pool().acquire() as conn:
        await benchmark_repo.set_override(conn, body.capability, body.bank, body.present)
    return await _load()

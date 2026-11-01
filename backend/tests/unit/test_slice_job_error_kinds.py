"""Maschinenlesbare Ursache eines fehlgeschlagenen Slice-Auftrags.

Die Oberfläche soll bei „Sidecar nicht erreichbar“ die Adresse nennen können,
statt den englischen Backend-Text anzuzeigen. Dafür muss die Ursache vom
HTTPException bis in den Auftrag durchgereicht werden.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.services.slice_dispatch import (
    SliceDispatchService,
    SliceJobHttpError,
    http_exception_to_job_error,
)


def test_slice_job_http_error_keeps_its_kind():
    error = http_exception_to_job_error(
        SliceJobHttpError(502, "Slicer sidecar unreachable: All connection attempts failed", "sidecar_unreachable")
    )
    assert error.status_code == 502
    assert error.kind == "sidecar_unreachable"


def test_plain_http_error_has_no_kind():
    from fastapi import HTTPException

    error = http_exception_to_job_error(HTTPException(status_code=400, detail="bad input"))
    assert error.kind is None


@pytest.mark.asyncio
async def test_failed_job_exposes_the_kind():
    async def run(job_id: int):
        raise http_exception_to_job_error(SliceJobHttpError(504, "Slicer ausgelastet", "timeout"))

    service = SliceDispatchService()
    job = await service.enqueue(kind="library_file", source_id=1, source_name="modell.3mf", run=run)
    for _ in range(100):
        if job.status == "failed":
            break
        await asyncio.sleep(0.01)

    assert job.status == "failed"
    assert job.error_status == 504
    assert job.error_kind == "timeout"
    assert job.error_detail == "Slicer ausgelastet"

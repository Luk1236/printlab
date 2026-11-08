"""Schemas for printer fleet management and batch operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class FleetCommandRequest(BaseModel):
    """Request to execute a batch operation across printer fleet."""

    action: Literal[
        "pause",
        "resume",
        "stop",
        "emergency_stop",
        "chamber_light_on",
        "chamber_light_off",
        "maintenance_enter",
        "maintenance_exit",
    ] = Field(..., description="Action to perform across the targeted fleet")
    printer_ids: list[int] | None = Field(
        None, description="Optional explicit printer IDs; if empty/omitted, targets all active printers"
    )
    location: str | None = Field(None, description="Optional filter to only target printers in this group/location")
    reason: str | None = Field(None, description="Optional operator reason for batch stop or emergency stop")


class FleetCommandResultItem(BaseModel):
    """Status result for a single printer within a fleet command."""

    printer_id: int
    name: str
    reason: str


class FleetCommandResponse(BaseModel):
    """Aggregated outcome of a batch fleet operation."""

    action: str
    total_targeted: int
    succeeded: list[int]
    failed: list[FleetCommandResultItem]
    skipped: list[FleetCommandResultItem]


class FleetJobSummary(BaseModel):
    """Summary of an active print job in the fleet."""

    printer_id: int
    printer_name: str
    model: str | None = None
    location: str | None = None
    state: str
    subtask_name: str | None = None
    gcode_file: str | None = None
    progress: int = 0
    remaining_time_minutes: int | None = None
    current_layer: int = 0
    total_layers: int = 0


class FleetOverviewResponse(BaseModel):
    """Real-time aggregated fleet status overview."""

    total_printers: int
    online_printers: int
    printing_count: int
    paused_count: int
    idle_count: int
    maintenance_count: int
    hms_error_count: int
    active_jobs: list[FleetJobSummary]
    locations: dict[str, int]

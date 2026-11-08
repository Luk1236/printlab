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


class FleetMetricsResponse(BaseModel):
    """Real-time WebSocket and fleet telemetry metrics."""

    active_ws_connections: int
    total_ws_broadcasts: int
    total_ws_messages_sent: int
    dropped_ws_connections: int
    last_broadcast_ms: float
    avg_broadcast_ms: float
    max_broadcast_ms: float
    maintenance_printers_count: int


class NestingPartItem(BaseModel):
    """Input specification for a single 3D part in 2D auto-nesting."""

    part_id: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    width_mm: float = Field(..., gt=0.1, le=1000.0)
    depth_mm: float = Field(..., gt=0.1, le=1000.0)
    height_mm: float = Field(10.0, gt=0.1, le=1000.0)
    copies: int = Field(1, ge=1, le=500)
    allow_rotation: bool = Field(True)
    filament_grams_per_copy: float = Field(10.0, ge=0.1, le=10000.0)
    print_minutes_per_copy: float = Field(20.0, ge=0.5, le=20000.0)


class ExclusionZoneItem(BaseModel):
    """Sperr- oder Schadenszone auf dem Druckbett (z.B. PEI-Kratzer)."""

    min_x: float = Field(..., ge=0.0, le=1000.0)
    min_y: float = Field(..., ge=0.0, le=1000.0)
    max_x: float = Field(..., ge=0.0, le=1000.0)
    max_y: float = Field(..., ge=0.0, le=1000.0)
    reason: str = Field("Damaged PEI", max_length=120)


class AutoNestRequest(BaseModel):
    """Request payload for multi-plate 2D auto-nesting."""

    parts: list[NestingPartItem] = Field(..., min_length=1, max_length=100)
    bed_width_mm: float = Field(256.0, ge=50.0, le=600.0)
    bed_depth_mm: float = Field(256.0, ge=50.0, le=600.0)
    bed_height_mm: float = Field(256.0, ge=50.0, le=600.0)
    margin_mm: float = Field(5.0, ge=0.0, le=30.0)
    spacing_mm: float = Field(4.0, ge=0.5, le=30.0)
    exclusion_zones: list[ExclusionZoneItem] | None = None


class BatchSplitRequest(AutoNestRequest):
    """Request payload for auto-nesting + parallel farm batch splitting."""

    material: str = Field("PLA", max_length=32)
    color: str = Field("", max_length=32)
    nozzle_diameter: float = Field(0.4, ge=0.15, le=1.2)
    requires_hardened_nozzle: bool = Field(False)


class PurgeOptimizeRequest(BaseModel):
    """Request payload for multicolor flush volume reduction and purge-to-infill analysis."""

    gcode: str = Field(..., min_length=1, max_length=10_000_000)
    flush_multiplier: float = Field(0.65, ge=0.3, le=1.5)
    enable_purge_to_infill: bool = Field(True)
    infill_purge_ratio: float = Field(0.40, ge=0.0, le=0.7)
    cost_per_kg_eur: float = Field(24.0, ge=1.0, le=500.0)


class OrientationCheckRequest(BaseModel):
    """Request payload for optimal 3D print orientation scoring."""

    width_mm: float = Field(..., gt=0.1, le=1000.0)
    depth_mm: float = Field(..., gt=0.1, le=1000.0)
    height_mm: float = Field(..., gt=0.1, le=1000.0)
    overhang_ratio_by_axis: dict[str, float] | None = None


class GcodeM486Request(BaseModel):
    """Request payload for M486 object exclusion marker analysis and injection."""

    gcode: str = Field(..., min_length=1, max_length=5_000_000)
    object_names: list[str] | None = None


"""API-Router für Multi-Location Farm Mesh & Standort-Clustering (Phase 25)."""

from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.permissions import Permission
from backend.app.services.farm_mesh_relay import (
    get_local_node_info,
    get_mesh_aggregated_overview,
    get_node_auth_token,
    list_peer_nodes,
    record_node_heartbeat,
    register_peer_node,
    remove_peer_node,
    route_job_across_mesh,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mesh", tags=["farm-mesh"])


class RegisterNodeRequest(BaseModel):
    node_id: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=2, max_length=128)
    location: str = Field(..., min_length=2, max_length=128)
    api_url: str = Field(..., min_length=5, max_length=256)
    auth_token: str = Field("", max_length=256)
    printers_count: int = Field(4, ge=1, le=100)

    @field_validator("api_url")
    @classmethod
    def _http_only(cls, value: str) -> str:
        # Die Adresse wird gespeichert und in der Oberfläche angezeigt: nur http(s)
        if not value.strip().lower().startswith(("http://", "https://")):
            raise ValueError("api_url muss mit http:// oder https:// beginnen")
        return value


class NodeHeartbeatRequest(BaseModel):
    node_id: str = Field(...)
    active_printers: int = Field(4, ge=0)
    queue_depth: int = Field(0, ge=0)
    latency_ms: float = Field(15.0, ge=0.0)


class RouteJobRequest(BaseModel):
    job_name: str = Field(..., min_length=1)
    material: str = Field("PLA", max_length=32)
    required_grams: float = Field(50.0, gt=0.0)
    local_farm_busy: bool = Field(True)


@router.get("/nodes", response_model=dict[str, Any])
async def get_nodes(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Liefert alle bekannten Standortknoten des Meshs."""
    return {
        "local_node": get_local_node_info(),
        "peer_nodes": list_peer_nodes(),
    }


@router.post("/nodes/register", response_model=dict[str, Any])
async def register_node(
    req: RegisterNodeRequest,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Registriert einen neuen Druckfarm-Standort im dezentralen Mesh."""
    return register_peer_node(
        node_id=req.node_id,
        name=req.name,
        location=req.location,
        api_url=req.api_url,
        auth_token=req.auth_token,
        printers_count=req.printers_count,
    )


@router.delete("/nodes/{node_id}", response_model=dict[str, Any])
async def unregister_node(
    node_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
) -> dict[str, Any]:
    """Entfernt einen Standort aus dem Verbund."""
    deleted = remove_peer_node(node_id)
    if not deleted:
        raise HTTPException(404, f"Standortknoten '{node_id}' nicht gefunden.")
    return {"success": True, "message": f"Knoten '{node_id}' erfolgreich aus dem Mesh entfernt."}


@router.post("/heartbeat", response_model=dict[str, Any])
async def handle_heartbeat(
    req: NodeHeartbeatRequest,
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    """Empfängt Statusmeldungen und Queuetiefen entfernter Farm-Standorte.

    Der Standort meldet sich mit dem Token, das beim Registrieren hinterlegt wurde (``Authorization: Bearer``).
    Unbekannte Knoten und Knoten ohne Token werden abgelehnt: Sonst könnte jeder beliebige Standorte anlegen
    und die Lastverteilung beeinflussen.
    """
    expected = get_node_auth_token(req.node_id)
    if expected is None:
        raise HTTPException(404, "Standortknoten unbekannt: erst über /mesh/nodes/register anmelden.")
    provided = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(401, "Ungültiges oder fehlendes Knoten-Token.")
    return record_node_heartbeat(
        node_id=req.node_id,
        active_printers=req.active_printers,
        queue_depth=req.queue_depth,
        latency_ms=req.latency_ms,
    )


@router.get("/overview", response_model=dict[str, Any])
async def get_cluster_overview(
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_READ),
) -> dict[str, Any]:
    """Aggregierte Flotten- und Kapazitätsübersicht aller Standorte."""
    return get_mesh_aggregated_overview()


@router.post("/route-job", response_model=dict[str, Any])
async def route_job(
    req: RouteJobRequest,
    _=RequirePermissionIfAuthEnabled(Permission.PRINTERS_CONTROL),
) -> dict[str, Any]:
    """Entscheidet, an welchem Standort der Auftrag gefertigt werden soll."""
    return route_job_across_mesh(
        job_name=req.job_name,
        material=req.material,
        required_grams=req.required_grams,
        local_farm_busy=req.local_farm_busy,
    )

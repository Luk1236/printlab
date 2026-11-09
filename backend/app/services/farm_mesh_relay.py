"""Multi-Location Farm Mesh & P2P-Relay für dezentrale Druckfarmen (Phase 25).

Ermöglicht die standortübergreifende Vernetzung mehrerer Druckwerkstätten
(z.B. München, Stuttgart, Berlin) in einem gemeinsamen Leitstand inklusive
dynamischem Cross-Location Job-Routing bei lokaler Farm-Überlastung.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Lokale Knoten-Identität
LOCAL_NODE: dict[str, Any] = {
    "node_id": "NODE-LOCAL-HQ",
    "name": "PrintLab Hauptwerkstatt",
    "location": "München HQ",
    "api_url": "http://localhost:8000",
    "role": "LEADER",
    "active": True,
}

# Verbundene Peer-Knoten im Mesh
_mesh_nodes: dict[str, dict[str, Any]] = {}


def get_local_node_info() -> dict[str, Any]:
    """Liefert die Identität und Netzwerkkonfiguration des lokalen Knotens."""
    return dict(LOCAL_NODE)


def _public_view(record: dict[str, Any]) -> dict[str, Any]:
    """Knotendaten ohne das Token: Es darf nicht über die Leseschnittstellen wieder herauskommen."""
    view = {k: v for k, v in record.items() if k != "auth_token"}
    view["has_auth_token"] = bool(record.get("auth_token"))
    return view


def register_peer_node(
    node_id: str,
    name: str,
    location: str,
    api_url: str,
    auth_token: str = "",
    printers_count: int = 4,
) -> dict[str, Any]:
    """Registriert einen neuen Standortknoten im Multi-Location Mesh."""
    clean_id = node_id.strip().upper()
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "node_id": clean_id,
        "name": name.strip(),
        "location": location.strip(),
        "api_url": api_url.strip(),
        "auth_token": auth_token.strip(),
        "printers_count": max(1, int(printers_count)),
        "status": "ONLINE",
        "last_heartbeat": now_iso,
        "latency_ms": 15.0,
        "queue_depth": 0,
        "registered_at": now_iso,
    }
    _mesh_nodes[clean_id] = record
    logger.info("[FarmMesh] Neuer Standortknoten registriert: %s (%s, %s)", clean_id, name, location)
    return {
        "success": True,
        "node": _public_view(record),
        "message": f"Standortknoten '{name}' ({clean_id}) erfolgreich in das Farm-Mesh aufgenommen.",
    }


def list_peer_nodes() -> list[dict[str, Any]]:
    """Liefert alle aktuell verbundenen Standortknoten."""
    return [_public_view(node) for node in _mesh_nodes.values()]


def remove_peer_node(node_id: str) -> bool:
    """Entfernt einen Standortknoten aus dem Mesh-Verbund."""
    clean_id = node_id.strip().upper()
    if clean_id in _mesh_nodes:
        del _mesh_nodes[clean_id]
        logger.info("[FarmMesh] Standortknoten '%s' aus Mesh entfernt.", clean_id)
        return True
    return False


def get_node_auth_token(node_id: str) -> str | None:
    """Das beim Registrieren hinterlegte Token eines Knotens; ``None``, wenn der Knoten unbekannt ist."""
    node = _mesh_nodes.get(node_id.strip().upper())
    return None if node is None else str(node.get("auth_token") or "")


def record_node_heartbeat(
    node_id: str,
    active_printers: int = 4,
    queue_depth: int = 0,
    latency_ms: float = 12.0,
) -> dict[str, Any]:
    """Aktualisiert den Lebenspuls und die aktuelle Auslastung eines Knotens."""
    clean_id = node_id.strip().upper()
    if clean_id not in _mesh_nodes:
        # Auto-Registrierung bei erstem Herzschlag
        register_peer_node(node_id=clean_id, name=f"Node {clean_id}", location="Remote", api_url="")

    node = _mesh_nodes[clean_id]
    node["last_heartbeat"] = datetime.now(timezone.utc).isoformat()
    node["status"] = "ONLINE"
    node["printers_count"] = max(0, int(active_printers))
    node["queue_depth"] = max(0, int(queue_depth))
    node["latency_ms"] = round(float(latency_ms), 1)

    return {
        "success": True,
        "node_id": clean_id,
        "status": "ONLINE",
        "acknowledged_at": node["last_heartbeat"],
    }


def get_mesh_aggregated_overview() -> dict[str, Any]:
    """Berechnet die aggregierten Telemetriedaten des gesamten Standort-Clusters."""
    all_nodes = [LOCAL_NODE] + list(_mesh_nodes.values())
    total_printers = sum(n.get("printers_count", 2) for n in all_nodes)
    total_queue_jobs = sum(n.get("queue_depth", 0) for n in all_nodes)
    online_count = sum(1 for n in all_nodes if n.get("status", "ONLINE") == "ONLINE")

    return {
        "mesh_health": "HEALTHY" if online_count == len(all_nodes) else "DEGRADED",
        "total_locations_count": len(all_nodes),
        "online_nodes_count": online_count,
        "total_cluster_printers": total_printers,
        "total_cluster_queue_jobs": total_queue_jobs,
        "local_node": LOCAL_NODE,
        "remote_nodes": list(_mesh_nodes.values()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def route_job_across_mesh(
    job_name: str,
    material: str = "PLA",
    required_grams: float = 50.0,
    local_farm_busy: bool = True,
) -> dict[str, Any]:
    """Wählt den optimalen Standort im Mesh zur Fertigung des Druckauftrags aus."""
    if not local_farm_busy or not _mesh_nodes:
        return {
            "routed_target": "LOCAL",
            "target_node_id": LOCAL_NODE["node_id"],
            "target_node_name": LOCAL_NODE["name"],
            "reason": "Lokale Druckerfarm verfügt über ausreichende Kapazität.",
            "job_name": job_name,
            "material": material,
        }

    # Besten Remote-Knoten nach geringster Warteschlangentiefe auswählen
    best_peer = min(_mesh_nodes.values(), key=lambda n: n.get("queue_depth", 999))
    logger.info(
        "[FarmMesh] Auftrag '%s' (%s, %.1fg) an Remote-Standort '%s' geroutet (Queue=%d).",
        job_name,
        material,
        required_grams,
        best_peer["name"],
        best_peer["queue_depth"],
    )

    return {
        "routed_target": "REMOTE",
        "target_node_id": best_peer["node_id"],
        "target_node_name": best_peer["name"],
        "target_location": best_peer["location"],
        "target_api_url": best_peer["api_url"],
        "reason": f"Lokale Farm ausgelastet. Automatische Weiterleitung an Partner-Standort mit geringster Warteschlange ({best_peer['queue_depth']} Jobs).",
        "job_name": job_name,
        "material": material,
        "required_grams": required_grams,
    }

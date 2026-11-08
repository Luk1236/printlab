"""Unit-Tests für Multi-Location Farm Mesh & Cluster-Routing (Phase 25)."""

import pytest
from httpx import AsyncClient

from backend.app.services.farm_mesh_relay import (
    get_local_node_info,
    get_mesh_aggregated_overview,
    list_peer_nodes,
    record_node_heartbeat,
    register_peer_node,
    remove_peer_node,
    route_job_across_mesh,
)


def test_local_node_info() -> None:
    info = get_local_node_info()
    assert info["node_id"] == "NODE-LOCAL-HQ"
    assert info["role"] == "LEADER"
    assert "Hauptwerkstatt" in info["name"]


def test_register_and_list_peer_nodes() -> None:
    res = register_peer_node(
        node_id="NODE-STUTTGART",
        name="Werkstatt Stuttgart",
        location="Stuttgart Vaihingen",
        api_url="http://192.168.1.100:8000",
        printers_count=6,
    )
    assert res["success"] is True
    assert res["node"]["node_id"] == "NODE-STUTTGART"

    peers = list_peer_nodes()
    assert any(p["node_id"] == "NODE-STUTTGART" for p in peers)

    # Löschen testen
    assert remove_peer_node("NODE-STUTTGART") is True
    assert remove_peer_node("NODE-NONEXISTENT") is False


def test_node_heartbeat_and_latency() -> None:
    register_peer_node("NODE-BERLIN", "Berlin Farm", "Berlin Mitte", "http://berlin:8000", printers_count=8)
    hb = record_node_heartbeat("NODE-BERLIN", active_printers=8, queue_depth=3, latency_ms=18.5)
    assert hb["success"] is True

    ov = get_mesh_aggregated_overview()
    assert ov["mesh_health"] == "HEALTHY"
    assert ov["total_locations_count"] >= 2


def test_cross_location_job_routing() -> None:
    # 1. Wenn lokale Farm frei ist -> Lokal fertigen
    res_local = route_job_across_mesh("Gehäuse Deckel", material="PLA", local_farm_busy=False)
    assert res_local["routed_target"] == "LOCAL"

    # 2. Wenn lokale Farm ausgelastet ist -> Weiterleitung an Peer
    register_peer_node("NODE-HAMBURG", "Hamburg Farm", "Hamburg", "http://hamburg:8000", printers_count=4)
    record_node_heartbeat("NODE-HAMBURG", active_printers=4, queue_depth=1)

    res_remote = route_job_across_mesh("Serienteil 50x", material="PA-CF", local_farm_busy=True)
    assert res_remote["routed_target"] == "REMOTE"
    assert "target_node_name" in res_remote


@pytest.mark.asyncio
async def test_farm_mesh_api_endpoints(async_client: AsyncClient) -> None:
    # 1. Nodes GET
    n_resp = await async_client.get("/api/v1/mesh/nodes")
    assert n_resp.status_code == 200
    assert "local_node" in n_resp.json()

    # 2. Register POST
    r_resp = await async_client.post(
        "/api/v1/mesh/nodes/register",
        json={
            "node_id": "NODE-KÖLN",
            "name": "Köln Labor",
            "location": "Köln Ehrenfeld",
            "api_url": "http://koeln:8000",
            "printers_count": 3,
        },
    )
    assert r_resp.status_code == 200
    assert r_resp.json()["success"] is True

    # 3. Overview GET
    ov_resp = await async_client.get("/api/v1/mesh/overview")
    assert ov_resp.status_code == 200
    assert ov_resp.json()["total_locations_count"] >= 2

    # 4. Route Job POST
    rt_resp = await async_client.post(
        "/api/v1/mesh/route-job",
        json={"job_name": "Adapter", "material": "PETG", "required_grams": 40.0, "local_farm_busy": False},
    )
    assert rt_resp.status_code == 200
    assert rt_resp.json()["routed_target"] == "LOCAL"

"""T6-01 der Code-Analyse: ein auf Drucker beschränkter API-Schlüssel gilt auf jeder Route nur für diese."""

from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


@pytest.fixture
async def scoped(async_client: AsyncClient, printer_factory, db_session):
    """Zwei Drucker, Anmeldung an, ein Schlüssel nur für Drucker A und ein unbeschränkter."""
    from backend.app.core.auth import generate_api_key
    from backend.app.models.api_key import APIKey

    printer_a = await printer_factory(name="Scoped A", serial_number="SCOPEA000000001")
    printer_b = await printer_factory(name="Scoped B", serial_number="SCOPEB000000001")
    setup = await async_client.post(
        "/api/v1/auth/setup",
        json={"auth_enabled": True, "admin_username": "scopeadmin", "admin_password": "AdminPass1!"},
    )
    assert setup.status_code == 200, setup.text

    keys = {}
    for name, printer_ids in (("scoped", [printer_a.id]), ("global", None)):
        full_key, key_hash, key_prefix = generate_api_key()
        db_session.add(
            APIKey(
                name=name,
                key_hash=key_hash,
                key_prefix=key_prefix,
                can_control_printer=True,
                can_queue=True,
                printer_ids=printer_ids,
                enabled=True,
            )
        )
        keys[name] = full_key
    await db_session.commit()

    client = MagicMock()
    for method in ("pause_print", "stop_print", "send_gcode", "set_chamber_light"):
        getattr(client, method).return_value = True
    with patch("backend.app.api.routes.printers.printer_manager") as manager:
        manager.get_client.return_value = client
        manager.get_status.return_value = None
        yield {"a": printer_a.id, "b": printer_b.id, "keys": keys, "client": client}


CONTROL_ROUTES = [
    ("POST", "/api/v1/printers/{id}/print/pause"),
    ("POST", "/api/v1/printers/{id}/print/stop"),
    ("POST", "/api/v1/printers/{id}/bed-jog?distance=5"),
    ("POST", "/api/v1/printers/{id}/chamber-light?on=true"),
    ("POST", "/api/v1/printers/{id}/camera/stop"),
    ("GET", "/api/v1/printers/{id}/camera/status"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "url"), CONTROL_ROUTES)
@pytest.mark.parametrize("transport", ["header", "bearer"])
async def test_scoped_key_is_refused_on_another_printer(async_client: AsyncClient, scoped, method, url, transport):
    key = scoped["keys"]["scoped"]
    headers = {"X-API-Key": key} if transport == "header" else {"Authorization": f"Bearer {key}"}

    resp = await async_client.request(method, url.format(id=scoped["b"]), headers=headers)

    assert resp.status_code == 403, resp.text
    assert f"printer {scoped['b']}" in resp.json()["detail"]
    assert scoped["client"].method_calls == [], "nothing reached the printer"


@pytest.mark.asyncio
async def test_scoped_key_still_controls_its_own_printer(async_client: AsyncClient, scoped):
    resp = await async_client.post(
        f"/api/v1/printers/{scoped['a']}/print/pause", headers={"X-API-Key": scoped["keys"]["scoped"]}
    )
    assert resp.status_code == 200, resp.text
    scoped["client"].pause_print.assert_called_once()


@pytest.mark.asyncio
async def test_global_key_and_routes_without_a_printer_are_untouched(async_client: AsyncClient, scoped):
    headers_global = {"X-API-Key": scoped["keys"]["global"]}
    resp = await async_client.post(f"/api/v1/printers/{scoped['b']}/print/pause", headers=headers_global)
    assert resp.status_code == 200, resp.text

    # A route that names no printer is not the guard's business, whatever the key.
    resp = await async_client.get("/api/v1/auth/status", headers={"X-API-Key": scoped["keys"]["scoped"]})
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_an_unknown_key_is_left_to_the_route(async_client: AsyncClient, scoped):
    """The guard is not authentication: a key it cannot find is rejected by the route with 401, not by the guard."""
    resp = await async_client.post(
        f"/api/v1/printers/{scoped['b']}/print/pause", headers={"X-API-Key": "bb_unknown_key_value_000000"}
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body_key", ["printer_id", "printer_ids"], ids=["single id in the body", "id list in the body"]
)
async def test_scoped_key_is_refused_when_the_body_names_another_printer(async_client: AsyncClient, scoped, body_key):
    body = {"printer_id": scoped["b"]} if body_key == "printer_id" else {"printer_ids": [scoped["a"], scoped["b"]]}
    body["action"] = "chamber_light_on"

    resp = await async_client.post("/api/v1/fleet/command", json=body, headers={"X-API-Key": scoped["keys"]["scoped"]})

    assert resp.status_code == 403, resp.text
    assert f"printer {scoped['b']}" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scoped_key_is_refused_when_the_query_names_another_printer(async_client: AsyncClient, scoped):
    resp = await async_client.get(
        f"/api/v1/print-queue/?printer_id={scoped['b']}", headers={"X-API-Key": scoped["keys"]["scoped"]}
    )
    assert resp.status_code == 403, resp.text


def test_every_route_carries_the_guard():
    """New routers get it for free; this fails if someone builds the app without the app-wide dependency."""
    from fastapi.routing import APIRoute

    from backend.app.core.printer_scope import enforce_api_key_printer_scope
    from backend.app.main import app

    missing = [
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and "{printer_id}" in route.path
        and all(dep.call is not enforce_api_key_printer_scope for dep in route.dependant.dependencies)
    ]
    assert missing == []

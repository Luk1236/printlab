"""Öffentlicher Angebots-Link: Teilen, Zurückziehen und die Seite für den Kunden.

Die Seite läuft ohne Anmeldung; der Link selbst ist die Berechtigung. Sie zeigt
nur, was der Kunde sehen darf (siehe ``services/quote_share.public_view``) und
schreibt ausschließlich die Zusage/Ablehnung dieses Vorgangs. Das Formular
leitet nach dem Absenden auf dieselbe Adresse um, damit ein Neuladen die
Antwort nicht erneut abschickt.
"""

from __future__ import annotations

from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.config import settings as app_settings
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.services import company_profile, quote_history, quote_share

router = APIRouter(prefix="/quote", tags=["quote-share"])


class ShareRequest(BaseModel):
    days: int = Field(quote_share.DEFAULT_DAYS, ge=1, le=quote_share.MAX_DAYS)


def _public_url(base: str, token: str) -> str:
    return f"{base.rstrip('/')}{app_settings.api_prefix}/quote/shared/{token}"


async def _base_url(db: AsyncSession) -> str:
    from backend.app.api.routes.settings import get_external_base_url

    try:
        return await get_external_base_url(db)
    except Exception:  # noqa: BLE001 — ohne konfigurierte Adresse reicht ein relativer Pfad
        return ""


@router.post("/history/{quote_id}/share")
async def create_share_link(
    quote_id: str,
    payload: ShareRequest,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
    db: AsyncSession = Depends(get_db),
):
    """Link erzeugen (macht einen älteren offenen Link desselben Angebots ungültig)."""
    quote = quote_history.get(quote_id)
    try:
        entry = quote_share.create(quote_id, payload.days, quote)
    except quote_share.ShareError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "token": entry["token"],
        "url": _public_url(await _base_url(db), entry["token"]),
        "expires_at": entry["expires_at"],
    }


@router.get("/history/{quote_id}/shares")
async def list_share_links(
    quote_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_READ),
):
    if quote_history.get(quote_id) is None:
        raise HTTPException(404, "Angebot nicht gefunden.")
    return {"shares": quote_share.list_for_quote(quote_id)}


@router.delete("/history/{quote_id}/share")
async def revoke_open_share_link(
    quote_id: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    """Den offenen Link eines Angebots zurückziehen (das Merkmal selbst wird nicht gebraucht)."""
    return {"revoked": quote_share.revoke_open(quote_id)}


@router.delete("/history/{quote_id}/shares/{token}")
async def revoke_share_link(
    quote_id: str,
    token: str,
    _=RequirePermissionIfAuthEnabled(Permission.ARCHIVES_UPDATE_ALL),
):
    entry = quote_share.get(token)
    if entry is None or entry.get("quote_id") != str(quote_id):
        raise HTTPException(404, "Link nicht gefunden.")
    return {"revoked": quote_share.revoke(token)}


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{escape(title)}</title></head>"
        "<body style='margin:0; background:#f4f5f7; color:#1f2933;"
        " font-family: system-ui, -apple-system, Segoe UI, sans-serif'>"
        "<main style='max-width:46rem; margin:0 auto; padding:2rem 1.25rem 4rem'>"
        f"{body}</main></body></html>"
    )


def _money(value, currency: str) -> str:
    try:
        return f"{float(value):,.2f} {escape(str(currency))}".replace(",", "_").replace(".", ",").replace("_", ".")
    except (TypeError, ValueError):
        return ""


def _render_quote(entry: dict, view: dict, token: str) -> str:
    company = view["company"]
    status = entry.get("status")
    rows = "".join(
        "<tr>"
        f"<td style='padding:.4rem .5rem; border-bottom:1px solid #e4e7eb'>{escape(str(item['description']))}</td>"
        f"<td style='padding:.4rem .5rem; border-bottom:1px solid #e4e7eb; text-align:right'>{item['quantity'] or ''}</td>"
        f"<td style='padding:.4rem .5rem; border-bottom:1px solid #e4e7eb; text-align:right'>{_money(item['unit_price'], view['currency'])}</td>"
        f"<td style='padding:.4rem .5rem; border-bottom:1px solid #e4e7eb; text-align:right'>{_money(item['amount'], view['currency'])}</td>"
        "</tr>"
        for item in view["items"]
    )
    meta = [
        f"<div><span style='color:#6b7280'>Datum</span><br>{escape(view['date'])}</div>",
        f"<div><span style='color:#6b7280'>Gültig bis</span><br>{escape(view['valid_until'] or '—')}</div>",
        f"<div><span style='color:#6b7280'>Kunde</span><br>{escape(view['customer'])}</div>",
    ]
    result = ""
    if status in ("accepted", "declined"):
        when = escape(str(entry.get("responded_at") or "")[:16].replace("T", " "))
        label = "Angenommen" if status == "accepted" else "Abgelehnt"
        color = "#0f7b3f" if status == "accepted" else "#9b2c2c"
        note = escape(entry.get("note") or "")
        result = (
            f"<p style='border-left:4px solid {color}; padding:.6rem .9rem; background:#fff'>"
            f"<strong style='color:{color}'>{label}</strong> — {when}"
            + (f"<br><span style='color:#6b7280'>{note}</span>" if note else "")
            + "</p>"
        )
    else:
        result = (
            "<form method='post' style='margin-top:1.5rem; background:#fff; padding:1rem; border-radius:.5rem'>"
            "<p style='margin-top:0'>Passt das Angebot so für Sie?</p>"
            "<label style='display:block; color:#6b7280; font-size:.9rem; margin-bottom:.3rem'>"
            "Anmerkung (optional)</label>"
            "<textarea name='note' rows='3' maxlength='500' style='width:100%; box-sizing:border-box;"
            " font: inherit; padding:.5rem; border:1px solid #cbd2d9; border-radius:.35rem'></textarea>"
            "<div style='display:flex; gap:.75rem; flex-wrap:wrap; margin-top:.9rem'>"
            "<button type='submit' name='decision' value='accepted' style='font: inherit; padding:.65rem 1.4rem;"
            " border:0; border-radius:.4rem; background:#0f7b3f; color:#fff; cursor:pointer'>Annehmen</button>"
            "<button type='submit' name='decision' value='declined' style='font: inherit; padding:.65rem 1.4rem;"
            " border:1px solid #9b2c2c; border-radius:.4rem; background:#fff; color:#9b2c2c; cursor:pointer'>"
            "Ablehnen</button>"
            "</div>"
            f"<p style='color:#9ca3af; font-size:.8rem; margin:.9rem 0 0'>Link gültig bis "
            f"{escape(str(entry.get('expires_at') or '')[:10])}. Die Antwort lässt sich danach nicht mehr ändern.</p>"
            "</form>"
        )
    body = (
        f"<header style='margin-bottom:1.5rem'><h1 style='margin:0; font-size:1.35rem'>"
        f"{escape(company['name'] or 'Angebot')}</h1>"
        f"<p style='margin:.3rem 0 0; color:#6b7280; white-space:pre-line'>{escape(company['address'])}</p></header>"
        f"<h2 style='font-size:1.1rem; margin:0 0 .75rem'>Angebot {escape(view['number'])}</h2>"
        f"<section style='display:flex; gap:2rem; flex-wrap:wrap; background:#fff; padding:1rem;"
        f" border-radius:.5rem; font-size:.95rem'>{''.join(meta)}</section>"
        + (f"<p style='margin:1.25rem 0'>{escape(view['description'])}</p>" if view["description"] else "")
        + (
            "<table style='width:100%; border-collapse:collapse; background:#fff; border-radius:.5rem'>"
            "<thead><tr style='text-align:left; color:#6b7280; font-size:.85rem'>"
            "<th style='padding:.5rem'>Leistung</th><th style='padding:.5rem; text-align:right'>Menge</th>"
            "<th style='padding:.5rem; text-align:right'>Einzelpreis</th>"
            "<th style='padding:.5rem; text-align:right'>Betrag</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
            if rows
            else ""
        )
        + f"<p style='text-align:right; font-size:1.2rem; margin:1rem 0'><strong>Gesamtpreis "
        f"{_money(view['total'], view['currency'])}</strong></p>"
        + (
            f"<p style='color:#6b7280; font-size:.9rem'>{escape(company['vat_note'])}</p>"
            if company["vat_note"]
            else ""
        )
        + result
        + (
            f"<footer style='margin-top:2rem; color:#6b7280; font-size:.85rem'>"
            f"{escape(company['name'])}"
            + (f" · {escape(company['email'])}" if company["email"] else "")
            + (f" · {escape(company['phone'])}" if company["phone"] else "")
            + (f" · {escape(company['tax_id'])}" if company["tax_id"] else "")
            + "</footer>"
        )
    )
    return _page(f"Angebot {view['number']}", body)


def _error_page(message: str) -> str:
    return _page(
        "Link nicht gültig",
        "<h1 style='font-size:1.2rem'>Dieser Link funktioniert nicht</h1>"
        f"<p style='color:#6b7280'>{escape(message)}</p>",
    )


def _no_store(html: str) -> HTMLResponse:
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})


@router.get("/shared/{token}", response_class=HTMLResponse, include_in_schema=False)
async def public_quote_page(token: str):
    """Seite für den Kunden — ohne Anmeldung, ohne Schreibzugriff."""
    try:
        entry, _answered = quote_share.open_entry(token)
    except quote_share.ShareError as exc:
        return _no_store(_error_page(str(exc)))
    quote = quote_history.get(entry.get("quote_id", ""))
    if quote is None:
        return _no_store(_error_page("Das Angebot wurde inzwischen entfernt. Bitte den Absender um ein neues bitten."))
    return _no_store(_render_quote(entry, quote_share.public_view(quote, company_profile.read()), token))


@router.post("/shared/{token}", response_class=HTMLResponse, include_in_schema=False)
async def public_quote_response(
    token: str,
    decision: str = Form(""),
    note: str = Form(""),
):
    """Zusage oder Ablehnung — einmalig; danach zurück auf die Seite mit dem Ergebnis."""
    try:
        quote_share.respond(token, decision, note)
    except quote_share.ShareError as exc:
        return _no_store(_error_page(str(exc)))
    return RedirectResponse(f"{app_settings.api_prefix}/quote/shared/{token}", status_code=303)

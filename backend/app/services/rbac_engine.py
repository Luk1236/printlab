"""Rollenbasierte Zugriffskontrolle (RBAC - Role-Based Access Control) für PrintLab 2.0.

Unterteilt Zugriffsrechte in 4 strikte Enterprise-Rollen:
1. 'admin': Voller Zugriff auf Hardware, Einstellungen, Benutzer und Firmware.
2. 'operator': Werkstattbetrieb (Druck starten/stoppen, Plattenwechsel, Kalibrierung, Not-Halt).
3. 'accounting': Buchhaltung & Finanzen (Angebote, XRechnung, ZUGFeRD, Stripe, Kunden).
4. 'client_guest': Eingeschränkter Gastzugang (nur eigener Druckfortschritt & Live-Kamera).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PermissionDeniedError(PermissionError):
    """Wird ausgelöst, wenn eine Benutzerrolle unzureichende Rechte für eine Aktion besitzt."""

    def __init__(self, role: str, permission: str):
        super().__init__(f"Zugriff verweigert: Rolle '{role}' besitzt nicht die Berechtigung '{permission}'.")
        self.role = role
        self.permission = permission


# Definition aller Berechtigungen nach Rollen
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "*",  # Wildcard: Alle Rechte
    },
    "operator": {
        "hardware:control",
        "hardware:emergency_stop",
        "hardware:plate_swap",
        "hardware:temperatures",
        "print:start",
        "print:pause",
        "print:cancel",
        "print:view",
        "camera:view",
        "maintenance:perform",
        "assistant:use",
    },
    "accounting": {
        "finance:quotes:read",
        "finance:quotes:write",
        "finance:invoices:read",
        "finance:invoices:write",
        "finance:stripe:manage",
        "finance:company_settings",
        "print:view",
    },
    "client_guest": {
        "print:view:self",
        "camera:view:self",
        "finance:quotes:view_public",
    },
}


def get_role_permissions(role: str) -> list[str]:
    """Liefert alle aktiven Berechtigungen für eine gegebene Rolle."""
    clean_role = role.lower().strip()
    perms = ROLE_PERMISSIONS.get(clean_role, set())
    return sorted(perms)


def can_role_perform(role: str, permission: str) -> bool:
    """Prüft, ob eine Rolle eine bestimmte Berechtigung besitzt."""
    clean_role = role.lower().strip()
    clean_perm = permission.strip()

    perms = ROLE_PERMISSIONS.get(clean_role, set())
    if "*" in perms:
        return True

    # Exakter Treffer oder Sub-Scope (z. B. "print:view" erlaubt auch "print:view:self")
    if clean_perm in perms:
        return True

    parts = clean_perm.split(":")
    return bool(len(parts) > 1 and f"{parts[0]}:*" in perms)


def validate_user_permission(role: str, permission: str) -> None:
    """Wirft PermissionDeniedError, wenn die Rolle die Aktion nicht ausführen darf."""
    if not can_role_perform(role, permission):
        raise PermissionDeniedError(role=role, permission=permission)


def filter_menu_items_for_role(role: str, menu_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filtert Navigationselemente der Benutzeroberfläche anhand der Rolle des angemeldeten Benutzers."""
    allowed: list[dict[str, Any]] = []
    for item in menu_items:
        required_perm = item.get("required_permission")
        if not required_perm or can_role_perform(role, required_perm):
            allowed.append(item)
    return allowed

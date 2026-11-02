"""Tests für die Rollenbasierte Zugriffskontrolle (RBAC)."""

import pytest

from backend.app.services import rbac_engine


class TestRBACEngine:
    def test_admin_has_wildcard_permission(self):
        assert rbac_engine.can_role_perform("admin", "hardware:emergency_stop") is True
        assert rbac_engine.can_role_perform("admin", "system:firmware:flash") is True
        assert rbac_engine.can_role_perform("admin", "any:random:permission") is True

    def test_operator_permissions(self):
        assert rbac_engine.can_role_perform("operator", "hardware:emergency_stop") is True
        assert rbac_engine.can_role_perform("operator", "print:start") is True
        assert rbac_engine.can_role_perform("operator", "camera:view") is True
        # Operator darf KEINE Rechnungen oder Firmenkontodaten ändern
        assert rbac_engine.can_role_perform("operator", "finance:company_settings") is False
        assert rbac_engine.can_role_perform("operator", "system:users") is False

    def test_accounting_permissions(self):
        assert rbac_engine.can_role_perform("accounting", "finance:invoices:write") is True
        assert rbac_engine.can_role_perform("accounting", "finance:quotes:read") is True
        # Buchhaltung darf KEINE Hardware oder Not-Aus betätigen
        assert rbac_engine.can_role_perform("accounting", "hardware:control") is False
        assert rbac_engine.can_role_perform("accounting", "hardware:plate_swap") is False

    def test_client_guest_restricted_permissions(self):
        assert rbac_engine.can_role_perform("client_guest", "print:view:self") is True
        assert rbac_engine.can_role_perform("client_guest", "hardware:control") is False
        assert rbac_engine.can_role_perform("client_guest", "finance:invoices:write") is False

    def test_validate_user_permission_raises(self):
        with pytest.raises(rbac_engine.PermissionDeniedError, match="Zugriff verweigert"):
            rbac_engine.validate_user_permission("client_guest", "hardware:emergency_stop")

    def test_filter_menu_items_for_role(self):
        menu = [
            {"name": "Druckersteuerung", "required_permission": "hardware:control"},
            {"name": "Rechnungen & Finanzen", "required_permission": "finance:invoices:read"},
            {"name": "Systemprüfung", "required_permission": "camera:view"},
        ]
        operator_menu = rbac_engine.filter_menu_items_for_role("operator", menu)
        names = [item["name"] for item in operator_menu]
        assert "Druckersteuerung" in names
        assert "Systemprüfung" in names
        assert "Rechnungen & Finanzen" not in names

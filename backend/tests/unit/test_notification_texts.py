"""Meldungssprache: unveränderte Vorgaben werden übersetzt, eigene Texte nicht."""

from __future__ import annotations

from backend.app.models.notification_template import DEFAULT_TEMPLATES, NotificationTemplate
from backend.app.models.settings import Settings
from backend.app.services.notification_service import notification_service
from backend.app.services.notification_texts import localized_default

COMPLETE = next(entry for entry in DEFAULT_TEMPLATES if entry["event_type"] == "print_complete")


def test_only_untouched_defaults_are_translated():
    assert localized_default("print_complete", "de", COMPLETE["title_template"], COMPLETE["body_template"]) == (
        "Druck fertig",
        "{printer}: {filename}\nZeit: {duration}\nMaterial: {filament_grams} g",
    )
    assert localized_default("print_complete", "ja", COMPLETE["title_template"], COMPLETE["body_template"]) is not None
    # Eigene Formulierung: unangetastet lassen.
    assert localized_default("print_complete", "de", "Mein Druck ist fertig", COMPLETE["body_template"]) is None
    # Unbekannte Sprache oder Ereignis: englische Vorgabe.
    assert localized_default("print_complete", "xx", COMPLETE["title_template"], COMPLETE["body_template"]) is None
    assert localized_default("print_batch", "de", COMPLETE["title_template"], COMPLETE["body_template"]) is None


async def test_built_message_uses_the_configured_language(db_session):
    db_session.add(
        NotificationTemplate(
            event_type="print_complete",
            name=COMPLETE["name"],
            title_template=COMPLETE["title_template"],
            body_template=COMPLETE["body_template"],
            is_default=True,
        )
    )
    db_session.add(Settings(key="notification_language", value="fr"))
    await db_session.commit()
    notification_service.clear_template_cache()

    try:
        title, body = await notification_service._build_message_from_template(
            db_session,
            "print_complete",
            {"printer": "P1S", "filename": "benchy", "duration": "1h 2m", "filament_grams": 42},
        )
    finally:
        notification_service.clear_template_cache()

    assert title == "Impression terminée"
    assert "P1S : benchy" in body
    assert "Durée : 1h 2m" in body
    assert "Filament : 42 g" in body


async def test_edited_template_keeps_its_own_words(db_session):
    db_session.add(
        NotificationTemplate(
            event_type="print_stopped",
            name="Eigener Titel",
            title_template="Abgebrochen: {printer}",
            body_template="{filename} wurde gestoppt",
            is_default=False,
        )
    )
    db_session.add(Settings(key="notification_language", value="de"))
    await db_session.commit()
    notification_service.clear_template_cache()

    try:
        title, body = await notification_service._build_message_from_template(
            db_session, "print_stopped", {"printer": "P1S", "filename": "benchy"}
        )
    finally:
        notification_service.clear_template_cache()

    assert title == "Abgebrochen: P1S"
    assert body == "benchy wurde gestoppt"

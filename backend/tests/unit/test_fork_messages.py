"""English translation layer for the PrintLab extension messages."""

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from backend.app.i18n.fork_messages import ForkI18nMiddleware, translate, translate_json, wants_english


class TestLanguageChoice:
    @pytest.mark.parametrize("header", [None, "", "de", "de-DE,de;q=0.9,en;q=0.8", "DE", "*"])
    def test_german_or_missing_keeps_the_original(self, header):
        assert wants_english(header) is False

    @pytest.mark.parametrize("header", ["en", "en-US,en;q=0.9", "ja", "fr-FR", "zh-CN"])
    def test_other_languages_get_english(self, header):
        assert wants_english(header) is True


class TestTranslate:
    @pytest.mark.parametrize(
        ("german", "english"),
        [
            ("Tür geöffnet.", "Door opened."),
            ("Platte aus Fach 2 eingesetzt (Simulation).", "Plate from slot 2 inserted (simulation)."),
            ("Keine frische Platte im Magazin.", "No fresh plate in the magazine."),
            ("Es läuft bereits ein Hardware-Vorgang.", "A hardware operation is already running."),
            ("Not-Halt ausgelöst.", "Emergency stop triggered."),
            ("Befehl endete mit Code 3.", "Command exited with code 3."),
            ("Kundenname fehlt.", "Customer name is missing."),
            ("Betrag „total“ fehlt oder ist ungültig.", "Amount “total” is missing or invalid."),
            ("Der Drucker ist nicht verbunden.", "The printer is not connected."),
            ("Bett fährt (2/5) …", "Bed moving (2/5) …"),
            ("Platte frei automatisch bestätigt (Kamera, 87%).", "Plate clear confirmed automatically (camera, 87%)."),
        ],
    )
    def test_known_messages(self, german, english):
        assert translate(german) == english

    def test_composite_messages_are_translated_piecewise(self):
        text = "Tür schließen: Befehl fehlgeschlagen: x — Wechsel unvollständig (Platte getauscht, Magazin nachgeführt); Mechanik prüfen."
        out = translate(text)
        assert "Close door" in out and "change incomplete" in out and "check the mechanics" in out
        assert "unvollständig" not in out

    def test_magazine_warning(self):
        out = translate("Magazin: nur noch 1 frische Platte(n), kein freies Ablagefach mehr — bitte auffüllen bzw. leeren.")
        assert out.startswith("Magazine: only 1 fresh plate(s) left")
        assert "no free storage slot left" in out and "please refill or empty" in out

    def test_unknown_text_is_left_alone(self):
        assert translate("Etwas ganz anderes") == "Etwas ganz anderes"
        assert translate("Door opened.") == "Door opened."

    def test_json_structures_are_walked(self):
        data = {"message": "Tür geöffnet.", "slots": [{"label": "Fach 1"}], "n": 3, "ok": True, "x": None}
        out = translate_json(data)
        assert out["message"] == "Door opened." and out["slots"][0]["label"] == "Fach 1"
        assert out["n"] == 3 and out["ok"] is True and out["x"] is None


def make_app():
    app = FastAPI()

    @app.get("/api/v1/printers/1/hardware")
    async def hardware():
        return {"message": "Tür geöffnet.", "error": None}

    @app.get("/api/v1/printers/1/hardware/boom")
    async def boom():
        raise HTTPException(400, "Es läuft bereits ein Hardware-Vorgang.")

    @app.get("/api/v1/printers/1/status")
    async def other():
        return {"message": "Tür geöffnet."}

    @app.get("/api/v1/quote/file")
    async def not_json():
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse("Tür geöffnet.")

    app.add_middleware(ForkI18nMiddleware)
    return app


async def get(path, language=None):
    headers = {"Accept-Language": language} if language else {}
    async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as client:
        return await client.get(path, headers=headers)


class TestMiddleware:
    @pytest.mark.asyncio
    async def test_english_header_translates_the_response(self):
        resp = await get("/api/v1/printers/1/hardware", "en-US")
        assert resp.json()["message"] == "Door opened."
        assert int(resp.headers["content-length"]) == len(resp.content)

    @pytest.mark.asyncio
    async def test_german_or_no_header_is_untouched(self):
        assert (await get("/api/v1/printers/1/hardware", "de")).json()["message"] == "Tür geöffnet."
        assert (await get("/api/v1/printers/1/hardware")).json()["message"] == "Tür geöffnet."

    @pytest.mark.asyncio
    async def test_error_details_are_translated_and_keep_their_status(self):
        resp = await get("/api/v1/printers/1/hardware/boom", "en")
        assert resp.status_code == 400
        assert resp.json()["detail"] == "A hardware operation is already running."

    @pytest.mark.asyncio
    async def test_other_endpoints_are_not_touched(self):
        assert (await get("/api/v1/printers/1/status", "en")).json()["message"] == "Tür geöffnet."

    @pytest.mark.asyncio
    async def test_non_json_responses_pass_through(self):
        assert (await get("/api/v1/quote/file", "en")).text == "Tür geöffnet."

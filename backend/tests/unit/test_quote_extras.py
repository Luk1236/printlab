"""Angebote: einstellbares Nummernformat, Kundenanschrift und Logo im PDF."""

import io
import os

import pytest

pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from backend.app.services import company_profile, quote_history, quote_pdf  # noqa: E402

BODY = {
    "customer": "Müller GmbH",
    "customer_address": "Musterweg 3\n12345 Musterstadt\nDeutschland",
    "description": "Gehäuse",
    "material": 1,
    "energy": 1,
    "labor": 1,
    "subtotal": 3,
    "markup": 0.6,
    "total": 3.6,
}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(quote_history, "HISTORY_PATH", tmp_path / "quote_history.json")
    monkeypatch.setattr(company_profile, "COMPANY_PATH", tmp_path / "company.json")


def png_bytes(size=(60, 30), color=(200, 30, 30, 255), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGBA" if fmt == "PNG" else "RGB", size, color if fmt == "PNG" else color[:3]).save(buffer, format=fmt)
    return buffer.getvalue()


class TestNumberFormat:
    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("{prefix}-{year}-{seq4}", "PL-2026-0007"),
            ("{prefix}{yy}/{seq}", "PL26/7"),
            ("RE-{year}.{seq5}", "RE-2026.00007"),
            ("{seq}", "7"),
        ],
    )
    def test_formats(self, fmt, expected):
        assert quote_history.format_number(fmt, "PL", 2026, 7) == expected

    def test_numbers_use_the_given_format_and_keep_counting(self):
        first = quote_history.add(BODY, prefix="PL", number_format="{prefix}{yy}/{seq}")
        second = quote_history.add(BODY, prefix="PL", number_format="{prefix}{yy}/{seq}")
        assert first["number"].endswith("/1") and second["number"].endswith("/2")

    def test_company_accepts_valid_formats_and_refuses_others(self):
        assert (
            company_profile.write({"number_format": "{prefix}-{yy}-{seq4}"})["number_format"] == "{prefix}-{yy}-{seq4}"
        )
        for bad in ("keine-laufende-nummer", "{prefix}-{seq4}-{nope}", "{seq4} mit Leerzeichen", "{seq4}}", "../{seq}"):
            with pytest.raises(ValueError, match="Nummernformat"):
                company_profile.write({"number_format": bad})

    def test_empty_format_falls_back_to_the_default(self):
        assert company_profile.write({"number_format": ""})["number_format"] == company_profile.DEFAULT_NUMBER_FORMAT

    def test_broken_stored_format_is_replaced_on_read(self):
        company_profile.COMPANY_PATH.write_text('{"number_format": "kaputt"}')
        assert company_profile.read()["number_format"] == company_profile.DEFAULT_NUMBER_FORMAT


class TestCustomerAddress:
    def test_address_is_stored_and_limited(self):
        entry = quote_history.add({**BODY, "customer_address": "x" * 500})
        assert len(entry["customer_address"]) == 240
        assert quote_history.get(entry["id"])["customer_address"] == "x" * 240

    def test_missing_address_is_empty(self):
        body = {k: v for k, v in BODY.items() if k != "customer_address"}
        assert quote_history.add(body)["customer_address"] == ""

    def test_pdf_with_address_renders(self):
        entry = quote_history.add(BODY)
        assert quote_pdf.render(entry, company_profile.read()).startswith(b"%PDF")


class TestLogo:
    def test_png_is_stored_as_a_clean_png(self):
        company_profile.save_logo(png_bytes())
        path = company_profile.logo_path()
        assert path and path.name == company_profile.LOGO_NAME
        with Image.open(path) as image:
            assert image.format == "PNG" and image.size == (60, 30)
        assert company_profile.read()["has_logo"] is True

    def test_jpeg_is_accepted_and_converted(self):
        company_profile.save_logo(png_bytes(fmt="JPEG"))
        with Image.open(company_profile.logo_path()) as image:
            assert image.format == "PNG"

    def test_large_images_are_scaled_down(self):
        company_profile.save_logo(png_bytes(size=(3000, 1500)))
        with Image.open(company_profile.logo_path()) as image:
            assert max(image.size) <= company_profile.LOGO_MAX_EDGE

    @pytest.mark.parametrize("data", [b"", b"das ist kein bild", b"GIF89a" + b"x" * 40, b"\x89PNG\r\n\x1a\nkaputt"])
    def test_garbage_is_refused_and_nothing_is_stored(self, data):
        with pytest.raises(ValueError):
            company_profile.save_logo(data)
        assert company_profile.logo_path() is None

    def test_too_big_is_refused(self):
        with pytest.raises(ValueError, match="2 MB"):
            company_profile.save_logo(b"x" * (company_profile.MAX_LOGO_BYTES + 1))

    def test_gif_is_not_a_permitted_format(self):
        buffer = io.BytesIO()
        Image.new("P", (10, 10)).save(buffer, format="GIF")
        with pytest.raises(ValueError, match="PNG oder JPEG"):
            company_profile.save_logo(buffer.getvalue())

    def test_delete(self):
        company_profile.save_logo(png_bytes())
        assert company_profile.delete_logo() is True
        assert company_profile.delete_logo() is False
        assert company_profile.read()["has_logo"] is False

    def test_pdf_with_logo_is_larger_and_a_broken_logo_never_blocks_it(self, tmp_path):
        entry = quote_history.add(BODY)
        without = quote_pdf.render(entry, company_profile.read())
        company_profile.save_logo(png_bytes(size=(300, 150)))
        with_logo = quote_pdf.render(entry, {**company_profile.read(), "_logo_path": company_profile.logo_path()})
        assert with_logo.startswith(b"%PDF") and len(with_logo) > len(without)
        broken = tmp_path / "kaputt.png"
        broken.write_bytes(b"nichts")
        assert quote_pdf.render(entry, {**company_profile.read(), "_logo_path": broken}).startswith(b"%PDF")

    @pytest.mark.skipif(os.name == "nt", reason="nur zur Dokumentation: Metadaten werden verworfen")
    def test_metadata_is_dropped(self):
        buffer = io.BytesIO()
        image = Image.new("RGBA", (20, 20), (1, 2, 3, 255))
        image.save(buffer, format="PNG", pnginfo=_info("Autor", "Geheim"))
        company_profile.save_logo(buffer.getvalue())
        with Image.open(company_profile.logo_path()) as stored:
            assert "Autor" not in stored.info


def _info(key, value):
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text(key, value)
    return info

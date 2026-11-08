"""Unit-Tests für die 3D-Mesh- und Geometrieanalyse."""

from __future__ import annotations

import io
import pytest
import trimesh

from backend.app.services.mesh_analysis import (
    MeshAnalysisResult,
    analyze_mesh_data,
)


def _make_box_stl_bytes(x=20.0, y=30.0, z=10.0) -> bytes:
    box = trimesh.creation.box(extents=(x, y, z))
    buf = io.BytesIO()
    box.export(buf, file_type="stl")
    return buf.getvalue()


def test_analyze_valid_box_stl():
    # 20x30x10 mm Box = 6000 mm³ = 6.00 cm³
    stl_bytes = _make_box_stl_bytes(20.0, 30.0, 10.0)
    result = analyze_mesh_data(stl_bytes, "test_cube.stl")

    assert isinstance(result, MeshAnalysisResult)
    assert result.filename == "test_cube.stl"
    assert pytest.approx(result.volume_cm3, rel=1e-2) == 6.0
    assert result.is_watertight is True
    assert result.fits_bed is True
    assert result.dimensions_mm[0] == pytest.approx(20.0, rel=1e-1)
    assert result.dimensions_mm[1] == pytest.approx(30.0, rel=1e-1)
    assert result.dimensions_mm[2] == pytest.approx(10.0, rel=1e-1)
    assert result.triangle_count == 12

    d = result.to_dict()
    assert d["volume_cm3"] == pytest.approx(6.0, rel=1e-2)
    assert d["fits_bed"] is True
    assert "dimensions_mm" in d


def test_analyze_oversized_mesh():
    # 300x100x50 mm Box (überschreitet 256mm Bauraum)
    stl_bytes = _make_box_stl_bytes(300.0, 100.0, 50.0)
    result = analyze_mesh_data(stl_bytes, "oversized.stl")

    assert result.fits_bed is False
    assert len(result.warnings) > 0
    assert "Bauraum" in result.warnings[0]


def test_analyze_corrupt_data():
    with pytest.raises(ValueError) as exc:
        analyze_mesh_data(b"not a valid stl content at all 1234567890" * 5, "broken.stl")
    assert "Geometrie" in str(exc.value)


def test_analyze_empty_data():
    with pytest.raises(ValueError) as exc:
        analyze_mesh_data(b"", "empty.stl")
    assert "leer" in str(exc.value)

"""3D-Mesh- und Geometrieanalyse für den Sofort-Kalkulator.

Analysiert hochgeladene STL-, OBJ- und 3MF-Dateien:
- Exaktes Volumen in cm³
- Bounding-Box Abmessungen (X, Y, Z in mm)
- Oberflächengröße in cm²
- Wasserdichtigkeit (Watertight) und Dreiecksanzahl
- Bauraum-Prüfung (z. B. Bambu Lab 256×256×256 mm)
- Automatische 2D-Vorschau (Thumbnail)
"""

from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    import trimesh

    TRIMESH_AVAILABLE = True
except ImportError:
    trimesh = None  # type: ignore[assignment]
    TRIMESH_AVAILABLE = False

MAX_BED_DIMENSIONS_MM = (256.0, 256.0, 256.0)  # Bambu Lab P1/X1/A1 Bauraum


class MeshAnalysisResult:
    """Strukturiertes Ergebnis einer 3D-Modellanalyse."""

    def __init__(
        self,
        filename: str,
        volume_cm3: float,
        dimensions_mm: tuple[float, float, float],
        surface_area_cm2: float,
        triangle_count: int,
        is_watertight: bool,
        fits_bed: bool,
        thumbnail_b64: str | None = None,
        warnings: list[str] | None = None,
    ):
        self.filename = filename
        self.volume_cm3 = float(round(volume_cm3, 2))
        self.dimensions_mm = (
            float(round(dimensions_mm[0], 1)),
            float(round(dimensions_mm[1], 1)),
            float(round(dimensions_mm[2], 1)),
        )
        self.surface_area_cm2 = float(round(surface_area_cm2, 1))
        self.triangle_count = int(triangle_count)
        self.is_watertight = bool(is_watertight)
        self.fits_bed = bool(fits_bed)
        self.thumbnail_b64 = thumbnail_b64
        self.warnings = warnings or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "volume_cm3": self.volume_cm3,
            "dimensions_mm": {
                "x": self.dimensions_mm[0],
                "y": self.dimensions_mm[1],
                "z": self.dimensions_mm[2],
            },
            "surface_area_cm2": self.surface_area_cm2,
            "triangle_count": self.triangle_count,
            "is_watertight": self.is_watertight,
            "fits_bed": self.fits_bed,
            "has_thumbnail": self.thumbnail_b64 is not None,
            "thumbnail_b64": self.thumbnail_b64,
            "warnings": self.warnings,
        }


def analyze_mesh_data(file_bytes: bytes, filename: str) -> MeshAnalysisResult:
    """Analysiert die Geometrie einer 3D-Modelldatei (STL, 3MF, OBJ)."""
    if not TRIMESH_AVAILABLE:
        raise RuntimeError("Das Modul 'trimesh' ist nicht verfügbar.")

    if not file_bytes or len(file_bytes) < 100:
        raise ValueError("Die Datei ist leer oder beschädigt.")

    ext = Path(filename).suffix.lower().lstrip(".")
    if not ext:
        ext = "stl"

    warnings: list[str] = []

    try:
        # Mesh via Trimesh laden
        loaded = trimesh.load(io.BytesIO(file_bytes), file_type=ext)

        # Wenn Scene (z. B. aus 3MF oder Multi-Body OBJ), Geometrien zusammenführen
        if isinstance(loaded, trimesh.Scene):
            if not loaded.geometry:
                raise ValueError("Die 3D-Datei enthält keine Geometrie-Körper.")
            mesh = trimesh.util.concatenate(list(loaded.geometry.values()))
        else:
            mesh = loaded

        if not hasattr(mesh, "vertices") or len(mesh.vertices) == 0:
            raise ValueError("Das Modell enthält keine Knotenpunkte (Vertices).")

        # 1. Bounding-Box Abmessungen
        bounds = mesh.bounds
        extents = bounds[1] - bounds[0]
        dims = (float(extents[0]), float(extents[1]), float(extents[2]))

        # Bauraum-Prüfung
        fits = (
            dims[0] <= MAX_BED_DIMENSIONS_MM[0]
            and dims[1] <= MAX_BED_DIMENSIONS_MM[1]
            and dims[2] <= MAX_BED_DIMENSIONS_MM[2]
        )
        if not fits:
            warnings.append(
                f"Modell überschreitet den Standard-Bauraum ({dims[0]:.0f}×{dims[1]:.0f}×{dims[2]:.0f} mm > {MAX_BED_DIMENSIONS_MM[0]:.0f} mm)."
            )

        # 2. Volumenberechnung
        is_watertight = bool(getattr(mesh, "is_watertight", False))
        if is_watertight and hasattr(mesh, "volume"):
            raw_vol_mm3 = abs(float(mesh.volume))
            vol_cm3 = raw_vol_mm3 / 1000.0
        else:
            # Fallback für offene / nicht geschlossene Netze
            warnings.append("Modellnetz ist nicht wasserdicht; Volumen wurde approximiert.")
            if hasattr(mesh, "convex_hull") and hasattr(mesh.convex_hull, "volume"):
                vol_cm3 = (abs(float(mesh.convex_hull.volume)) * 0.75) / 1000.0
            else:
                # Schätzung über Bounding-Box
                bbox_vol = (dims[0] * dims[1] * dims[2]) / 1000.0
                vol_cm3 = max(0.5, bbox_vol * 0.5)

        # Mindestvolumen 0.1 cm³
        vol_cm3 = max(0.1, vol_cm3)

        # 3. Oberfläche
        surface_cm2 = (float(mesh.area) / 100.0) if hasattr(mesh, "area") else 0.0

        # 4. Dreiecksanzahl
        tri_count = int(mesh.faces.shape[0]) if hasattr(mesh, "faces") else len(mesh.vertices) // 3

        # 5. Thumbnail-Erzeugung
        thumbnail_b64: str | None = None
        try:
            from backend.app.services.stl_thumbnail import render_mesh_png

            thumb_png = render_mesh_png(mesh, size=200, label=filename)
            if thumb_png:
                b64 = base64.b64encode(thumb_png).decode("ascii")
                thumbnail_b64 = f"data:image/png;base64,{b64}"
        except Exception as t_exc:
            logger.debug("Thumbnail-Erstellung übersprungen: %s", t_exc)

        return MeshAnalysisResult(
            filename=filename,
            volume_cm3=vol_cm3,
            dimensions_mm=dims,
            surface_area_cm2=surface_cm2,
            triangle_count=tri_count,
            is_watertight=is_watertight,
            fits_bed=fits,
            thumbnail_b64=thumbnail_b64,
            warnings=warnings,
        )

    except Exception as exc:
        logger.warning("Fehler bei Mesh-Analyse von '%s': %s", filename, exc)
        raise ValueError(f"3D-Geometrie konnte nicht analysiert werden: {exc}") from exc

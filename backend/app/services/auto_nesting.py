"""2D-Bin-Packing Auto-Nesting, 3D-Orientierungsanalyse, M486-G-Code-Injektor & Farm-Seriensplit (Phase 13).

Stellt vier eng verzahnte Kernfunktionen für die Serienfertigung bereit:
1. ``pack_parts_onto_plates``: Kollisionsfreies 2D-Bin-Packing (Best-Short-Side-Fit / Guillotine)
   mit automatischer 90°-Drehungsoptimierung auf eine oder mehrere Bauplatten (Standard 256×256 mm).
2. ``suggest_optimal_orientation``: Bewertet die 6 Haupt-Orthogonalausrichtungen eines 3D-Modells
   anhand von Auflagefläche, Überhangfläche (>45°), Schwerpunkthöhe und Kippsicherheit.
3. ``inject_m486_object_markers``: Analysiert G-Code und injiziert fehlende ``M486``-Objektmarker,
   damit einzelne fehlerhafte Bauteile während des Drucks übersprungen werden können (``skip_objects``).
4. ``split_batch_across_fleet``: Verteilt die gepackten Bauplatten einer Großserie optimal auf
   mehrere kompatible Farm-Drucker zur Minimierung der Gesamtdurchlaufzeit (Makespan).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from backend.app.services.fleet_load_balancer import MIN_DISPATCH_SCORE, calculate_printer_fitness

DEFAULT_BED_WIDTH_MM = 256.0
DEFAULT_BED_DEPTH_MM = 256.0
DEFAULT_BED_HEIGHT_MM = 256.0
DEFAULT_MARGIN_MM = 5.0
DEFAULT_SPACING_MM = 4.0


@dataclass(frozen=True)
class NestingPart:
    """Ein zu platzierendes Bauteil (ggf. mit mehreren Kopien)."""

    part_id: str
    name: str
    width_mm: float
    depth_mm: float
    height_mm: float = 10.0
    copies: int = 1
    allow_rotation: bool = True
    filament_grams_per_copy: float = 10.0
    print_minutes_per_copy: float = 20.0


@dataclass(frozen=True)
class PlacedInstance:
    """Eine konkret auf einer Bauplatte platzierte Bauteil-Instanz."""

    instance_id: int
    part_id: str
    name: str
    copy_index: int
    min_x_mm: float
    min_y_mm: float
    width_mm: float
    depth_mm: float
    height_mm: float
    center_x_mm: float
    center_y_mm: float
    rotated_90: bool
    filament_grams: float
    print_minutes: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "part_id": self.part_id,
            "name": self.name,
            "copy_index": self.copy_index,
            "min_x_mm": round(self.min_x_mm, 2),
            "min_y_mm": round(self.min_y_mm, 2),
            "width_mm": round(self.width_mm, 2),
            "depth_mm": round(self.depth_mm, 2),
            "height_mm": round(self.height_mm, 2),
            "center_x_mm": round(self.center_x_mm, 2),
            "center_y_mm": round(self.center_y_mm, 2),
            "rotated_90": self.rotated_90,
            "filament_grams": round(self.filament_grams, 2),
            "print_minutes": round(self.print_minutes, 2),
        }


@dataclass
class NestedPlate:
    """Eine belegte Bauplatte mit allen darauf platzierten Bauteil-Instanzen."""

    plate_index: int
    bed_width_mm: float
    bed_depth_mm: float
    usable_width_mm: float
    usable_depth_mm: float
    placements: list[PlacedInstance] = field(default_factory=list)

    @property
    def used_area_mm2(self) -> float:
        return sum(p.width_mm * p.depth_mm for p in self.placements)

    @property
    def usable_area_mm2(self) -> float:
        return max(1.0, self.usable_width_mm * self.usable_depth_mm)

    @property
    def utilization_percent(self) -> float:
        return round(min(100.0, (self.used_area_mm2 / self.usable_area_mm2) * 100.0), 2)

    @property
    def total_filament_grams(self) -> float:
        return round(sum(p.filament_grams for p in self.placements), 2)

    @property
    def estimated_print_minutes(self) -> float:
        return round(sum(p.print_minutes for p in self.placements), 2)

    @property
    def max_height_mm(self) -> float:
        return round(max((p.height_mm for p in self.placements), default=0.0), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plate_index": self.plate_index,
            "instance_count": len(self.placements),
            "utilization_percent": self.utilization_percent,
            "total_filament_grams": self.total_filament_grams,
            "estimated_print_minutes": self.estimated_print_minutes,
            "max_height_mm": self.max_height_mm,
            "placements": [p.to_dict() for p in self.placements],
        }


def verify_no_collisions(placements: list[PlacedInstance], spacing_mm: float = 0.0, eps: float = 1e-4) -> bool:
    """Prüft mathematisch, dass sich keine zwei Bounding-Boxen auf einer Platte überlappen."""
    n = len(placements)
    half_gap = max(0.0, spacing_mm) * 0.5 - eps
    for i in range(n):
        a = placements[i]
        ax0, ay0 = a.min_x_mm - half_gap, a.min_y_mm - half_gap
        ax1, ay1 = a.min_x_mm + a.width_mm + half_gap, a.min_y_mm + a.depth_mm + half_gap
        for j in range(i + 1, n):
            b = placements[j]
            bx0, by0 = b.min_x_mm - half_gap, b.min_y_mm - half_gap
            bx1, by1 = b.min_x_mm + b.width_mm + half_gap, b.min_y_mm + b.depth_mm + half_gap
            overlap_x = ax0 < bx1 - eps and ax1 > bx0 + eps
            overlap_y = ay0 < by1 - eps and ay1 > by0 + eps
            if overlap_x and overlap_y:
                return False
    return True


class _GuillotineBin:
    """2D-Guillotine-Bin-Packer (Best-Short-Side-Fit) für eine einzelne Bauplatte."""

    def __init__(self, width: float, depth: float, margin_x: float, margin_y: float, spacing: float):
        self.width = width
        self.depth = depth
        self.margin_x = margin_x
        self.margin_y = margin_y
        self.spacing = spacing
        # Freie Rechtecke als (x, y, w, d) im nutzbaren Bereich (inkl. +spacing Puffer rechts/oben)
        self.free_rects: list[tuple[float, float, float, float]] = [
            (0.0, 0.0, width + spacing, depth + spacing)
        ]

    def try_insert(self, w: float, d: float, allow_rotation: bool) -> tuple[float, float, float, float, bool] | None:
        """Versucht ein Rechteck (w, d) einzufügen. Liefert (x, y, placed_w, placed_d, rotated_90) oder None."""
        req_w = w + self.spacing
        req_d = d + self.spacing

        best_score: tuple[float, float] | None = None
        best_idx = -1
        best_choice: tuple[float, float, bool] | None = None

        candidates = [(req_w, req_d, w, d, False)]
        if allow_rotation and abs(w - d) > 1e-4:
            candidates.append((req_d, req_w, d, w, True))

        for idx, (fx, fy, fw, fd) in enumerate(self.free_rects):
            for rw, rd, orig_w, orig_d, rot in candidates:
                if rw <= fw + 1e-6 and rd <= fd + 1e-6:
                    leftover_h = abs(fw - rw)
                    leftover_v = abs(fd - rd)
                    short_side = min(leftover_h, leftover_v)
                    long_side = max(leftover_h, leftover_v)
                    score = (short_side, long_side)
                    if best_score is None or score < best_score:
                        best_score = score
                        best_idx = idx
                        best_choice = (orig_w, orig_d, rot)

        if best_idx < 0 or best_choice is None:
            return None

        fx, fy, fw, fd = self.free_rects.pop(best_idx)
        placed_w, placed_d, rotated = best_choice
        used_w = placed_w + self.spacing
        used_d = placed_d + self.spacing

        # Guillotine-Split entlang der kürzeren Restachse für maximal große zusammenhängende Restflächen
        rem_w = fw - used_w
        rem_d = fd - used_d
        if rem_w > 1e-3 and rem_d > 1e-3:
            if rem_w < rem_d:
                self.free_rects.append((fx + used_w, fy, rem_w, used_d))
                self.free_rects.append((fx, fy + used_d, fw, rem_d))
            else:
                self.free_rects.append((fx, fy + used_d, used_w, rem_d))
                self.free_rects.append((fx + used_w, fy, rem_w, fd))
        elif rem_w > 1e-3:
            self.free_rects.append((fx + used_w, fy, rem_w, fd))
        elif rem_d > 1e-3:
            self.free_rects.append((fx, fy + used_d, fw, rem_d))

        return (self.margin_x + fx, self.margin_y + fy, placed_w, placed_d, rotated)


def pack_parts_onto_plates(
    parts: list[NestingPart],
    *,
    bed_width_mm: float = DEFAULT_BED_WIDTH_MM,
    bed_depth_mm: float = DEFAULT_BED_DEPTH_MM,
    bed_height_mm: float = DEFAULT_BED_HEIGHT_MM,
    margin_mm: float = DEFAULT_MARGIN_MM,
    spacing_mm: float = DEFAULT_SPACING_MM,
) -> dict[str, Any]:
    """Packt Bauteile (mit Kopien) kollisionsfrei auf eine oder mehrere Bauplatten."""
    usable_w = max(10.0, bed_width_mm - 2.0 * margin_mm)
    usable_d = max(10.0, bed_depth_mm - 2.0 * margin_mm)

    oversized: list[dict[str, Any]] = []
    expanded: list[tuple[NestingPart, int]] = []

    for part in parts:
        if part.copies <= 0:
            continue
        fits_normal = part.width_mm <= usable_w + 1e-6 and part.depth_mm <= usable_d + 1e-6
        fits_rotated = (
            part.allow_rotation and part.depth_mm <= usable_w + 1e-6 and part.width_mm <= usable_d + 1e-6
        )
        fits_height = part.height_mm <= bed_height_mm + 1e-6

        if (not fits_normal and not fits_rotated) or not fits_height:
            oversized.append(
                {
                    "part_id": part.part_id,
                    "name": part.name,
                    "width_mm": part.width_mm,
                    "depth_mm": part.depth_mm,
                    "height_mm": part.height_mm,
                    "copies": part.copies,
                    "reason": (
                        f"Bauteil ({part.width_mm:.1f}×{part.depth_mm:.1f}×{part.height_mm:.1f} mm) "
                        f"überschreitet den nutzbaren Bauraum ({usable_w:.1f}×{usable_d:.1f}×{bed_height_mm:.1f} mm)."
                    ),
                }
            )
            continue

        for copy_idx in range(1, part.copies + 1):
            expanded.append((part, copy_idx))

    # Absteigend nach Grundfläche (und längerer Kante) sortieren -> optimale Packdichte
    expanded.sort(
        key=lambda item: (item[0].width_mm * item[0].depth_mm, max(item[0].width_mm, item[0].depth_mm)),
        reverse=True,
    )

    bins: list[_GuillotineBin] = []
    plates: list[NestedPlate] = []
    next_instance_id = 1

    for part, copy_idx in expanded:
        placed_tuple = None
        target_plate_idx = -1

        for b_idx, gbin in enumerate(bins):
            res = gbin.try_insert(part.width_mm, part.depth_mm, part.allow_rotation)
            if res is not None:
                placed_tuple = res
                target_plate_idx = b_idx
                break

        if placed_tuple is None:
            new_bin = _GuillotineBin(usable_w, usable_d, margin_mm, margin_mm, spacing_mm)
            res = new_bin.try_insert(part.width_mm, part.depth_mm, part.allow_rotation)
            if res is None:
                continue
            bins.append(new_bin)
            plates.append(
                NestedPlate(
                    plate_index=len(plates) + 1,
                    bed_width_mm=bed_width_mm,
                    bed_depth_mm=bed_depth_mm,
                    usable_width_mm=usable_w,
                    usable_depth_mm=usable_d,
                )
            )
            placed_tuple = res
            target_plate_idx = len(plates) - 1

        px, py, pw, pd, rotated = placed_tuple
        instance = PlacedInstance(
            instance_id=next_instance_id,
            part_id=part.part_id,
            name=part.name,
            copy_index=copy_idx,
            min_x_mm=px,
            min_y_mm=py,
            width_mm=pw,
            depth_mm=pd,
            height_mm=part.height_mm,
            center_x_mm=px + pw * 0.5,
            center_y_mm=py + pd * 0.5,
            rotated_90=rotated,
            filament_grams=part.filament_grams_per_copy,
            print_minutes=part.print_minutes_per_copy,
        )
        next_instance_id += 1
        plates[target_plate_idx].placements.append(instance)

    collision_free = all(verify_no_collisions(plate.placements, spacing_mm=spacing_mm) for plate in plates)
    total_placed = sum(len(plate.placements) for plate in plates)
    avg_utilization = (
        round(sum(p.utilization_percent for p in plates) / len(plates), 2) if plates else 0.0
    )

    return {
        "total_parts_requested": sum(max(0, p.copies) for p in parts),
        "total_parts_placed": total_placed,
        "total_plates": len(plates),
        "average_utilization_percent": avg_utilization,
        "collision_free": collision_free,
        "total_filament_grams": round(sum(p.total_filament_grams for p in plates), 2),
        "total_estimated_minutes": round(sum(p.estimated_print_minutes for p in plates), 2),
        "plates": [p.to_dict() for p in plates],
        "oversized_parts": oversized,
    }


def suggest_optimal_orientation(
    dimensions_mm: tuple[float, float, float],
    *,
    overhang_ratio_by_axis: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Bewertet die 6 orthogonalen Druckausrichtungen (+Z, -Z, +X, -X, +Y, -Y) eines Bauteils.

    Kriterien:
    - Große Grundfläche (X×Y) erhöht Betthaftung und verhindert Umkippen.
    - Niedrige Bauhöhe (Z) senkt das Hebelmoment und beschleunigt den Druck.
    - Geringes Überhangverhältnis minimiert Support-Material.
    """
    dx, dy, dz = (max(0.1, float(dimensions_mm[0])), max(0.1, float(dimensions_mm[1])), max(0.1, float(dimensions_mm[2])))
    overhangs = overhang_ratio_by_axis or {}

    orientations = [
        ("original_z_up", "Standard (0°)", (dx, dy, dz), overheads := overhangs.get("z_up", 0.10)),
        ("flip_z_down", "180° um X-Achse gedreht", (dx, dy, dz), overhangs.get("z_down", 0.12)),
        ("rotate_x_plus_90", "+90° um X-Achse (Tiefe wird Höhe)", (dx, dz, dy), overhangs.get("x_plus", 0.15)),
        ("rotate_x_minus_90", "-90° um X-Achse", (dx, dz, dy), overhangs.get("x_minus", 0.15)),
        ("rotate_y_plus_90", "+90° um Y-Achse (Breite wird Höhe)", (dz, dy, dx), overhangs.get("y_plus", 0.15)),
        ("rotate_y_minus_90", "-90° um Y-Achse", (dz, dy, dx), overhangs.get("y_minus", 0.15)),
    ]
    del overheads

    max_area = max(w * d for _, _, (w, d, _), _ in orientations)
    max_h = max(h for _, _, (_, _, h), _ in orientations)

    candidates: list[dict[str, Any]] = []
    for key, label, (w, d, h), oh_ratio in orientations:
        footprint_mm2 = w * d
        area_score = (footprint_mm2 / max_area) * 45.0
        height_score = (1.0 - (h / (max_h * 1.25))) * 35.0
        overhang_score = max(0.0, (1.0 - min(1.0, float(oh_ratio))) * 20.0)
        total_score = round(area_score + height_score + overhang_score, 1)

        candidates.append(
            {
                "orientation_id": key,
                "label": label,
                "footprint_width_mm": round(w, 1),
                "footprint_depth_mm": round(d, 1),
                "height_mm": round(h, 1),
                "footprint_area_mm2": round(footprint_mm2, 1),
                "aspect_ratio_stability": round(min(w, d) / max(0.1, h), 2),
                "overhang_ratio": round(float(oh_ratio), 3),
                "score": total_score,
            }
        )

    candidates.sort(key=lambda c: (-c["score"], c["height_mm"]))
    best = candidates[0]
    return {
        "recommended": best,
        "alternatives": candidates[1:],
    }


def inject_m486_object_markers(gcode: str, object_names: list[str] | None = None) -> dict[str, Any]:
    """Analysiert G-Code und injiziert fehlende ``M486``-Objektmarker für Einzelobjekt-Ausschluss (`skip_objects`)."""
    lines = gcode.splitlines()
    existing_m486_s = re.compile(r"^\s*M486\s+S(\d+)", re.IGNORECASE)
    existing_m486_t = re.compile(r"^\s*M486\s+T(\d+)", re.IGNORECASE)
    comment_obj = re.compile(
        r"^\s*;\s*(?:printing object|OBJECT_START|start object)\s+([^\s;]+)(?:\s+id:(\d+))?",
        re.IGNORECASE,
    )
    comment_stop = re.compile(
        r"^\s*;\s*(?:stop printing object|OBJECT_END|end object)\s+([^\s;]+)?",
        re.IGNORECASE,
    )

    has_m486_t = any(existing_m486_t.match(line) for line in lines)
    s_indices_found: set[int] = set()
    for line in lines:
        m = existing_m486_s.match(line)
        if m:
            s_indices_found.add(int(m.group(1)))

    # Zuordnung von Objektnamen -> Index (0-basiert)
    known_names: list[str] = list(object_names or [])
    name_to_idx: dict[str, int] = {name: i for i, name in enumerate(known_names)}

    for line in lines:
        m = comment_obj.match(line)
        if m:
            obj_name = m.group(1).strip()
            if obj_name not in name_to_idx:
                name_to_idx[obj_name] = len(known_names)
                known_names.append(obj_name)

    total_objects = max(len(known_names), len(s_indices_found))
    injected_markers = 0
    out_lines: list[str] = []

    if total_objects > 0 and not has_m486_t:
        out_lines.append(f"M486 T{total_objects}")
        injected_markers += 1

    for line in lines:
        m_start = comment_obj.match(line)
        m_stop = comment_stop.match(line)
        out_lines.append(line)
        if m_start:
            obj_name = m_start.group(1).strip()
            explicit_id = m_start.group(2)
            idx = int(explicit_id) if explicit_id is not None else name_to_idx.get(obj_name, 0)
            if idx not in s_indices_found:
                out_lines.append(f"M486 S{idx}")
                injected_markers += 1
        elif m_stop and not s_indices_found:
            out_lines.append("M486 S-1")
            injected_markers += 1

    return {
        "total_objects": total_objects,
        "object_names": known_names,
        "injected_markers": injected_markers,
        "already_had_m486": bool(s_indices_found or has_m486_t),
        "gcode": "\n".join(out_lines) + ("\n" if gcode.endswith("\n") else ""),
    }


def split_batch_across_fleet(
    nesting_result: dict[str, Any],
    printers: list[dict[str, Any]],
    job_requirements: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verteilt die Bauplatten aus ``pack_parts_onto_plates`` optimal auf alle geeigneten Farm-Drucker.

    Nutzt Longest-Processing-Time-First (LPT) Scheduling über die nach Fitness gewichteten
    Drucker, um die Gesamtdurchlaufzeit (Makespan) der Großserie zu minimieren.
    """
    plates = nesting_result.get("plates") or []
    reqs = dict(job_requirements or {})

    eligible_printers: list[dict[str, Any]] = []
    for p in printers:
        plate_req = {
            **reqs,
            "filament_grams": max((pl.get("total_filament_grams", 10.0) for pl in plates), default=10.0),
        }
        score, reasons = calculate_printer_fitness(p, plate_req)
        if score >= MIN_DISPATCH_SCORE:
            eligible_printers.append(
                {
                    "printer_id": p["id"],
                    "printer_name": p.get("name", f"Drucker {p['id']}"),
                    "fitness_score": score,
                    "reasons": reasons,
                    "assigned_plates": [],
                    "total_assigned_minutes": 0.0,
                    "total_assigned_grams": 0.0,
                }
            )

    eligible_printers.sort(key=lambda x: x["fitness_score"], reverse=True)
    single_printer_minutes = round(sum(float(pl.get("estimated_print_minutes", 0.0)) for pl in plates), 2)

    if not eligible_printers or not plates:
        return {
            "can_dispatch_parallel": False,
            "eligible_printer_count": len(eligible_printers),
            "total_plates": len(plates),
            "single_printer_minutes": single_printer_minutes,
            "parallel_makespan_minutes": single_printer_minutes,
            "speedup_factor": 1.0,
            "assignments": eligible_printers,
            "unassigned_plates": [pl.get("plate_index") for pl in plates],
        }

    # LPT-Zuweisung: jede Bauplatte bekommt den geeigneten Drucker mit der aktuell geringsten Gesamtlaufzeit
    sorted_plates = sorted(plates, key=lambda pl: float(pl.get("estimated_print_minutes", 0.0)), reverse=True)
    for pl in sorted_plates:
        target = min(
            eligible_printers,
            key=lambda ep: (ep["total_assigned_minutes"], -ep["fitness_score"]),
        )
        pl_min = float(pl.get("estimated_print_minutes", 0.0))
        pl_grams = float(pl.get("total_filament_grams", 0.0))
        target["assigned_plates"].append(
            {
                "plate_index": pl.get("plate_index"),
                "instance_count": pl.get("instance_count", 0),
                "estimated_print_minutes": round(pl_min, 2),
                "total_filament_grams": round(pl_grams, 2),
            }
        )
        target["total_assigned_minutes"] = round(target["total_assigned_minutes"] + pl_min, 2)
        target["total_assigned_grams"] = round(target["total_assigned_grams"] + pl_grams, 2)

    active_assignments = [ep for ep in eligible_printers if ep["assigned_plates"]]
    makespan = round(max((ep["total_assigned_minutes"] for ep in active_assignments), default=0.0), 2)
    speedup = round(single_printer_minutes / makespan, 2) if makespan > 0 else 1.0

    return {
        "can_dispatch_parallel": True,
        "eligible_printer_count": len(eligible_printers),
        "printers_used": len(active_assignments),
        "total_plates": len(plates),
        "single_printer_minutes": single_printer_minutes,
        "parallel_makespan_minutes": makespan,
        "speedup_factor": speedup,
        "assignments": active_assignments,
        "unassigned_plates": [],
    }

"""API routes for local slicer presets (imported from OrcaSlicer, etc.)."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.local_preset import LocalPreset
from backend.app.models.user import User
from backend.app.schemas.local_preset import (
    ImportResponse,
    LocalPresetCreate,
    LocalPresetDetail,
    LocalPresetResponse,
    LocalPresetsResponse,
    LocalPresetUpdate,
)
from backend.app.services.orca_profiles import (
    extract_core_fields,
    get_cache_status,
    import_orca_file,
    reclassify_presets,
    refresh_base_cache,
    resolve_preset,
)
from backend.app.utils.upload_limits import MAX_SMALL_FILE_UPLOAD_BYTES, read_upload_limited

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-presets", tags=["Local Presets"])


@router.get("/", response_model=LocalPresetsResponse)
async def list_local_presets(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
    db: AsyncSession = Depends(get_db),
):
    """List all local presets grouped by type."""
    result = await db.execute(select(LocalPreset).order_by(LocalPreset.name))
    presets = result.scalars().all()

    grouped = LocalPresetsResponse()
    for p in presets:
        resp = LocalPresetResponse.model_validate(p)
        if p.preset_type == "filament":
            grouped.filament.append(resp)
        elif p.preset_type == "printer":
            grouped.printer.append(resp)
        elif p.preset_type == "process":
            grouped.process.append(resp)

    return grouped


@router.get("/templates")
async def get_preset_templates(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    """Liefert Basis-Vorlagen fuer die Erstellung von Filament- und Prozess-Profilen."""
    return {
        "filament": [
            {
                "id": "tpl_pla",
                "name": "Generic PLA",
                "filament_type": "PLA",
                "filament_vendor": "Generic",
                "default_filament_colour": "#16A34A",
                "setting": {
                    "type": "filament",
                    "name": "Generic PLA",
                    "from": "system",
                    "filament_type": ["PLA"],
                    "filament_vendor": ["Generic"],
                    "default_filament_colour": ["#16A34A"],
                    "nozzle_temperature": ["220"],
                    "nozzle_temperature_initial_layer": ["220"],
                    "nozzle_temperature_range_low": ["190"],
                    "nozzle_temperature_range_high": ["240"],
                    "hot_plate_temp": ["55"],
                    "hot_plate_temp_initial_layer": ["55"],
                    "filament_max_volumetric_speed": ["15"],
                    "filament_density": ["1.24"],
                    "filament_cost": ["20"],
                },
            },
            {
                "id": "tpl_petg",
                "name": "Generic PETG",
                "filament_type": "PETG",
                "filament_vendor": "Generic",
                "default_filament_colour": "#2563EB",
                "setting": {
                    "type": "filament",
                    "name": "Generic PETG",
                    "from": "system",
                    "filament_type": ["PETG"],
                    "filament_vendor": ["Generic"],
                    "default_filament_colour": ["#2563EB"],
                    "nozzle_temperature": ["255"],
                    "nozzle_temperature_initial_layer": ["255"],
                    "nozzle_temperature_range_low": ["230"],
                    "nozzle_temperature_range_high": ["270"],
                    "hot_plate_temp": ["70"],
                    "hot_plate_temp_initial_layer": ["70"],
                    "filament_max_volumetric_speed": ["12"],
                    "filament_density": ["1.27"],
                    "filament_cost": ["22"],
                },
            },
            {
                "id": "tpl_abs",
                "name": "Generic ABS",
                "filament_type": "ABS",
                "filament_vendor": "Generic",
                "default_filament_colour": "#EA580C",
                "setting": {
                    "type": "filament",
                    "name": "Generic ABS",
                    "from": "system",
                    "filament_type": ["ABS"],
                    "filament_vendor": ["Generic"],
                    "default_filament_colour": ["#EA580C"],
                    "nozzle_temperature": ["270"],
                    "nozzle_temperature_initial_layer": ["270"],
                    "nozzle_temperature_range_low": ["240"],
                    "nozzle_temperature_range_high": ["280"],
                    "hot_plate_temp": ["90"],
                    "hot_plate_temp_initial_layer": ["90"],
                    "filament_max_volumetric_speed": ["14"],
                    "filament_density": ["1.06"],
                    "filament_cost": ["24"],
                },
            },
            {
                "id": "tpl_tpu",
                "name": "Generic TPU 95A",
                "filament_type": "TPU",
                "filament_vendor": "Generic",
                "default_filament_colour": "#9333EA",
                "setting": {
                    "type": "filament",
                    "name": "Generic TPU 95A",
                    "from": "system",
                    "filament_type": ["TPU"],
                    "filament_vendor": ["Generic"],
                    "default_filament_colour": ["#9333EA"],
                    "nozzle_temperature": ["230"],
                    "nozzle_temperature_initial_layer": ["230"],
                    "nozzle_temperature_range_low": ["210"],
                    "nozzle_temperature_range_high": ["250"],
                    "hot_plate_temp": ["45"],
                    "hot_plate_temp_initial_layer": ["45"],
                    "filament_max_volumetric_speed": ["3.5"],
                    "filament_density": ["1.22"],
                    "filament_cost": ["35"],
                },
            },
        ],
        "process": [
            {
                "id": "tpl_proc_standard",
                "name": "0.20mm Standard",
                "setting": {
                    "type": "process",
                    "name": "0.20mm Standard",
                    "from": "system",
                    "layer_height": "0.2",
                    "initial_layer_print_height": "0.2",
                    "wall_loops": "2",
                    "sparse_infill_density": "15%",
                    "sparse_infill_pattern": "grid",
                    "enable_support": "0",
                    "tree_support_wall_count": "0",
                    "top_shell_layers": "4",
                    "bottom_shell_layers": "3",
                    "outer_wall_speed": "200",
                    "inner_wall_speed": "300",
                    "sparse_infill_speed": "300",
                },
            },
            {
                "id": "tpl_proc_fine",
                "name": "0.12mm Fein",
                "setting": {
                    "type": "process",
                    "name": "0.12mm Fein",
                    "from": "system",
                    "layer_height": "0.12",
                    "initial_layer_print_height": "0.2",
                    "wall_loops": "3",
                    "sparse_infill_density": "20%",
                    "sparse_infill_pattern": "gyroid",
                    "enable_support": "0",
                    "tree_support_wall_count": "0",
                    "top_shell_layers": "5",
                    "bottom_shell_layers": "4",
                    "outer_wall_speed": "120",
                    "inner_wall_speed": "200",
                    "sparse_infill_speed": "200",
                },
            },
            {
                "id": "tpl_proc_draft",
                "name": "0.28mm Schnell",
                "setting": {
                    "type": "process",
                    "name": "0.28mm Schnell",
                    "from": "system",
                    "layer_height": "0.28",
                    "initial_layer_print_height": "0.24",
                    "wall_loops": "2",
                    "sparse_infill_density": "12%",
                    "sparse_infill_pattern": "grid",
                    "enable_support": "0",
                    "tree_support_wall_count": "0",
                    "top_shell_layers": "3",
                    "bottom_shell_layers": "3",
                    "outer_wall_speed": "250",
                    "inner_wall_speed": "350",
                    "sparse_infill_speed": "350",
                },
            },
            {
                "id": "tpl_proc_strength",
                "name": "0.20mm Stabil / Fest",
                "setting": {
                    "type": "process",
                    "name": "0.20mm Stabil / Fest",
                    "from": "system",
                    "layer_height": "0.2",
                    "initial_layer_print_height": "0.2",
                    "wall_loops": "5",
                    "sparse_infill_density": "40%",
                    "sparse_infill_pattern": "gyroid",
                    "enable_support": "0",
                    "tree_support_wall_count": "0",
                    "top_shell_layers": "6",
                    "bottom_shell_layers": "5",
                    "outer_wall_speed": "150",
                    "inner_wall_speed": "250",
                    "sparse_infill_speed": "250",
                },
            },
        ],
    }


@router.get("/{preset_id}", response_model=LocalPresetDetail)
async def get_local_preset(
    preset_id: int,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Get full detail for a local preset including the setting JSON."""
    result = await db.execute(select(LocalPreset).where(LocalPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(404, "Local preset not found")

    data = LocalPresetResponse.model_validate(preset).model_dump()
    try:
        data["setting"] = json.loads(preset.setting)
    except Exception:
        data["setting"] = {}

    return LocalPresetDetail(**data)


@router.post("/{preset_id}/clone", response_model=LocalPresetResponse)
async def clone_local_preset(
    preset_id: int,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Dupliziert ein bestehendes lokales Profil mit fortlaufendem Namen."""
    result = await db.execute(select(LocalPreset).where(LocalPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(404, "Local preset not found")

    clone_name = f"{preset.name} (Kopie)"
    counter = 1
    while True:
        existing = await db.execute(select(LocalPreset).where(LocalPreset.name == clone_name))
        if not existing.scalar_one_or_none():
            break
        counter += 1
        clone_name = f"{preset.name} (Kopie {counter})"

    cloned = LocalPreset(
        name=clone_name,
        preset_type=preset.preset_type,
        source="clone",
        setting=preset.setting,
        filament_type=preset.filament_type,
        filament_vendor=preset.filament_vendor,
        nozzle_temp_min=preset.nozzle_temp_min,
        nozzle_temp_max=preset.nozzle_temp_max,
        pressure_advance=preset.pressure_advance,
        default_filament_colour=preset.default_filament_colour,
        filament_cost=preset.filament_cost,
        filament_density=preset.filament_density,
        compatible_printers=preset.compatible_printers,
        inherits=preset.inherits,
        version=preset.version,
    )
    db.add(cloned)
    await db.flush()
    await db.refresh(cloned)
    return LocalPresetResponse.model_validate(cloned)


@router.post("/import", response_model=ImportResponse)
async def import_presets(
    file: UploadFile,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Import presets from an OrcaSlicer export file (.json, .orca_filament, .bbscfg, .bbsflmt, .zip)."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    content = await read_upload_limited(file, MAX_SMALL_FILE_UPLOAD_BYTES)
    if not content:
        raise HTTPException(400, "Empty file")

    result = await import_orca_file(file.filename, content, db)
    return ImportResponse(**result)


@router.post("/", response_model=LocalPresetResponse)
async def create_local_preset(
    data: LocalPresetCreate,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Manually create a local preset."""
    if data.preset_type not in ("filament", "printer", "process"):
        raise HTTPException(400, "preset_type must be filament, printer, or process")

    if data.preset_type == "process" and isinstance(data.setting, dict):
        from backend.app.services.slicer_cli import sanitize_process_profile_dict

        data.setting = sanitize_process_profile_dict(data.setting)

    # Extract core fields
    core = extract_core_fields(data.setting)

    preset = LocalPreset(
        name=data.name,
        preset_type=data.preset_type,
        source="manual",
        setting=json.dumps(data.setting),
        **core,
    )
    db.add(preset)
    await db.flush()
    await db.refresh(preset)
    return LocalPresetResponse.model_validate(preset)


@router.put("/{preset_id}", response_model=LocalPresetResponse)
async def update_local_preset(
    preset_id: int,
    data: LocalPresetUpdate,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Update a local preset's name or settings."""
    result = await db.execute(select(LocalPreset).where(LocalPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(404, "Local preset not found")

    if data.name is not None:
        preset.name = data.name

    if data.setting is not None:
        if preset.preset_type == "process" and isinstance(data.setting, dict):
            from backend.app.services.slicer_cli import sanitize_process_profile_dict

            data.setting = sanitize_process_profile_dict(data.setting)

        # Re-resolve and extract core fields
        resolved = await resolve_preset(data.setting, preset.preset_type, db)
        core = extract_core_fields(resolved)
        preset.setting = json.dumps(resolved)
        preset.filament_type = core.get("filament_type")
        preset.filament_vendor = core.get("filament_vendor")
        preset.nozzle_temp_min = core.get("nozzle_temp_min")
        preset.nozzle_temp_max = core.get("nozzle_temp_max")
        preset.pressure_advance = core.get("pressure_advance")
        preset.default_filament_colour = core.get("default_filament_colour")
        preset.filament_cost = core.get("filament_cost")
        preset.filament_density = core.get("filament_density")
        preset.compatible_printers = core.get("compatible_printers")

    await db.flush()
    await db.refresh(preset)
    return LocalPresetResponse.model_validate(preset)


@router.delete("/{preset_id}")
async def delete_local_preset(
    preset_id: int,
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Delete a local preset."""
    result = await db.execute(select(LocalPreset).where(LocalPreset.id == preset_id))
    preset = result.scalar_one_or_none()
    if not preset:
        raise HTTPException(404, "Local preset not found")

    await db.delete(preset)
    return {"success": True}


@router.get("/base-cache/status")
async def base_cache_status(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
    db: AsyncSession = Depends(get_db),
):
    """Get the status of the OrcaSlicer base profile cache."""
    return await get_cache_status(db)


@router.post("/base-cache/refresh")
async def refresh_cache(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Force refresh all cached base profiles from GitHub."""
    return await refresh_base_cache(db)


@router.post("/reclassify")
async def reclassify(
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
    db: AsyncSession = Depends(get_db),
):
    """Re-evaluate preset types for all local presets using the improved heuristic."""
    return await reclassify_presets(db)

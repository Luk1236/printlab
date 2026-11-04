// Aus types.ts ausgelagerte Typen: Warteschlange, Batches, K-Profile und Filament-Wahl.

import type { CalibrationMode } from './types_slicer';

export interface PrintQueueItem {
  id: number;
  printer_id: number | null;  // null = unassigned
  target_model: string | null;  // Target printer model for model-based assignment
  target_location: string | null;  // Target location filter for model-based assignment
  required_filament_types: string[] | null;  // Required filament types for model-based assignment
  waiting_reason: string | null;  // Why this job hasn't started yet (empty once it can)
  // Cross-model alternatives (#671), in priority order. Empty for ordinary
  // items. Present until dispatch resolves one, after which library_file_id and
  // target_model name the candidate that actually ran.
  variants?: Array<{
    library_file_id: number;
    filename: string;
    target_model: string;
    position: number;
  }>;
  // Either archive_id OR library_file_id must be set (archive created at print start)
  archive_id: number | null;
  library_file_id: number | null;
  cost_center_id: number | null;
  estimated_cost: number | null;
  position: number;
  scheduled_time: string | null;
  require_previous_success: boolean;
  auto_off_after: boolean;
  manual_start: boolean;  // Requires manual trigger to start (staged)
  priority?: number;  // 0 niedrig, 1 normal, 2 eilig
  due_at?: string | null;  // optionaler Liefertermin (nur Warnung)
  due_warning?: 'overdue' | 'too_late' | null;
  // Set by the dispatch scheduler when the assigned spool can't satisfy
  // any required slot's grams (#1496). Surfaced on the queue row as a
  // "filament short" badge; cleared on a successful ▶ click (live recheck).
  filament_short: boolean;
  // Persistent "Print Anyway" acknowledgement — once true the scheduler
  // skips the deficit check for this item (#1698-followup). Set by the
  // start route when skip_filament_check=true, or at queue creation if
  // PrintModal's deficit warning was acknowledged.
  skip_filament_check: boolean;
  // True when the source archive carries the slicer's own live-resolved
  // AMS-slot pick (extra_data.slicer_ams_mapping) — a reprint reuses that
  // exact physical spool instead of re-deriving one from type/color.
  archive_has_slicer_ams_mapping: boolean;
  ams_mapping: number[] | null;  // AMS slot mapping for multi-color prints
  filament_overrides: Array<{ slot_id: number; type: string; color: string; color_name?: string; tray_info_idx?: string; force_color_match?: boolean }> | null;  // Filament overrides for model-based assignment
  plate_id: number | null;  // Plate ID for multi-plate 3MF files
  // Print options
  bed_levelling: CalibrationMode;
  flow_cali: CalibrationMode;
  vibration_cali: boolean;
  layer_inspect: boolean;
  timelapse: boolean;
  use_ams: boolean;
  nozzle_offset_cali: CalibrationMode;
  // Ask for a post-print outcome verdict when this job completes (#1898)
  confirm_outcome: boolean;
  preheat_override: 'inherit' | 'on' | 'off';
  preheat_chamber_target_override: number | null;
  status: 'pending' | 'printing' | 'completed' | 'failed' | 'skipped' | 'cancelled';
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
  archive_name?: string | null;
  archive_thumbnail?: string | null;
  // True when the linked archive has been soft-deleted; archive_name /
  // archive_thumbnail / downstream metadata are left null in that case so
  // the UI doesn't 404-storm the now-missing endpoints (#1348 follow-up).
  archive_deleted?: boolean;
  library_file_name?: string | null;
  library_file_thumbnail?: string | null;
  printer_name?: string | null;
  print_time_seconds?: number | null;  // Estimated print time from archive or library file
  filament_used_grams?: number | null;  // Estimated print weight from archive or library file
  filament_type?: string | null;  // e.g. "PLA", "PETG"
  filament_color?: string | null;  // Hex RGBA from the slicer
  bed_type?: string | null;  // Build plate type for this print (per-plate accurate, #1281)
  // User tracking (Issue #206)
  created_by_id?: number | null;
  created_by_username?: string | null;
  // Batch grouping
  batch_id?: number | null;
  batch_name?: string | null;
  // Shortest-job-first scheduling
  been_jumped?: boolean;
  // Auto-print G-code injection
  gcode_injection?: boolean;
  cleanup_library_after_dispatch?: boolean;
  /** Which rack position each filament group prints from, on a nozzle-rack
   *  machine (#1784): `{ [group_id]: 1-based position }`. Re-checked against
   *  the live rack at dispatch; omit to have the dispatcher assign them. */
  nozzle_rack_choice?: Record<number, number> | null;
}
export interface PrintBatchPlateTarget {
  plate_id: number | null;
  plate_name?: string | null;
  quantity_target: number;
  sort_order?: number;
}
export interface PrintBatchPlateProgress {
  plate_id: number | null;
  plate_name: string | null;
  quantity_target: number;
  dispatched: number;
  remaining: number;
  pending_count: number;
  printing_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  skipped_count: number;
  /** Measured from finished runs; null until one has produced a cost. */
  actual_cost: number | null;
  estimated_remaining_cost: number | null;
  filament_used_grams: number | null;
  print_time_seconds: number;
  /** False when this plate owes runs but has no queue item left to clone
   *  their configuration from, so queueing it could only fail (#2960). */
  can_dispatch: boolean;
}
export interface PrintBatch {
  id: number;
  name: string;
  archive_id: number | null;
  library_file_id: number | null;
  quantity: number;
  status: string;
  created_at: string;
  completed_at: string | null;
  created_by_id: number | null;
  created_by_username: string | null;
  project_id: number | null;
  due_date: string | null;
  notes: string | null;
  /** Set when an integration (e.g. a shop connector) created the batch. */
  external_source: string | null;
  external_ref: string | null;
  pending_count: number;
  printing_count: number;
  completed_count: number;
  failed_count: number;
  cancelled_count: number;
  skipped_count: number;
  /** False for batches created before per-plate targets existed (#342):
   *  they report progress but owe nothing and cannot be dispatched from. */
  has_targets: boolean;
  target_count: number;
  remaining_count: number;
  /** Of remaining_count, how many runs can actually be queued (#2960). */
  dispatchable_count: number;
  actual_cost: number | null;
  estimated_remaining_cost: number | null;
  filament_used_grams: number | null;
  print_time_seconds: number;
  plates: PrintBatchPlateProgress[];
}
export interface PrintQueueItemCreate {
  printer_id?: number | null;  // null = unassigned
  target_model?: string | null;  // Target printer model (mutually exclusive with printer_id)
  target_location?: string | null;  // Target location filter (only used with target_model)
  filament_overrides?: Array<{ slot_id: number; type: string; color: string; color_name?: string; tray_info_idx?: string; force_color_match?: boolean }> | null;
  archive_id?: number | null;
  library_file_id?: number | null;
  scheduled_time?: string | null;
  require_previous_success?: boolean;
  auto_off_after?: boolean;
  manual_start?: boolean;  // Requires manual trigger to start (staged)
  priority?: number;
  due_at?: string | null;
  insert_at_top?: boolean;  // Insert ahead of other pending items (one queue order across all printers, #3200)
  insert_position?: number | null;  // 1-indexed insertion position for priority queueing
  // PrintModal "Print Anyway" on the deficit warning — persisted so the
  // scheduler doesn't immediately re-flag this item (#1698-followup).
  skip_filament_check?: boolean;
  ams_mapping?: number[] | null;  // AMS slot mapping for multi-color prints
  plate_id?: number | null;  // Plate ID for multi-plate 3MF files
  // Print options
  bed_levelling?: CalibrationMode;
  flow_cali?: CalibrationMode;
  vibration_cali?: boolean;
  layer_inspect?: boolean;
  timelapse?: boolean;
  use_ams?: boolean;
  nozzle_offset_cali?: CalibrationMode;
  // Ask for a post-print outcome verdict when this job completes (#1898)
  confirm_outcome?: boolean;
  preheat_override?: 'inherit' | 'on' | 'off';
  preheat_chamber_target_override?: number | null;
  // Auto-print G-code injection
  gcode_injection?: boolean;
  // Batch: create multiple copies (creates a batch if > 1)
  quantity?: number;
  // Existing batch to add this item into (multi-plate auto-batch flow).
  batch_id?: number | null;
  // Project to associate the resulting archive with
  project_id?: number;
  cost_center_id?: number | null;
  estimated_cost?: number | null;
  // Delete transient uploaded library file after scheduler creates the archive
  cleanup_library_after_dispatch?: boolean;
  // Cross-model alternatives (#671): several sliced files, one job, whichever
  // printer frees up first. Mutually exclusive with printer_id (a named printer
  // defeats the point) and with archive_id/library_file_id (these ARE the files).
  // Order is priority — index 0 wins when several printers are idle at once.
  variants?: QueueVariantCreate[];
  /** Which rack position each filament group prints from, on a nozzle-rack
   *  machine (#1784): `{ [group_id]: 1-based position }`. Re-checked against
   *  the live rack at dispatch; omit to have the dispatcher assign them. */
  nozzle_rack_choice?: Record<number, number> | null;
}
export interface QueueVariantCreate {
  library_file_id: number;
  /** Read from the file's own sliced_for_model unless it declares none. */
  target_model?: string | null;
  plate_id?: number | null;
  ams_mapping?: number[] | null;
  nozzle_mapping?: number[] | null;
  filament_overrides?: Array<{ slot_id: number; type: string; color: string; color_name?: string; tray_info_idx?: string; force_color_match?: boolean }> | null;
}
export interface PrintBatchCreate {
  name: string;
  archive_id?: number | null;
  library_file_id?: number | null;
  /** When set, the listed pending items are assigned to the new batch
   *  (manual "Group as batch"). When omitted/empty, an empty batch is
   *  returned so the client can pass batch_id on subsequent addToQueue calls. */
  item_ids?: number[];
  /** Per-plate targets. Omitting them creates a plain grouping batch. */
  plates?: PrintBatchPlateTarget[];
  project_id?: number | null;
  due_date?: string | null;
  notes?: string | null;
}
export interface PrintBatchUpdate {
  name?: string;
  status?: 'active' | 'cancelled';
  /** Replaces the full target set — a plate omitted here is removed. */
  plates?: PrintBatchPlateTarget[];
  project_id?: number | null;
  due_date?: string | null;
  notes?: string | null;
}
export interface PrintBatchDispatchRequest {
  plate_id?: number | null;
  only_plate?: boolean;
  /** Cap on items created across all plates; omit to queue everything owed. */
  limit?: number;
}
export interface PrintQueueItemUpdate {
  printer_id?: number | null;  // null = unassign
  target_model?: string | null;  // Target printer model (mutually exclusive with printer_id)
  target_location?: string | null;  // Target location filter (only used with target_model)
  filament_overrides?: Array<{ slot_id: number; type: string; color: string; color_name?: string; tray_info_idx?: string; force_color_match?: boolean }> | null;
  position?: number;
  scheduled_time?: string | null;
  require_previous_success?: boolean;
  auto_off_after?: boolean;
  manual_start?: boolean;
  priority?: number;
  due_at?: string | null;
  ams_mapping?: number[];
  plate_id?: number | null;  // Plate ID for multi-plate 3MF files
  // Print options
  bed_levelling?: CalibrationMode;
  flow_cali?: CalibrationMode;
  vibration_cali?: boolean;
  layer_inspect?: boolean;
  timelapse?: boolean;
  use_ams?: boolean;
  nozzle_offset_cali?: CalibrationMode;
  // Ask for a post-print outcome verdict when this job completes (#1898)
  confirm_outcome?: boolean;
  preheat_override?: 'inherit' | 'on' | 'off';
  preheat_chamber_target_override?: number | null;
  // Auto-print G-code injection
  gcode_injection?: boolean;
  cost_center_id?: number | null;
  estimated_cost?: number | null;
  /** Which rack position each filament group prints from, on a nozzle-rack
   *  machine (#1784): `{ [group_id]: 1-based position }`. Re-checked against
   *  the live rack at dispatch; omit to have the dispatcher assign them. */
  nozzle_rack_choice?: Record<number, number> | null;
}
export interface PrintQueueBulkUpdate {
  item_ids: number[];
  printer_id?: number | null;
  scheduled_time?: string | null;
  require_previous_success?: boolean;
  auto_off_after?: boolean;
  manual_start?: boolean;
  priority?: number;
  due_at?: string | null;
  // Print options
  bed_levelling?: CalibrationMode;
  flow_cali?: CalibrationMode;
  vibration_cali?: boolean;
  layer_inspect?: boolean;
  timelapse?: boolean;
  use_ams?: boolean;
  nozzle_offset_cali?: CalibrationMode;
  // Ask for a post-print outcome verdict when this job completes (#1898)
  confirm_outcome?: boolean;
  preheat_override?: 'inherit' | 'on' | 'off';
  preheat_chamber_target_override?: number | null;
  // Auto-print G-code injection
  gcode_injection?: boolean;
  cost_center_id?: number | null;
  estimated_cost?: number | null;
}
export interface PrintQueueBulkUpdateResponse {
  updated_count: number;
  skipped_count: number;
  message: string;
}
export interface MQTTLogEntry {
  timestamp: string;
  topic: string;
  direction: 'in' | 'out';
  payload: Record<string, unknown>;
}
export interface MQTTLogsResponse {
  logging_enabled: boolean;
  logs: MQTTLogEntry[];
}
export interface KProfile {
  slot_id: number;
  extruder_id: number;
  nozzle_id: string;
  nozzle_diameter: string;
  filament_id: string;
  name: string;
  k_value: string;
  n_coef: string;
  ams_id: number;
  tray_id: number;
  setting_id: string | null;
}
export interface KProfileCreate {
  slot_id?: number;  // Storage slot, 0 for new profiles
  extruder_id?: number;
  nozzle_id: string;
  nozzle_diameter: string;
  filament_id: string;
  name: string;
  k_value: string;
  n_coef?: string;
  ams_id?: number;
  tray_id?: number;
  setting_id?: string | null;
}
export interface KProfileDelete {
  slot_id: number;  // cali_idx - calibration index to delete
  extruder_id: number;
  nozzle_id: string;  // e.g., "HH00-0.4"
  nozzle_diameter: string;  // e.g., "0.4"
  filament_id: string;  // Bambu filament identifier
  setting_id?: string | null;  // Setting ID (for X1C series)
}
export interface KProfilesResponse {
  profiles: KProfile[];
  nozzle_diameter: string;
}
export interface KProfileNote {
  setting_id: string;
  note: string;
}
export interface KProfileNotesResponse {
  notes: Record<string, string>;  // setting_id -> note
}
export interface SlotPresetMapping {
  ams_id: number;
  tray_id: number;
  preset_id: string;
  preset_name: string;
  // Filament id the slot was configured with alongside this preset; null for
  // rows that predate it or whose writer did not know it (#3216).
  tray_info_idx?: string | null;
}
export interface Filament {
  id: number;
  name: string;
  type: string;  // PLA, PETG, ABS, etc.
  brand: string | null;
  color: string | null;
  color_hex: string | null;
  cost_per_kg: number;
  spool_weight_g: number;
  currency: string;
  density: number | null;
  print_temp_min: number | null;
  print_temp_max: number | null;
  bed_temp_min: number | null;
  bed_temp_max: number | null;
  created_at: string;
  updated_at: string;
}

// Aus types.ts ausgelagerte Typen: Einstellungen (AppSettings), Slicer-Profile, -Pipelines und Smart Plug/Home Assistant.

export interface APIKey {
  id: number;
  name: string;
  key_prefix: string;
  user_id: number | null;  // Owner; null on legacy keys created before per-user ownership (#1182)
  can_queue: boolean;
  can_control_printer: boolean;
  can_read_status: boolean;
  can_manage_library: boolean;
  can_manage_inventory: boolean;
  can_manage_maintenance: boolean;
  can_manage_archives: boolean;
  can_manage_projects: boolean;
  can_access_cloud: boolean;
  can_update_energy_cost: boolean;
  can_send_notifications: boolean;
  printer_ids: number[] | null;
  enabled: boolean;
  last_used: string | null;
  created_at: string;
  expires_at: string | null;
}
export interface APIKeyCreate {
  name: string;
  can_queue?: boolean;
  can_control_printer?: boolean;
  can_read_status?: boolean;
  can_manage_library?: boolean;
  can_manage_inventory?: boolean;
  can_manage_maintenance?: boolean;
  can_manage_archives?: boolean;
  can_manage_projects?: boolean;
  can_access_cloud?: boolean;
  can_update_energy_cost?: boolean;
  can_send_notifications?: boolean;
  printer_ids?: number[] | null;
  expires_at?: string | null;
}
export interface APIKeyCreateResponse extends APIKey {
  key: string;  // Full key, only shown on creation
}
export interface APIKeyUpdate {
  name?: string;
  can_queue?: boolean;
  can_control_printer?: boolean;
  can_read_status?: boolean;
  can_manage_library?: boolean;
  can_manage_inventory?: boolean;
  can_manage_maintenance?: boolean;
  can_manage_archives?: boolean;
  can_manage_projects?: boolean;
  can_access_cloud?: boolean;
  can_update_energy_cost?: boolean;
  can_send_notifications?: boolean;
  printer_ids?: number[] | null;
  enabled?: boolean;
  expires_at?: string | null;
}
export type CalibrationMode = 'off' | 'on' | 'auto';
export interface AppSettings {
  auto_archive: boolean;
  save_thumbnails: boolean;
  capture_finish_photo: boolean;
  finish_photo_restore_plate: boolean;
  default_filament_cost: number;
  currency: string;
  energy_cost_per_kwh: number;
  printer_power_watts: number;
  labor_rate_per_hour: number;
  quote_markup_percent: number;
  energy_tracking_mode: 'print' | 'total';
  check_updates: boolean;
  check_printer_firmware: boolean;
  include_beta_updates: boolean;
  // Announcements from the PrintLab maintainers (a signed file on GitHub).
  announcements_enabled?: boolean;
  announcements_all_users?: boolean;
  // #1589: false hides the local username/password form on the login page;
  // PRINTLAB_LOCAL_LOGIN=true on the server flips the reported value back to
  // true so the env-var recovery path is visible to the SPA.
  local_login_enabled: boolean;
  language: string;
  notification_language: string;
  // AMS threshold settings
  ams_humidity_good: number;  // <= this is green
  ams_humidity_fair: number;  // <= this is orange, > is red
  ams_temp_good: number;      // <= this is green/blue
  ams_temp_fair: number;      // <= this is orange, > is red
  // Separate from the display band (#2905). null = unset, which the backend
  // resolves to ams_temp_fair so existing installs are unaffected.
  ams_temp_alarm: number | null;
  ams_history_retention_days: number;  // days to keep AMS sensor history
  // Queue auto-drying settings
  queue_drying_enabled: boolean;  // Auto-dry AMS between queued prints
  queue_drying_block: boolean;  // Block queue until drying completes
  ambient_drying_enabled: boolean;  // Auto-dry idle printers based on humidity regardless of queue
  ambient_drying_sustained_minutes: number;  // Minutes humidity must stay above threshold before ambient auto-dry starts (0 = instant)
  print_drying_enabled: boolean;  // Continue drying while a print is running on capable hardware
  drying_presets: string;  // JSON blob of drying presets per filament type
  ams_humidity_thresholds: string;  // JSON blob of per-filament humidity thresholds (#1605)
  gcode_snippets: string;  // JSON: per-model G-code injection snippets
  // Scheduled local backup
  local_backup_enabled: boolean;
  local_backup_schedule: string;
  local_backup_time: string;
  local_backup_retention: number;
  local_backup_path: string;
  // Print modal settings
  per_printer_mapping_expanded: boolean;  // Whether custom mapping is expanded by default in print modal
  // Date/time format settings
  date_format: 'system' | 'us' | 'eu' | 'iso';
  time_format: 'system' | '12h' | '24h';
  // Filament tracking
  disable_filament_warnings: boolean;  // Disable filament warnings (print insufficiency and assignment mismatch)
  prefer_lowest_filament: boolean;  // When multiple spools match, prefer lowest remaining filament
  spoolman_enabled: boolean;  // True when the user has switched filament tracking to Spoolman; backend includes this in the /settings/ response even though earlier consumers read it from the dedicated /settings/spoolman endpoint as a string
  auto_add_unknown_rfid: boolean;  // When false, the backend skips auto-creating inventory spools for unknown RFID tags and instead broadcasts an unknown_tag event for the confirmation modal
  spoolman_url: string;
  // Default printer
  default_printer_id: number | null;
  pipeline_max_copies: number;
  // Dark mode theme settings
  dark_style: 'classic' | 'glow' | 'vibrant';
  dark_background: 'neutral' | 'warm' | 'cool' | 'oled' | 'slate' | 'forest';
  dark_accent: 'green' | 'teal' | 'blue' | 'orange' | 'purple' | 'red';
  // Light mode theme settings
  light_style: 'classic' | 'glow' | 'vibrant';
  light_background: 'neutral' | 'warm' | 'cool';
  light_accent: 'green' | 'teal' | 'blue' | 'orange' | 'purple' | 'red';
  // FTP retry settings
  ftp_retry_enabled: boolean;
  ftp_retry_count: number;
  ftp_retry_delay: number;
  ftp_timeout: number;
  // MQTT relay settings
  mqtt_enabled: boolean;
  mqtt_broker: string;
  mqtt_port: number;
  mqtt_username: string;
  mqtt_password: string;
  mqtt_topic_prefix: string;
  mqtt_use_tls: boolean;
  // External URL for notifications
  external_url: string;
  // Directory holding docker-compose.yml, shown in the update instructions (#2664)
  docker_compose_dir: string;
  // Home Assistant integration
  ha_enabled: boolean;
  ha_url: string;
  ha_token: string;
  ha_url_from_env: boolean;
  ha_token_from_env: boolean;
  ha_env_managed: boolean;
  // File Manager / Library settings
  library_archive_mode: 'always' | 'never' | 'ask';
  library_disk_warning_gb: number;
  // Camera view settings
  camera_view_mode: 'window' | 'embedded';
  // Preferred slicer (server-side API / sidecar)
  preferred_slicer: 'bambu_studio' | 'orcaslicer';
  // Desktop "Open in Slicer" override (#1329). Null inherits from
  // preferred_slicer so existing installs behave identically.
  open_in_slicer: 'bambu_studio' | 'orcaslicer' | null;
  // Where slicing runs, independent of which slicer binary the sidecar drives.
  // Only 'sidecar' is implemented today; see lib/sliceEngines.ts.
  slice_engine: 'sidecar' | 'browser';
  // Use the slicer-API sidecar for slicing (in-app modal) vs desktop URI scheme
  use_slicer_api: boolean;
  // Per-install sidecar URLs. Empty string falls back to the env defaults.
  orcaslicer_api_url: string;
  bambu_studio_api_url: string;
  // Minutes of silence from the sidecar before a slice is abandoned. Bounds
  // stalls, not total slicing time — a model that keeps reporting progress
  // runs to completion however long it takes.
  slicer_stall_timeout_minutes: number;
  // Prometheus metrics
  prometheus_enabled: boolean;
  prometheus_token: string;
  // Bed cooled threshold
  bed_cooled_threshold: number;
  // Inventory low stock threshold
  low_stock_threshold: number;
  // Session policy (#1706) — admin-set ceiling, hours, [1, 720]
  session_max_hours: number;
  // User email notifications toggle
  user_notifications_enabled: boolean;
  // Default print options
  default_bed_levelling: CalibrationMode;
  default_flow_cali: CalibrationMode;
  default_vibration_cali: boolean;
  default_layer_inspect: boolean;
  default_timelapse: boolean;
  default_nozzle_offset_cali: CalibrationMode;
  // Default for the per-job "ask for outcome afterwards" toggle (#1898)
  default_confirm_outcome: boolean;
  // Also ask for prints PrintLab archived but did not dispatch (#1898)
  confirm_outcome_external_prints: boolean;
  // Count unanswered outcome prompts as "good" when the plate is released (#1898)
  confirm_default_good_on_plate_clear: boolean;
  // Staggered batch start defaults
  stagger_group_size: number;
  stagger_interval_minutes: number;
  // Finance budget reset window
  billing_enabled: boolean;
  printer_kill_switch_enabled: boolean;
  finance_budget_reset_day: number;
  finance_budget_reset_timezone: string;
  // Plate-clear confirmation
  require_plate_clear: boolean;
  // Shortest job first scheduling
  queue_shortest_first: boolean;
  // How many printers the queue may upload to at once (#2555). 1 restores the
  // old strictly-serial behaviour, where every printer waited out every other
  // printer's transfer.
  queue_max_concurrent_uploads: number;
  // Preheat / heat-soak before queued prints (#1468). Master toggle is the
  // default for new queue items; per-item PrintQueueItem.preheat_override can
  // flip the decision per print. Chamber target derives from the loaded AMS
  // filament types via preheat_filament_targets (JSON map of type → °C, max
  // across loaded slots); the per-item override field bypasses derivation.
  preheat_enabled: boolean;
  preheat_filament_targets: string;
  preheat_max_wait_seconds: number;
  preheat_soak_seconds: number;
  queue_keep_bed_warm: boolean;
  queue_keep_warm_bed_temp: number;
  queue_keep_warm_max_minutes: number;
  // User-configurable presets for the printer-card popovers (JSON arrays of 3 ints).
  // Empty string = use built-in defaults.
  nozzle_temp_presets: string;
  bed_temp_presets: string;
  chamber_temp_presets: string;
  fan_speed_presets: string;
  // Default sidebar order (admin-set for all users)
  default_sidebar_order: string;
  // LDAP authentication
  ldap_enabled: boolean;
  ldap_server_url: string;
  ldap_bind_dn: string;
  ldap_bind_password: string;
  ldap_search_base: string;
  ldap_user_filter: string;
  ldap_security: string;
  ldap_group_mapping: string;
  ldap_auto_provision: boolean;
  ldap_default_group: string;
  obico_enabled: boolean;
  obico_ml_url: string;
  obico_ml_token: string;
  obico_sensitivity: 'low' | 'medium' | 'high';
  obico_action: 'notify' | 'pause' | 'pause_and_off';
  obico_poll_interval: number;
  obico_enabled_printers: string;
  // Inventory forecasting global lead time
  forecast_global_lead_time_days: number;
  location_sensor_poll_interval: number;
  // JSON map of sensor category → {alertAbove, alertBelow, notifyOnAlert},
  // seeding new storage-location sensor bindings. Empty = built-in defaults.
  // Server-backed so two admins seed the same alert rules and a restore
  // brings them back; see utils/locationSensorDefaults.ts.
  location_sensor_alert_defaults: string;
}
export type AppSettingsUpdate = Partial<AppSettings>;
export interface MQTTStatus {
  enabled: boolean;
  connected: boolean;
  broker: string;
  port: number;
  topic_prefix: string;
}
export interface CloudAuthStatus {
  is_authenticated: boolean;
  email: string | null;
  region?: 'global' | 'china' | null;
  /** A token is stored but Bambu no longer accepts it — tell the user why the login form is back. */
  sign_in_expired?: boolean;
}
export interface CloudLoginResponse {
  success: boolean;
  needs_verification: boolean;
  message: string;
  verification_type?: 'email' | 'totp' | null;
  tfa_key?: string | null;
  /**
   * Machine-readable cause of a failure. 'captcha' means Bambu's anti-abuse
   * layer is challenging this network and no credential will be accepted until
   * it clears — the UI must explain that in place rather than toast `message`.
   */
  reason?: 'captcha' | string | null;
}
export interface OrcaDeviceStartResponse {
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string;
  interval: number;
  expires_in: number;
}
export type OrcaDevicePollStatus =
  | 'authorization_pending'
  | 'slow_down'
  | 'access_denied'
  | 'expired_token'
  | 'complete';
export interface OrcaDevicePollResponse {
  status: OrcaDevicePollStatus;
  connected: boolean;
  email: string | null;
  user_id: string | null;
}
export interface OrcaAuthStatusResponse {
  connected: boolean;
  email: string | null;
  user_id: string | null;
}
export interface OrcaProfileMeta {
  setting_id: string;
  name: string;
  type: string;
  version: string | null;
  user_id: string | null;
  updated_time: string | null;
  is_custom: boolean;
}
export interface OrcaProfileListResponse {
  filament: OrcaProfileMeta[];
  printer: OrcaProfileMeta[];
  process: OrcaProfileMeta[];
}
export interface OrcaProfileDetail {
  setting_id: string;
  name: string;
  type: string;
  version: string | null;
  base_id: string | null;
  update_time: string | null;
  setting: Record<string, unknown>;
}
export interface MakerworldStatus {
  has_cloud_token: boolean;
  can_download: boolean;
  /** A token is stored but Bambu rejected it — downloads will fail until the user signs in again. */
  sign_in_expired?: boolean;
}
export interface MakerworldResolvedModel {
  model_id: number;
  profile_id: number | null;
  design: Record<string, unknown>;
  instances: Array<Record<string, unknown>>;
  already_imported_library_ids: number[];
}
export interface MakerworldImportResponse {
  library_file_id: number;
  filename: string;
  folder_id: number | null;
  profile_id: number | null;
  was_existing: boolean;
}
export interface MakerworldRecentImport {
  library_file_id: number;
  filename: string;
  folder_id: number | null;
  thumbnail_path: string | null;
  source_url: string | null;
  created_at: string;
}
export interface SlicerSetting {
  setting_id: string;
  name: string;
  type: string;
  version: string | null;
  user_id: string | null;
  updated_time: string | null;
  is_custom: boolean;
}
export interface SpoolCatalogEntry {
  id: number;
  name: string;
  weight: number;
  is_default: boolean;
}
export interface StorageLocation {
  id: number;
  name: string;
  identifier: string | null;
  spool_count: number;
  created_at: string;
  updated_at: string;
}
export interface ColorCatalogEntry {
  id: number;
  manufacturer: string;
  color_name: string;
  hex_color: string;
  material: string | null;
  is_default: boolean;
  // #1154: optional multi-colour gradient stops + visual effect.
  extra_colors?: string | null;
  effect_type?: string | null;
}
export interface ColorLookupResult {
  found: boolean;
  hex_color: string | null;
  material: string | null;
}
export interface SlicerSettingsResponse {
  filament: SlicerSetting[];
  printer: SlicerSetting[];
  process: SlicerSetting[];
}
export interface SlicerSettingDetail {
  message?: string | null;
  code?: string | null;
  error?: string | null;
  public: boolean;
  version?: string | null;
  type: string;
  name: string;
  update_time?: string | null;
  nickname?: string | null;
  base_id?: string | null;
  setting: Record<string, unknown>;
  filament_id?: string | null;
  setting_id?: string | null;
}
export interface SlicerSettingCreate {
  type: string;  // 'filament', 'print', or 'printer'
  name: string;
  base_id: string;
  setting: Record<string, unknown>;
}
export interface SlicerSettingUpdate {
  name?: string;
  setting?: Record<string, unknown>;
}
export interface SlicerSettingDeleteResponse {
  success: boolean;
  message: string;
}
export interface BuiltinFilament {
  filament_id: string;
  name: string;
}
export type PresetSource = 'orca_cloud' | 'cloud' | 'local' | 'standard';
export interface PresetRef {
  source: PresetSource;
  id: string;
}
export type SlicerPresetValuesReason =
  | 'ok'
  | 'sidecar_outdated'
  | 'sidecar_unavailable'
  | 'not_configured'
  | 'preset_unresolved';
export interface SlicerPresetValues {
  /** False when the sidecar could not supply values; `values` is then empty. */
  resolved: boolean;
  /** Flattened key -> value map, in the string forms a process preset stores. */
  values: Record<string, string | string[]>;
  reason: SlicerPresetValuesReason;
}
export interface SliceRequest {
  printer_preset_id?: number;
  process_preset_id?: number;
  filament_preset_id?: number;
  printer_preset?: PresetRef;
  process_preset?: PresetRef;
  filament_preset?: PresetRef;
  // Multi-color: one PresetRef per plate slot, in plate order. Always
  // preferred over the singular `filament_preset` when both are sent; the
  // backend validator promotes a singular into a one-element list when this
  // is omitted, so legacy single-color clients keep working unchanged.
  filament_presets?: PresetRef[];
  // Per-slot filament colour as `#RRGGBB` / `#RRGGBBAA`, same plate order as
  // `filament_presets` (#2977). Neither slicer stores a colour on a filament
  // *preset* -- it is a per-project property -- so without this every sliced
  // file records the CLI's built-in #00AE42 and the print dialog reports a
  // colour mismatch against whatever is loaded in the AMS. An empty string in
  // any position hands that slot back to the backend's fallback chain (the
  // preset's own default_filament_colour, then the source plate's colour).
  filament_colours?: string[];
  plate?: number;
  export_3mf?: boolean;
  // Build-plate override (#1337). When omitted, the slicer uses the process
  // preset's curr_bed_type as-is. Canonical values match BambuStudio /
  // OrcaSlicer's enum: "Cool Plate", "Engineering Plate", "High Temp Plate",
  // "Textured PEI Plate", "Smooth PEI Plate", "Cool Plate (SuperTack)",
  // "Supertack Plate".
  bed_type?: string | null;
  // "Slice as designed" (#2611). 3MF only: slice using the file's embedded
  // project_settings.config (the designer's own wall count, infill, etc.)
  // instead of the picked profile triplet. The preset refs above are still
  // required by the backend validator but go unused on this path.
  use_embedded_settings?: boolean;
  // Process settings the user edited in the slice modal's settings panel,
  // already serialised into the string forms a process preset stores ("1" for
  // a bool, "20%" for a percent, a list for the per-extruder vectors). Patched
  // onto the resolved process JSON after the designer's carried tweaks, so an
  // explicit choice here wins. Omitted when the panel is untouched.
  process_overrides?: Record<string, string | string[]>;
  // Design settings carried from the source 3MF (#2622) — a list of keys the
  // file flags as changed from the system preset, not values.
  design_overrides?: string[];
  // Layout passes the slicer runs before slicing (#2548), both off by
  // default because they move or rotate the objects the user laid out.
  // Unlike the fields above these are CLI actions rather than profile
  // values, so they apply on the embedded-settings path too.
  auto_orient?: boolean;
  auto_arrange?: boolean;
}
export type SlicerCloudStatus = 'ok' | 'not_authenticated' | 'expired' | 'unreachable';
export interface UnifiedPreset {
  id: string;
  name: string;
  source: PresetSource;
  // Populated for the filament slot only — used by the SliceModal multi-color
  // pre-pick to score presets against each plate slot's required (type,
  // colour). Optional because the bundled / standard tier rarely carries a
  // colour (colour is a runtime spool attribute on Bambu) and older API
  // responses pre-date these fields entirely.
  filament_type?: string | null;
  filament_colour?: string | null;
  // Printer-preset names a process / filament preset declares itself
  // compatible with. Populated for the local tier (the slicer's own
  // `compatible_printers`); null for cloud / standard. The SliceModal filters
  // the process / filament dropdowns by the selected printer using this when
  // present (#1325).
  compatible_printers?: string[] | null;
}
export interface UnifiedPresetsBySlot {
  printer: UnifiedPreset[];
  process: UnifiedPreset[];
  filament: UnifiedPreset[];
}
export interface UnifiedPresetsResponse {
  // Priority order: local > orca_cloud > cloud > standard. No cross-tier
  // dedup — every tier surfaces its full list so the user can pick from
  // any source. The order drives auto-pick + visual group rendering only.
  orca_cloud: UnifiedPresetsBySlot;
  cloud: UnifiedPresetsBySlot;
  local: UnifiedPresetsBySlot;
  standard: UnifiedPresetsBySlot;
  cloud_status: SlicerCloudStatus;
  orca_cloud_status: SlicerCloudStatus;
}
export interface SlicerPipeline {
  id: number;
  name: string;
  description: string | null;
  printer_preset: PresetRef;
  process_preset: PresetRef;
  filament_presets: PresetRef[];
  bed_type: string | null;
  target_kind: 'specific_printer' | 'printer_class';
  target_printer_id: number | null;
  target_model_class: string | null;
  fanout_strategy: 'max_parallel' | 'fill_one_first' | 'round_robin';
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface SlicerPipelineCreateRequest {
  name: string;
  description?: string | null;
  printer_preset: PresetRef;
  process_preset: PresetRef;
  filament_presets: PresetRef[];
  bed_type?: string | null;
}
export type SlicerPipelineUpdateRequest = Partial<SlicerPipelineCreateRequest> & {
  target_kind?: 'specific_printer' | 'printer_class';
  // ``target_printer_id: 0`` means "clear the target" — the backend maps that
  // to null. Use null in TypeScript for the same intent.
  target_printer_id?: number | null;
  target_model_class?: string | null;
  fanout_strategy?: 'max_parallel' | 'fill_one_first' | 'round_robin';
};
export interface SlicerPipelinesListResponse {
  pipelines: SlicerPipeline[];
}
export type PipelineEligibilityKind =
  | 'printer_not_set'
  | 'printer_not_found'
  | 'printer_disabled'
  | 'printer_offline'
  | 'filament_type_mismatch'
  | 'filament_color_mismatch'
  | 'ams_slot_missing'
  | 'filament_unverified'
  | 'no_class_matches'
  | 'class_not_set';
export interface PipelineEligibilityIssue {
  kind: PipelineEligibilityKind;
  slot_index: number | null;
  expected: string | null;
  actual: string | null;
}
export interface PipelinePerPrinterReport {
  printer_id: number;
  printer_name: string;
  ok: boolean;
  issues: PipelineEligibilityIssue[];
}
export interface PipelineEligibilityReport {
  ok: boolean;
  target_kind: 'specific_printer' | 'printer_class';
  target_printer_id: number | null;
  target_printer_name: string | null;
  target_model_class: string | null;
  issues: PipelineEligibilityIssue[];
  printer_reports: PipelinePerPrinterReport[];
}
export interface PipelineJob {
  id: number;
  pipeline_run_id: number;
  copy_index: number;
  assigned_printer_id: number | null;
  assigned_printer_name: string | null;
  queue_entry_id: number | null;
  status:
    | 'pending'
    | 'awaiting_printer'
    | 'queued'
    | 'printing'
    | 'completed'
    | 'failed'
    | 'cancelled';
  error_message: string | null;
  dispatched_at: string | null;
  completed_at: string | null;
}
export interface PipelineRun {
  id: number;
  pipeline_id: number | null;
  pipeline_name: string | null;
  source_library_file_id: number | null;
  source_archive_id: number | null;
  source_filename: string | null;
  parent_run_id: number | null;
  copies: number;
  copies_completed: number;
  copies_failed: number;
  copies_cancelled: number;
  copies_in_progress: number;
  status:
    | 'queued'
    | 'slicing'
    | 'dispatching'
    | 'in_progress'
    | 'completed'
    | 'failed'
    | 'partial_failure'
    | 'cancelled';
  slice_job_id: number | null;
  sliced_library_file_id: number | null;
  eligibility_overridden: boolean;
  error_message: string | null;
  created_by: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  jobs: PipelineJob[];
  target_kind: 'specific_printer' | 'printer_class' | null;
  target_printer_id: number | null;
  target_model_class: string | null;
  fanout_strategy: 'max_parallel' | 'fill_one_first' | 'round_robin' | null;
}
export interface PipelineRunListResponse {
  runs: PipelineRun[];
  total: number;
}
export interface SliceResponse {
  library_file_id: number;
  name: string;
  print_time_seconds: number;
  filament_used_g: number;
  filament_used_mm: number;
  used_embedded_settings: boolean;
  /** Why the result could not be written to the external folder the source
   * lives in, and so went to managed storage instead. Null on every normal
   * slice. Surfaced to the user — a file filed somewhere they aren't looking
   * with no signal is what made #2810 invisible from the UI. */
  external_write_fallback?: string | null;
}
export interface SliceArchiveResponse {
  archive_id: number;
  name: string;
  print_time_seconds: number;
  filament_used_g: number;
  filament_used_mm: number;
  used_embedded_settings: boolean;
}
export type SliceJobStatus = 'pending' | 'running' | 'completed' | 'failed';
export interface SliceJobEnqueueResponse {
  job_id: number;
  status: SliceJobStatus;
  status_url: string;
}
export interface SliceJobProgress {
  /** Stage label emitted by the slicer ("Generating G-code", "Slicing finished"). */
  stage: string;
  total_percent: number;
  plate_percent: number;
  /** 1-indexed plate position; 0 means "all plates" / final completion. */
  plate_index: number;
  plate_count: number;
  updated_at: number;
  /** When the backend is in the cross-class slice-all loop (#1493), each
   *  per-plate sub-slice's progress is augmented with the loop position
   *  so the toast can show "Plate 2 of 5 — Generating G-code 47%". The
   *  fields are absent on a single-plate slice. */
  multi_plate_index?: number;
  multi_plate_count?: number;
}
/** GET /slicer/status — ob das eingestellte Slicer-Sidecar antwortet.
 *
 * ``url`` ist die tatsächlich benutzte Adresse (Einstellung vor env-Vorgabe),
 * damit die Meldung sie nennen kann: ``localhost`` auf dem Pi zeigt auf den Pi
 * selbst, nicht auf den PC, auf dem das Sidecar läuft. */
export interface SlicerStatus {
  configured: boolean;
  reachable: boolean;
  url: string | null;
  version: string | null;
  error: string | null;
}

export interface SliceJobState {
  job_id: number;
  status: SliceJobStatus;
  kind: 'library_file' | 'archive';
  source_id: number;
  source_name: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  /** Live progress fed by the sidecar's --pipe channel; null until the
   * slicer emits its first frame (early "Initializing" phase) or when
   * the sidecar doesn't support progress. */
  progress: SliceJobProgress | null;
  result?: SliceResponse | SliceArchiveResponse;
  error_status?: number;
  error_detail?: string;
  /** Maschinenlesbare Ursache ("sidecar_unreachable", "timeout", …), damit
   * die Oberfläche eine Handlungsanweisung statt des englischen Backend-Texts
   * zeigen kann. Fehlt bei Fehlern ohne eigenen Rat. */
  error_kind?: string | null;
}
export interface LocalPreset {
  id: number;
  name: string;
  preset_type: string;
  source: string;
  filament_type: string | null;
  filament_vendor: string | null;
  nozzle_temp_min: number | null;
  nozzle_temp_max: number | null;
  pressure_advance: string | null;
  default_filament_colour: string | null;
  filament_cost: string | null;
  filament_density: string | null;
  compatible_printers: string | null;
  inherits: string | null;
  version: string | null;
  created_at: string;
  updated_at: string;
}
export interface LocalPresetDetail extends LocalPreset {
  setting: Record<string, unknown>;
}
export interface LocalPresetsResponse {
  filament: LocalPreset[];
  printer: LocalPreset[];
  process: LocalPreset[];
}
export interface ImportResponse {
  success: boolean;
  imported: number;
  skipped: number;
  errors: string[];
}
export interface FieldOption {
  value: string;
  label: string;
}
export interface FieldDefinition {
  key: string;
  label: string;
  type: 'text' | 'number' | 'boolean' | 'select';
  category: string;
  description?: string;
  options?: FieldOption[];
  unit?: string;
  min?: number;
  max?: number;
  step?: number;
}
export interface FieldDefinitionsResponse {
  version: string;
  description: string;
  fields: FieldDefinition[];
}
export interface CloudDevice {
  dev_id: string;
  name: string;
  dev_model_name: string | null;
  dev_product_name: string | null;
  online: boolean;
}
export interface SmartPlug {
  id: number;
  name: string;
  plug_type: 'tasmota' | 'homeassistant' | 'mqtt' | 'rest';
  ip_address: string | null;  // Required for Tasmota
  ha_entity_id: string | null;  // Required for Home Assistant (e.g., "switch.printer_plug", "script.turn_on_printer")
  // Home Assistant energy sensor entities (optional)
  ha_power_entity: string | null;
  ha_energy_today_entity: string | null;
  ha_energy_total_entity: string | null;
  // MQTT fields (required when plug_type="mqtt")
  // Legacy field - kept for backward compatibility
  mqtt_topic: string | null;  // Deprecated, use mqtt_power_topic
  mqtt_multiplier: number;  // Deprecated, use mqtt_power_multiplier
  // Power monitoring
  mqtt_power_topic: string | null;  // Topic for power data
  mqtt_power_path: string | null;  // e.g., "power_l1" or "data.power"
  mqtt_power_multiplier: number;  // Unit conversion for power
  // Energy monitoring
  mqtt_energy_topic: string | null;  // Topic for energy data
  mqtt_energy_path: string | null;  // e.g., "energy_l1"
  mqtt_energy_multiplier: number;  // Unit conversion for energy
  // State monitoring
  mqtt_state_topic: string | null;  // Topic for state data
  mqtt_state_path: string | null;  // e.g., "state_l1" for ON/OFF
  mqtt_state_on_value: string | null;  // What value means "ON" (e.g., "ON", "true", "1")
  // REST/Webhook fields (required when plug_type="rest")
  rest_on_url: string | null;
  rest_on_body: string | null;
  rest_off_url: string | null;
  rest_off_body: string | null;
  rest_method: string | null;
  rest_headers: string | null;
  rest_status_url: string | null;
  rest_status_path: string | null;
  rest_status_on_value: string | null;
  rest_power_url: string | null;
  rest_power_path: string | null;
  rest_power_multiplier: number;
  rest_energy_url: string | null;
  rest_energy_path: string | null;
  rest_energy_multiplier: number;
  // Lifetime counter, separate from the daily one (#2539). A Shelly reports only
  // this; Today and Yesterday are derived from its hourly snapshots.
  rest_energy_total_path: string | null;
  rest_energy_total_multiplier: number;
  printer_id: number | null;
  // #2629: only a plug that really feeds the printer may mark it offline when
  // switched off. Accessory plugs follow the print cycle without powering it.
  controls_printer_power: boolean;
  enabled: boolean;
  auto_on: boolean;
  auto_off: boolean;
  auto_off_persistent: boolean;
  off_delay_mode: 'time' | 'temperature';
  off_delay_minutes: number;
  off_temp_threshold: number;
  // #1349: auto-off after AMS drying completes.
  auto_off_after_drying: boolean;
  off_delay_after_drying_minutes: number;
  username: string | null;
  password: string | null;
  // Power alerts
  power_alert_enabled: boolean;
  power_alert_high: number | null;
  power_alert_low: number | null;
  power_alert_last_triggered: string | null;
  // Schedule
  schedule_enabled: boolean;
  schedule_on_time: string | null;
  schedule_off_time: string | null;
  // Visibility options
  show_in_switchbar: boolean;
  show_on_printer_card: boolean;  // For scripts: show on printer card
  // Status
  last_state: string | null;
  last_checked: string | null;
  auto_off_executed: boolean;  // True when auto-off was triggered after print
  created_at: string;
  updated_at: string;
}
export interface SmartPlugCreate {
  name: string;
  plug_type?: 'tasmota' | 'homeassistant' | 'mqtt' | 'rest';
  ip_address?: string | null;  // Required for Tasmota
  ha_entity_id?: string | null;  // Required for Home Assistant
  // Home Assistant energy sensor entities (optional)
  ha_power_entity?: string | null;
  ha_energy_today_entity?: string | null;
  ha_energy_total_entity?: string | null;
  // MQTT fields (required when plug_type="mqtt")
  // Legacy fields - kept for backward compatibility
  mqtt_topic?: string | null;
  mqtt_multiplier?: number;
  // Power monitoring
  mqtt_power_topic?: string | null;
  mqtt_power_path?: string | null;
  mqtt_power_multiplier?: number;
  // Energy monitoring
  mqtt_energy_topic?: string | null;
  mqtt_energy_path?: string | null;
  mqtt_energy_multiplier?: number;
  // State monitoring
  mqtt_state_topic?: string | null;
  mqtt_state_path?: string | null;
  mqtt_state_on_value?: string | null;
  // REST fields
  rest_on_url?: string | null;
  rest_on_body?: string | null;
  rest_off_url?: string | null;
  rest_off_body?: string | null;
  rest_method?: string | null;
  rest_headers?: string | null;
  rest_status_url?: string | null;
  rest_status_path?: string | null;
  rest_status_on_value?: string | null;
  rest_power_url?: string | null;
  rest_power_path?: string | null;
  rest_power_multiplier?: number;
  rest_energy_url?: string | null;
  rest_energy_path?: string | null;
  rest_energy_multiplier?: number;
  rest_energy_total_path?: string | null;
  rest_energy_total_multiplier?: number;
  printer_id?: number | null;
  // #2629
  controls_printer_power?: boolean;
  enabled?: boolean;
  auto_on?: boolean;
  auto_off?: boolean;
  auto_off_persistent?: boolean;
  off_delay_mode?: 'time' | 'temperature';
  off_delay_minutes?: number;
  off_temp_threshold?: number;
  // #1349
  auto_off_after_drying?: boolean;
  off_delay_after_drying_minutes?: number;
  username?: string | null;
  password?: string | null;
  // Power alerts
  power_alert_enabled?: boolean;
  power_alert_high?: number | null;
  power_alert_low?: number | null;
  // Schedule
  schedule_enabled?: boolean;
  schedule_on_time?: string | null;
  schedule_off_time?: string | null;
  // Visibility options
  show_in_switchbar?: boolean;
  show_on_printer_card?: boolean;
}
export interface SmartPlugUpdate {
  name?: string;
  plug_type?: 'tasmota' | 'homeassistant' | 'mqtt' | 'rest';
  ip_address?: string | null;
  ha_entity_id?: string | null;
  // Home Assistant energy sensor entities (optional)
  ha_power_entity?: string | null;
  ha_energy_today_entity?: string | null;
  ha_energy_total_entity?: string | null;
  // MQTT fields (legacy)
  mqtt_topic?: string | null;
  mqtt_multiplier?: number;
  // MQTT power fields
  mqtt_power_topic?: string | null;
  mqtt_power_path?: string | null;
  mqtt_power_multiplier?: number;
  // MQTT energy fields
  mqtt_energy_topic?: string | null;
  mqtt_energy_path?: string | null;
  mqtt_energy_multiplier?: number;
  // MQTT state fields
  mqtt_state_topic?: string | null;
  mqtt_state_path?: string | null;
  mqtt_state_on_value?: string | null;
  // REST fields
  rest_on_url?: string | null;
  rest_on_body?: string | null;
  rest_off_url?: string | null;
  rest_off_body?: string | null;
  rest_method?: string | null;
  rest_headers?: string | null;
  rest_status_url?: string | null;
  rest_status_path?: string | null;
  rest_status_on_value?: string | null;
  rest_power_url?: string | null;
  rest_power_path?: string | null;
  rest_power_multiplier?: number;
  rest_energy_url?: string | null;
  rest_energy_path?: string | null;
  rest_energy_multiplier?: number;
  rest_energy_total_path?: string | null;
  rest_energy_total_multiplier?: number;
  printer_id?: number | null;
  // #2629
  controls_printer_power?: boolean;
  enabled?: boolean;
  auto_on?: boolean;
  auto_off?: boolean;
  auto_off_persistent?: boolean;
  off_delay_mode?: 'time' | 'temperature';
  off_delay_minutes?: number;
  off_temp_threshold?: number;
  // #1349
  auto_off_after_drying?: boolean;
  off_delay_after_drying_minutes?: number;
  username?: string | null;
  password?: string | null;
  // Power alerts
  power_alert_enabled?: boolean;
  power_alert_high?: number | null;
  power_alert_low?: number | null;
  // Schedule
  schedule_enabled?: boolean;
  schedule_on_time?: string | null;
  schedule_off_time?: string | null;
  // Visibility options
  show_in_switchbar?: boolean;
  show_on_printer_card?: boolean;
}
export interface HAEntity {
  entity_id: string;
  friendly_name: string;
  state: string | null;
  domain: string;  // "switch", "light", "input_boolean", "script"
}
export interface HASensorEntity {
  entity_id: string;
  friendly_name: string;
  state: string | null;
  unit_of_measurement: string | null;  // "W", "kW", "kWh", "Wh"
}
export interface HATestConnectionResult {
  success: boolean;
  message: string | null;
  error: string | null;
}
export interface PrinterHASensor {
  id: number;
  printer_id: number;
  name: string;
  entity_id: string;
  kind: 'binary' | 'numeric';
  device_class: string | null;  // HA's own class: "door", "temperature", ...
  unit: string | null;  // numeric sensors only
  // What counts as needing attention. Binary sensors use alert_state, numeric
  // ones the thresholds; all null means the sensor is display-only.
  alert_state: 'on' | 'off' | null;
  alert_above: number | null;
  alert_below: number | null;
  block_print: boolean;  // hold the printer's queue while alerting
  notify_on_alert: boolean;
  show_on_printer_card: boolean;
  sort_order: number;
  last_state: string | null;
  last_changed: string | null;
  last_checked: string | null;
  created_at: string;
  updated_at: string;
}
export interface PrinterHASensorReading {
  id: number;
  name: string;
  entity_id: string;
  kind: 'binary' | 'numeric';
  device_class: string | null;
  unit: string | null;
  state: string | null;  // null when unreadable or not yet polled
  value: number | null;  // numeric sensors only
  alerting: boolean;
  block_print: boolean;
  reachable: boolean;
  last_changed: string | null;
}
export interface PrinterHASensorCreate {
  printer_id: number;
  name: string;
  entity_id: string;
  kind: 'binary' | 'numeric';
  device_class?: string | null;
  unit?: string | null;
  alert_state?: 'on' | 'off' | null;
  alert_above?: number | null;
  alert_below?: number | null;
  block_print?: boolean;
  notify_on_alert?: boolean;
  show_on_printer_card?: boolean;
  sort_order?: number;
}
export type PrinterHASensorUpdate = Partial<Omit<PrinterHASensorCreate, 'printer_id'>>;
export interface LocationHASensor {
  id: number;
  location_id: number;
  name: string;
  entity_id: string;
  kind: 'binary' | 'numeric';
  device_class: string | null;
  unit: string | null;
  alert_state: 'on' | 'off' | null;
  alert_above: number | null;
  alert_below: number | null;
  notify_on_alert: boolean;
  show_on_card: boolean;
  sort_order: number;
  last_state: string | null;
  last_changed: string | null;
  last_checked: string | null;
  created_at: string;
  updated_at: string;
}
export interface LocationHASensorReading {
  id: number;
  name: string;
  entity_id: string;
  kind: 'binary' | 'numeric';
  device_class: string | null;
  unit: string | null;
  state: string | null;
  value: number | null;
  alerting: boolean;
  reachable: boolean;
  alert_state: string | null;
  alert_above: number | null;
  alert_below: number | null;
  last_changed: string | null;
  show_on_card: boolean;
}
export interface LocationHASensorCreate {
  location_id: number;
  name: string;
  entity_id: string;
  kind: 'binary' | 'numeric';
  device_class?: string | null;
  unit?: string | null;
  alert_state?: 'on' | 'off' | null;
  alert_above?: number | null;
  alert_below?: number | null;
  notify_on_alert?: boolean;
  show_on_card?: boolean;
  sort_order?: number;
}
export type LocationHASensorUpdate = Partial<Omit<LocationHASensorCreate, 'location_id'>>;
export interface HADisplayEntity {
  entity_id: string;
  friendly_name: string;
  state: string | null;
  domain: string;  // "binary_sensor" | "sensor"
  device_class: string | null;
  unit_of_measurement: string | null;
}
export interface SmartPlugEnergy {
  power: number | null;  // Current watts
  voltage: number | null;  // Volts
  current: number | null;  // Amps
  today: number | null;  // kWh used today
  yesterday: number | null;  // kWh used yesterday
  total: number | null;  // Total kWh
  factor: number | null;  // Power factor (0-1)
  apparent_power: number | null;  // VA
  reactive_power: number | null;  // VAr
}
export interface SmartPlugStatus {
  state: string | null;
  reachable: boolean;
  device_name: string | null;
  energy: SmartPlugEnergy | null;
}
export interface SmartPlugTestResult {
  success: boolean;
  state: string | null;
  device_name: string | null;
}
export interface TasmotaScanStatus {
  running: boolean;
  scanned: number;
  total: number;
}
export interface DiscoveredTasmotaDevice {
  ip_address: string;
  name: string;
  module: number | null;
  state: string | null;
  discovered_at: string | null;
}

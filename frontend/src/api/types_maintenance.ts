// Aus types.ts ausgelagerte Typen: Version/Update, Wartung und Hardware samt Angebots-Typen.

import type { QuoteItem } from './forkApi';

export interface VersionInfo {
  version: string;
  repo: string;
}
export interface UpdateCheckResult {
  update_available: boolean;
  current_version: string;
  latest_version: string | null;
  release_name?: string;
  release_notes?: string;
  release_url?: string;
  published_at?: string;
  error?: string;
  message?: string;
  is_docker?: boolean;
  is_ha_addon?: boolean;
  is_windows_installer?: boolean;
  update_method?: 'docker' | 'git' | 'ha_addon' | 'windows_installer';
  installer_download_url?: string | null;
  // Best-effort guess at the compose directory (#2664). Prefill only — the
  // value the user saved lives on AppSettings.docker_compose_dir, so clearing
  // that field falls back to this guess instead of resurrecting the old value.
  compose_dir_detected?: string | null;
}
export interface UpdateStatus {
  status: 'idle' | 'checking' | 'downloading' | 'installing' | 'complete' | 'error';
  progress: number;
  message: string;
  error: string | null;
  signature_enforced?: boolean;
  /** Der Dienst startet sich nach dem Update selbst neu (PRINTLAB_AUTO_RESTART). */
  restarting?: boolean;
  rolled_back?: { from_ref: string | null; to_version: string | null; reason: string; at: string } | null;
}
export interface MaintenanceType {
  id: number;
  name: string;
  description: string | null;
  default_interval_hours: number;
  interval_type: 'hours' | 'days';  // "hours" = print hours, "days" = calendar days
  icon: string | null;
  wiki_url: string | null;  // Documentation link
  is_system: boolean;
  created_at: string;
}
export interface MaintenanceTypeCreate {
  name: string;
  description?: string | null;
  default_interval_hours?: number;
  interval_type?: 'hours' | 'days';
  icon?: string | null;
  wiki_url?: string | null;
}
export interface MaintenanceStatus {
  id: number;
  printer_id: number;
  printer_name: string;
  printer_model: string | null;
  maintenance_type_id: number;
  maintenance_type_name: string;
  maintenance_type_icon: string | null;
  maintenance_type_wiki_url: string | null;  // Custom wiki URL from type
  enabled: boolean;
  interval_hours: number;  // For hours type: print hours; for days type: number of days
  interval_type: 'hours' | 'days';
  current_hours: number;
  hours_since_maintenance: number;
  hours_until_due: number;
  days_since_maintenance: number | null;  // For days type
  days_until_due: number | null;  // For days type
  is_due: boolean;
  is_warning: boolean;
  last_performed_at: string | null;
}
export interface PrinterMaintenanceOverview {
  printer_id: number;
  printer_name: string;
  printer_model: string | null;
  total_print_hours: number;
  maintenance_items: MaintenanceStatus[];
  due_count: number;
  warning_count: number;
}
export interface MaintenanceHistory {
  id: number;
  printer_maintenance_id: number;
  performed_at: string;
  hours_at_maintenance: number;
  notes: string | null;
}
export interface MaintenanceSummary {
  total_due: number;
  total_warning: number;
  printers_with_issues: Array<{
    printer_id: number;
    printer_name: string;
    due_count: number;
    warning_count: number;
  }>;
}
export type MaintenanceProgram = 'oil' | 'rods';
export interface MaintenanceProgramStatus {
  printer_id: number;
  program: MaintenanceProgram | null;
  label: string | null;
  active: boolean;
  phase: 'idle' | 'starting' | 'homing' | 'z' | 'xy' | 'pause' | 'done' | 'stopped' | 'error' | string;
  message: string;
  step: number;
  steps: number;
  percent: number;
  eta_seconds: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  runs: number;
}
export interface MaintenanceProgramStartResponse extends MaintenanceProgramStatus {
  success: boolean;
  message: string;
}
export interface HardwareSlot {
  id: number;
  type: 'supply' | 'storage' | string;
  status: 'ready' | 'used' | 'empty' | 'occupied' | string;
  label?: string;
  print?: string | null;
}
export interface PartialHardwareSlot {
  id: number;
  type?: 'supply' | 'storage' | string;
  status?: 'ready' | 'used' | 'empty' | 'occupied' | string;
  label?: string;
}
export interface HardwareStatus {
  mode: 'simulated' | 'command' | string;
  door: 'open' | 'closed' | 'unknown' | string;
  plate_on_bed: boolean;
  busy: boolean;
  error: string | null;
  slots: HardwareSlot[];
  supply_ready: number;
  storage_empty: number;
  changes: number;
  last_change: string | null;
  estop?: boolean;
  incomplete?: { step: string; plate_swapped: boolean; job: string } | null;
  auto_plate_change?: AutoPlateChange;
}
export interface AutoPlateChange {
  enabled: boolean;
  cooldown_bed_temp: number;
  max_wait_seconds: number;
  poll_seconds: number;
  skip_if_offline: boolean;
  only_with_queue?: boolean;
  low_supply_warning?: number;
  notify?: boolean;
  auto_confirm_plate_clear?: boolean;
  plate_clear_min_confidence?: number;
  last_run: {
    printer_id: number;
    job: string;
    ok: boolean;
    message: string;
    warning?: string;
  } | null;
}
export interface HardwareActionResponse extends HardwareStatus {
  success: boolean;
  message: string;
}
export interface PlateCalibrationStatus {
  calibrated: boolean;
  points: Array<[number, number]> | null;
  plate_size: number;
}
export interface QuoteResponse {
  currency: string;
  inputs: Record<string, number>;
  material: number;
  energy: number;
  labor: number;
  subtotal: number;
  markup: number;
  total: number;
}
export interface QuoteHistoryEntry {
  id: string;
  number?: string;
  ts: string;
  customer: string;
  description: string;
  currency: string;
  material: number;
  energy: number;
  labor: number;
  subtotal: number;
  markup: number;
  total: number;
  items?: QuoteItem[];
  extras?: number;
}
export interface QuoteCustomerTotal {
  customer: string;
  currency: string;
  count: number;
  total: number;
}
export interface PriceListEntry {
  material: string;
  rate_per_kg: number;
}
export interface AuditEntry {
  ts: string;
  action: string;
  ok: boolean;
  message: string;
  printer_id: number | null;
  user: string | null;
  details?: Record<string, unknown>;
}
export interface HardwareConfig {
  mode: 'simulated' | 'command' | string;
  door_open_command: string | string[];
  door_close_command: string | string[];
  door_status_command: string | string[];
  plate_change_command: string | string[];
  emergency_stop_command: string | string[];
  timeout_seconds: number;
  auto_plate_change?: AutoPlateChange;
}
export interface MaintenancePrintResponse {
  success: boolean;
  message: string;
  filename: string;
  download_url: string;
}

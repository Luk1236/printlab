// Aus types.ts ausgelagerte Typen: Archiv, Druckprotokoll, Projekte, BOM und Voransichten.

export interface ArchiveDuplicate {
  id: number;
  print_name: string | null;
  created_at: string;
  match_type: 'exact' | 'similar';  // 'exact' = hash match, 'similar' = name match
}
export interface ArchivePrinterMediaFile {
  name: string;
  path: string;
  size: number;
  mtime: string | null;
  kind: 'timelapse' | 'ipcam';
}
export interface ArchivePrinterMedia {
  archive_id: number;
  printer_id: number | null;
  local_timelapse: { name: string; size: number } | null;
  remote_files: ArchivePrinterMediaFile[];
  warnings: Array<'printer_missing' | 'timelapse_unavailable' | 'ipcam_unavailable' | 'printer_files_forbidden'>;
}
export type VerdictSource = 'dialog' | 'link' | 'plate_clear' | 'printer_card' | 'api' | 'reaction';
export interface Archive {
  id: number;
  printer_id: number | null;
  project_id: number | null;
  project_name: string | null;
  filename: string;
  file_path: string;
  file_size: number;
  content_hash: string | null;
  thumbnail_path: string | null;
  timelapse_path: string | null;
  source_3mf_path: string | null;
  f3d_path: string | null;
  duplicates: ArchiveDuplicate[] | null;
  duplicate_count: number;
  duplicate_sequence: number;  // 0 = original, 1+ = nth duplicate
  original_archive_id: number | null;  // ID of the first/original archive
  object_count: number | null;
  print_name: string | null;
  plate_id: number | null;  // Selected plate of a multi-plate 3MF (#2603)
  print_time_seconds: number | null;
  actual_time_seconds: number | null;  // Computed from started_at/completed_at
  time_accuracy: number | null;  // Percentage: 100 = perfect, >100 = faster than estimated
  filament_used_grams: number | null;
  filament_type: string | null;
  filament_color: string | null;
  layer_height: number | null;
  total_layers: number | null;
  nozzle_diameter: number | null;
  bed_temperature: number | null;
  bed_type: string | null;  // Build plate type from 3MF (e.g. "Cool Plate", "Textured PEI Plate")
  nozzle_temperature: number | null;
  sliced_for_model: string | null;  // Printer model this file was sliced for
  status: string;
  started_at: string | null;
  completed_at: string | null;
  extra_data: Record<string, unknown> | null;
  makerworld_url: string | null;
  designer: string | null;
  external_url: string | null;
  is_favorite: boolean;
  tags: string | null;
  notes: string | null;
  cost: number | null;
  photos: string[] | null;
  failure_reason: string | null;
  // Post-print outcome confirmation (#1898)
  user_verdict: 'good' | 'reject' | null;
  // How the verdict arrived; 'reaction' is written by the Telegram reaction
  // handler (#3046) and is labelled here so it reads correctly once that lands.
  user_verdict_source: VerdictSource | null;
  user_verdict_at: string | null;
  confirm_requested: boolean;
  quantity: number;
  energy_kwh: number | null;
  energy_cost: number | null;
  created_at: string;
  // User tracking (Issue #206)
  created_by_id: number | null;
  created_by_username: string | null;
  // Per-archive run aggregates from PrintLogEntry (#1378)
  run_count: number;
  last_run_at: string | null;
  total_filament_actual_grams: number | null;
  successful_run_count: number;
  failed_run_count: number;
}
export interface ArchiveSlim {
  printer_id: number | null;
  print_name: string | null;
  print_time_seconds: number | null;
  actual_time_seconds: number | null;
  filament_used_grams: number | null;
  filament_type: string | null;
  filament_color: string | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  cost: number | null;
  energy_kwh: number | null;
  energy_cost: number | null;
  quantity: number;
  created_at: string;
}
export interface PrintLogEntry {
  id: number;
  archive_id: number | null;
  print_name: string | null;
  printer_name: string | null;
  printer_id: number | null;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  filament_type: string | null;
  filament_color: string | null;
  filament_used_grams: number | null;
  cost: number | null;
  energy_kwh: number | null;
  energy_cost: number | null;
  failure_reason: string | null;
  thumbnail_path: string | null;
  created_by_id: number | null;
  created_by_username: string | null;
  created_at: string;
}
export interface PrintLogResponse {
  items: PrintLogEntry[];
  total: number;
}
export interface ArchiveStats {
  total_prints: number;
  successful_prints: number;
  failed_prints: number;
  cancelled_prints: number;
  total_print_time_hours: number;
  total_filament_grams: number;
  total_cost: number;
  prints_by_filament_type: Record<string, number>;
  prints_by_printer: Record<string, number>;
  // Name each printer id was last recorded under in the print log, so history
  // belonging to a deleted printer keeps its label.
  printer_names?: Record<string, string>;
  average_time_accuracy: number | null;
  time_accuracy_by_printer: Record<string, number> | null;
  total_energy_kwh: number;
  total_energy_cost: number;
  // True when a date-filtered total-consumption query is running on incomplete
  // snapshot history (e.g. right after upgrade, before hourly snapshots have
  // a baseline). UI should explain why the number may undercount.
  energy_data_warming_up?: boolean;
}
export interface TagInfo {
  name: string;
  count: number;
}
export interface FailureAnalysis {
  period_days: number;
  total_prints: number;
  failed_prints: number;
  failure_rate: number;
  // Quality dimension (#1898): completed prints the user rejected. Optional
  // so a frontend build against an older backend degrades gracefully.
  rejected_prints?: number;
  yield_rate?: number;
  rejects_by_reason?: Record<string, number>;
  failures_by_reason: Record<string, number>;
  failures_by_filament: Record<string, number>;
  failures_by_printer: Record<string, number>;
  failures_by_hour: Record<number, number>;
  recent_failures: Array<{
    id: number;
    print_name: string;
    failure_reason: string | null;
    filament_type: string | null;
    printer_id: number | null;
    created_at: string | null;
  }>;
  trend: Array<{
    week_start: string;
    total_prints: number;
    failed_prints: number;
    failure_rate: number;
  }>;
}
export interface BulkUploadResult {
  uploaded: number;
  failed: number;
  results: Array<{ filename: string; id: number; status: string }>;
  errors: Array<{ filename: string; error: string }>;
}
export interface ComparisonArchiveInfo {
  id: number;
  print_name: string;
  status: string;
  created_at: string | null;
  printer_id: number | null;
  project_name: string | null;
}
export interface ComparisonField {
  field: string;
  label: string;
  unit: string | null;
  values: (string | number | null)[];
  raw_values: (string | number | null)[];
  has_difference: boolean;
}
export interface SuccessCorrelationInsight {
  field: string;
  label: string;
  insight: string;
  success_avg?: number;
  failed_avg?: number;
  success_values?: string[];
  failed_values?: string[];
}
export interface SuccessCorrelation {
  has_both_outcomes: boolean;
  message?: string;
  successful_count?: number;
  failed_count?: number;
  insights?: SuccessCorrelationInsight[];
}
export interface ArchiveComparison {
  archives: ComparisonArchiveInfo[];
  comparison: ComparisonField[];
  differences: ComparisonField[];
  success_correlation: SuccessCorrelation;
}
export interface SimilarArchive {
  archive: {
    id: number;
    print_name: string;
    status: string;
    created_at: string | null;
  };
  match_reason: string;
  match_score: number;
}
export interface ProjectStats {
  total_archives: number;
  total_items: number;  // Sum of quantities (total items printed)
  completed_prints: number;  // Sum of quantities for completed prints (parts)
  failed_prints: number;
  queued_prints: number;
  in_progress_prints: number;
  total_print_time_hours: number;
  total_filament_grams: number;
  progress_percent: number | null;  // Plates progress (total_archives / target_count)
  parts_progress_percent: number | null;  // Parts progress (completed_prints / target_parts_count)
  estimated_cost: number;
  total_energy_kwh: number;
  total_energy_cost: number;
  remaining_prints: number | null;  // Remaining plates
  remaining_parts: number | null;  // Remaining parts
  bom_total_items: number;
  bom_completed_items: number;
  bom_cost: number;
}
export interface ProjectChildPreview {
  id: number;
  name: string;
  color: string | null;
  status: string;
  progress_percent: number | null;
  descendant_count: number;
  total_archives: number;
  completed_prints: number;
  total_print_time_hours: number;
  total_filament_grams: number;
  total_cost: number;  // Filament + energy + BOM, matching the parent's cost card
}
export interface Project {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  status: string;  // active, completed, archived
  target_count: number | null;  // Target number of plates/print jobs
  target_parts_count: number | null;  // Target number of parts/objects
  target_sets: number | null;  // Copies-per-file target (#1897)
  notes: string | null;
  attachments: ProjectAttachment[] | null;
  tags: string | null;
  due_date: string | null;
  priority: string;  // low, normal, high, urgent
  budget: number | null;
  is_template: boolean;
  template_source_id: number | null;
  parent_id: number | null;
  parent_name: string | null;
  children: ProjectChildPreview[];
  descendant_count: number;  // Sub-projects at any depth beneath this one (#1264)
  created_at: string;
  updated_at: string;
  stats?: ProjectStats;
  // This project's numbers combined with every sub-project's. Null when there
  // are none, since it would only repeat `stats` (#1264).
  rollup_stats?: ProjectStats | null;
  url: string | null;  // External link rendered next to project name on the card (#1155)
  cover_image_filename: string | null;  // Filename within project attachments dir (#1155)
}
export interface ProjectAttachment {
  filename: string;
  original_name: string;
  size: number;
  uploaded_at: string;
}
export interface ProjectFileProgress {
  file_id: number;
  completed_count: number;
}
export interface ArchivePreview {
  id: number;
  print_name: string | null;
  thumbnail_path: string | null;
  status: string;
  filament_type: string | null;
  filament_color: string | null;
}
export interface ProjectListItem {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  status: string;
  target_count: number | null;  // Target number of plates/print jobs
  target_parts_count: number | null;  // Target number of parts/objects
  target_sets: number | null;  // #1897 — the shared edit dialog seeds itself from this
  budget: number | null;
  tags: string | null;  // #2536 — the shared edit dialog seeds itself from this
  due_date: string | null;  // #2536
  priority: string;  // #2536
  created_at: string;
  archive_count: number;  // Number of print jobs (plates)
  total_items: number;  // Sum of quantities (total items printed, including failed)
  completed_count: number;  // Sum of quantities for completed prints only (parts)
  failed_count: number;  // Sum of quantities for failed prints
  queue_count: number;
  progress_percent: number | null;  // Plates progress
  parent_id: number | null;  // #1264 — set when this is a sub-project
  child_count: number;  // #1264 — direct sub-projects only
  archives: ArchivePreview[];
  url: string | null;  // #1155
  cover_image_filename: string | null;  // #1155
}
export interface ProjectCreate {
  name: string;
  description?: string;
  color?: string;
  target_count?: number;
  target_parts_count?: number;
  target_sets?: number;
  notes?: string;
  tags?: string;
  due_date?: string;
  priority?: string;
  budget?: number | null;
  parent_id?: number;
  url?: string | null;  // #1155
}
export interface ProjectUpdate {
  name?: string;
  description?: string;
  color?: string;
  status?: string;
  target_count?: number;
  target_parts_count?: number;
  target_sets?: number | null;  // #1897 — explicit null clears the copies-per-file target
  notes?: string;
  tags?: string | null;  // #2536 — explicit null clears the tags
  due_date?: string | null;  // #2536 — explicit null clears the due date
  priority?: string;
  budget?: number | null;
  parent_id?: number;
  url?: string | null;  // #1155 — explicit null clears the URL
}
export interface BOMItem {
  id: number;
  project_id: number;
  name: string;
  quantity_needed: number;
  quantity_acquired: number;
  unit_price: number | null;
  sourcing_url: string | null;
  archive_id: number | null;
  archive_name: string | null;
  stl_filename: string | null;
  remarks: string | null;
  sort_order: number;
  is_complete: boolean;
  created_at: string;
  updated_at: string;
}
export interface BOMItemCreate {
  name: string;
  quantity_needed?: number;
  unit_price?: number;
  sourcing_url?: string;
  archive_id?: number;
  stl_filename?: string;
  remarks?: string;
}
export interface BOMItemUpdate {
  name?: string;
  quantity_needed?: number;
  quantity_acquired?: number;
  unit_price?: number;
  sourcing_url?: string;
  archive_id?: number;
  stl_filename?: string;
  remarks?: string;
}
export interface BOMItemExport {
  name: string;
  quantity_needed: number;
  quantity_acquired: number;
  unit_price: number | null;
  sourcing_url: string | null;
  stl_filename: string | null;
  remarks: string | null;
}
export interface LinkedFolderExport {
  name: string;
}
export interface ProjectExport {
  name: string;
  description: string | null;
  color: string | null;
  status: string;
  target_count: number | null;
  target_parts_count: number | null;
  target_sets: number | null;  // #1897
  notes: string | null;
  tags: string | null;
  due_date: string | null;
  priority: string;
  budget: number | null;
  bom_items: BOMItemExport[];
  linked_folders: LinkedFolderExport[];
}
export interface ProjectImport {
  name: string;
  description?: string;
  color?: string;
  status?: string;
  target_count?: number;
  target_parts_count?: number;
  target_sets?: number;  // #1897
  notes?: string;
  tags?: string;
  due_date?: string;
  priority?: string;
  budget?: number | null;
  bom_items?: BOMItemExport[];
  linked_folders?: LinkedFolderExport[];
}
export interface TimelineEvent {
  event_type: string;
  timestamp: string;
  title: string;
  description: string | null;
  metadata: Record<string, unknown> | null;
}

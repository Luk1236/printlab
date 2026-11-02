// Aus types.ts ausgelagerte Typen für Dateimanager (Library), Discovery, Virtual Printer, Firmware und System.

export interface LibraryFolderTree {
  id: number;
  name: string;
  parent_id: number | null;
  project_id: number | null;
  archive_id: number | null;
  project_name: string | null;
  archive_name: string | null;
  is_external: boolean;
  external_path: string | null;
  external_readonly: boolean;
  file_count: number;
  // max(folder.updated_at, max(immediate-child file.updated_at)). Used by
  // the File Manager folder tree's "sort by recent activity" mode (#1770).
  latest_activity_at: string | null;
  children: LibraryFolderTree[];
}
export interface LibraryFolder {
  id: number;
  name: string;
  parent_id: number | null;
  project_id: number | null;
  archive_id: number | null;
  project_name: string | null;
  archive_name: string | null;
  is_external: boolean;
  external_path: string | null;
  external_readonly: boolean;
  external_show_hidden: boolean;
  file_count: number;
  latest_activity_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface LibraryFolderCreate {
  name: string;
  parent_id?: number | null;
  project_id?: number | null;
  archive_id?: number | null;
}
export interface ExternalFolderCreate {
  name: string;
  external_path: string;
  readonly?: boolean;
  show_hidden?: boolean;
  parent_id?: number | null;
}
export interface LibraryFolderUpdate {
  name?: string;
  parent_id?: number | null;
  project_id?: number | null;  // 0 to unlink
  archive_id?: number | null;  // 0 to unlink
}
export interface LibraryFileDuplicate {
  id: number;
  filename: string;
  folder_id: number | null;
  folder_name: string | null;
  created_at: string;
}
export interface LibraryFile {
  id: number;
  folder_id: number | null;
  folder_name: string | null;
  project_id: number | null;
  project_name: string | null;
  is_external: boolean;
  filename: string;
  file_path: string;
  file_type: string;
  file_size: number;
  file_hash: string | null;
  thumbnail_path: string | null;
  metadata: Record<string, unknown> | null;
  print_count: number;
  last_printed_at: string | null;
  notes: string | null;
  // User link + photos of the printed result (#3077); source_url is the
  // read-only import provenance (MakerWorld).
  external_url: string | null;
  photos: string[];
  source_url: string | null;
  duplicates: LibraryFileDuplicate[] | null;
  duplicate_count: number;
  // User tracking (Issue #206)
  created_by_id: number | null;
  created_by_username: string | null;
  created_at: string;
  updated_at: string;
  // Metadata fields
  print_name: string | null;
  print_time_seconds: number | null;
  filament_used_grams: number | null;
  sliced_for_model: string | null;
}
export interface LibraryTagSummary {
  id: number;
  name: string;
}
export interface LibraryFileListItem {
  id: number;
  folder_id: number | null;
  is_external: boolean;
  filename: string;
  file_type: string;
  file_size: number;
  thumbnail_path: string | null;
  print_count: number;
  duplicate_count: number;
  // User tracking (Issue #206)
  created_by_id: number | null;
  created_by_username: string | null;
  created_at: string;
  // Real on-disk modification time (#2680). Null for managed uploads; the date
  // sort and "Modified" column use `fs_modified_at ?? created_at`.
  fs_modified_at: string | null;
  print_name: string | null;
  print_time_seconds: number | null;
  filament_used_grams: number | null;
  sliced_for_model: string | null;
  // Tags assigned to this file (#1268). The backend always emits an empty
  // array when a file has no tags, but the field is typed optional so any
  // legacy code path (or mock) that constructs a LibraryFileListItem without
  // it doesn't crash the renderer. Read sites use `file.tags ?? []`.
  tags?: LibraryTagSummary[];
  // Variant grouping (#671 / #2570). `variant_count` is the size of the whole
  // group, which may include files in other folders — never the number of
  // matching rows on screen. 0 when the file is not grouped.
  variant_group_id?: number | null;
  variant_count?: number;
  // Metadata indicators (#3077). Optional for the same reason as `tags`: older
  // mocks construct list items without them. Read sites default to falsy.
  external_url?: string | null;
  has_notes?: boolean;
  photo_count?: number;
}
export interface VariantGroupMember {
  library_file_id: number;
  filename: string;
  target_model: string;
  position: number;
}
export interface VariantGroup {
  id: number;
  name: string;
  /** In priority order — index 0 wins when several printers are free at once. */
  members: VariantGroupMember[];
}
export interface LibraryTag {
  id: number;
  name: string;
  file_count: number;
  created_at: string;
  updated_at: string;
}
export interface LibraryTagBulkAssignResult {
  files_updated: number;
  associations_added: number;
  associations_removed: number;
}
export interface LibraryFileUpdate {
  filename?: string;
  folder_id?: number | null;
  project_id?: number | null;
  notes?: string | null;
  external_url?: string | null;
}
export interface LibraryTrashItem {
  id: number;
  filename: string;
  file_size: number;
  thumbnail_path: string | null;
  folder_id: number | null;
  folder_name: string | null;
  created_by_id: number | null;
  created_by_username: string | null;
  deleted_at: string;
  auto_purge_at: string;
}
export interface LibraryTrashListResponse {
  items: LibraryTrashItem[];
  total: number;
  retention_days: number;
}
export interface LibraryPurgePreview {
  count: number;
  total_bytes: number;
  sample_filenames: string[];
  older_than_days: number;
  include_never_printed: boolean;
}
export interface LibraryTrashSettings {
  retention_days: number;
  auto_purge_enabled: boolean;
  auto_purge_days: number;
  auto_purge_include_never_printed: boolean;
}
export interface ArchivePurgePreview {
  count: number;
  total_bytes: number;
  sample_filenames: string[];
  older_than_days: number;
}
export interface ArchivePurgeSettings {
  enabled: boolean;
  days: number;
  // #1390: when true, bulk-deletes the linked PrintLogEntry rows so the
  // contribution drops from Quick Stats too. Default false — soft-delete,
  // Quick Stats preserved.
  purge_stats: boolean;
}
export interface LibraryFileUploadResponse {
  id: number;
  filename: string;
  file_type: string;
  file_size: number;
  thumbnail_path: string | null;
  duplicate_of: number | null;
  metadata: Record<string, unknown> | null;
}
export interface LibraryStats {
  total_files: number;
  total_folders: number;
  total_size_bytes: number;
  files_by_type: Record<string, number>;
  total_prints: number;
  disk_free_bytes: number;
  disk_total_bytes: number;
  disk_used_bytes: number;
}
export interface ZipExtractResult {
  filename: string;
  file_id: number;
  folder_id: number | null;
}
export interface ZipExtractError {
  filename: string;
  error: string;
}
export interface ZipExtractResponse {
  extracted: number;
  folders_created: number;
  files: ZipExtractResult[];
  errors: ZipExtractError[];
}
export interface BatchThumbnailResult {
  file_id: number;
  filename: string;
  success: boolean;
  error?: string | null;
}
export interface BatchThumbnailResponse {
  processed: number;
  succeeded: number;
  failed: number;
  results: BatchThumbnailResult[];
}
export interface AddToQueueResult {
  file_id: number;
  filename: string;
  queue_item_id: number;
  archive_id: number;
}
export interface AddToQueueError {
  file_id: number;
  filename: string;
  error: string;
}
export interface AddToQueueResponse {
  added: AddToQueueResult[];
  errors: AddToQueueError[];
}
export interface DiscoveredPrinter {
  serial: string;
  name: string;
  ip_address: string;
  model: string | null;
  discovered_at: string | null;
}
export interface DiscoveryStatus {
  running: boolean;
}
export interface DiscoveryInfo {
  is_docker: boolean;
  ssdp_running: boolean;
  scan_running: boolean;
  subnets: string[];
}
export interface SubnetScanStatus {
  running: boolean;
  scanned: number;
  total: number;
}
export type VirtualPrinterMode = 'archive' | 'review' | 'queue' | 'proxy' | 'immediate' | 'print_queue';
export interface VirtualPrinterProxyStatus {
  running: boolean;
  target_host: string;
  ftp_port: number;
  mqtt_port: number;
  ftp_connections: number;
  mqtt_connections: number;
}
export interface VirtualPrinterStatus {
  enabled: boolean;
  running: boolean;
  mode: VirtualPrinterMode;
  name: string;
  serial: string;
  model: string;
  model_name: string;
  pending_files: number;
  target_printer_ip?: string;  // For proxy mode
  proxy?: VirtualPrinterProxyStatus;  // For proxy mode
}
export interface VirtualPrinterSettings {
  enabled: boolean;
  access_code_set: boolean;
  mode: VirtualPrinterMode;
  model: string;
  target_printer_id: number | null;  // For proxy mode
  remote_interface_ip: string | null;  // For SSDP proxy across networks
  tailscale_disabled: boolean;
  archive_name_source: 'metadata' | 'filename';  // Source for archive's display name
  status: VirtualPrinterStatus;
}
export interface NetworkInterface {
  name: string;
  ip: string;
  netmask: string;
  subnet: string;
  is_alias?: boolean;
  label?: string;
}
export interface VirtualPrinterModels {
  models: Record<string, string>;  // SSDP code -> display name
  default: string;
}
export interface PendingUpload {
  id: number;
  filename: string;
  // Resolved name the review card should show — mirrors what archive_print
  // will eventually write to PrintArchive.print_name (#1152 follow-up). Falls
  // back to the stripped filename stem when the 3MF has no embedded title or
  // the operator has chosen the "filename" archive-name source.
  display_name: string;
  file_size: number;
  source_ip: string | null;
  status: string;
  tags: string | null;
  notes: string | null;
  project_id: number | null;
  uploaded_at: string;
}
export interface VirtualPrinterConfig {
  id: number;
  name: string;
  enabled: boolean;
  mode: VirtualPrinterMode;
  model: string | null;
  model_name: string | null;
  access_code_set: boolean;
  serial: string;
  target_printer_id: number | null;
  auto_dispatch: boolean;
  queue_force_color_match: boolean;
  save_ams_mapping: boolean;
  gcode_injection: boolean;
  tailscale_disabled: boolean;
  bind_ip: string | null;
  remote_interface_ip: string | null;
  position: number;
  status: { running: boolean; pending_files: number; proxy?: VirtualPrinterProxyStatus };
}
export interface VirtualPrinterListResponse {
  printers: VirtualPrinterConfig[];
  models: Record<string, string>;
}
export interface VPCaCertificate {
  pem: string;
  fingerprint_sha256: string;
  not_valid_after: string;
}
export type VPDiagnosticStatus = 'pass' | 'fail' | 'warn' | 'skip';
export interface VPDiagnosticCheck {
  id:
    | 'enabled'
    | 'running'
    | 'bind_interface'
    | 'access_code'
    | 'target_printer'
    | 'port_ftps'
    | 'port_mqtt'
    | 'port_bind'
    | 'certificate';
  status: VPDiagnosticStatus;
  params: Record<string, string | number>;
}
export interface VPDiagnosticResult {
  vp_id: number;
  vp_name: string;
  mode: string;
  overall: 'ok' | 'warnings' | 'problems';
  checks: VPDiagnosticCheck[];
}
export interface TailscaleStatusResponse {
  available: boolean;
  fqdn: string;
  hostname: string;
  tailnet_name: string;
  tailscale_ips: string[];
  error: string | null;
}
export interface AvailableFirmwareVersion {
  version: string;
  file_available: boolean;
  download_url: string | null;
  release_notes: string | null;
  release_time: string | null;
}
export interface FirmwareUpdateInfo {
  printer_id: number;
  printer_name: string;
  model: string | null;
  current_version: string | null;
  latest_version: string | null;
  update_available: boolean;
  download_url: string | null;
  release_notes: string | null;
  available_versions: AvailableFirmwareVersion[];
}
export interface FirmwareUploadPrepare {
  can_proceed: boolean;
  sd_card_present: boolean;
  sd_card_free_space: number;
  firmware_size: number;
  space_sufficient: boolean;
  update_available: boolean;
  current_version: string | null;
  latest_version: string | null;
  target_version: string | null;
  firmware_filename: string | null;
  errors: string[];
}
export interface FirmwareUploadStatus {
  status: 'idle' | 'preparing' | 'downloading' | 'uploading' | 'complete' | 'error';
  progress: number;
  message: string;
  error: string | null;
  firmware_filename: string | null;
  firmware_version: string | null;
}
export interface DebugLoggingState {
  enabled: boolean;
  enabled_at: string | null;
  duration_seconds: number | null;
}
export interface LogEntry {
  timestamp: string;
  level: string;
  logger_name: string;
  message: string;
}
export interface LogsResponse {
  entries: LogEntry[];
  total_in_file: number;
  filtered_count: number;
}
export interface SpoolBuddyDevice {
  id: number;
  device_id: string;
  hostname: string;
  ip_address: string;
  backend_url?: string | null;
  firmware_version: string | null;
  has_nfc: boolean;
  has_scale: boolean;
  tare_offset: number;
  calibration_factor: number;
  nfc_reader_type: string | null;
  nfc_connection: string | null;
  display_brightness: number;
  display_blank_timeout: number;
  has_backlight: boolean;
  last_calibrated_at: string | null;
  last_seen: string | null;
  pending_command: string | null;
  nfc_ok: boolean;
  scale_ok: boolean;
  uptime_s: number;
  update_status: string | null;
  update_message: string | null;
  system_stats: {
    os?: { os?: string; kernel?: string; arch?: string; python?: string };
    cpu_temp_c?: number;
    cpu_count?: number;
    load_avg?: number[];
    memory?: { total_mb?: number; available_mb?: number; used_mb?: number; percent?: number };
    disk?: { total_gb?: number; used_gb?: number; free_gb?: number; percent?: number };
    system_uptime_s?: number;
  } | null;
  online: boolean;
}
export interface DaemonUpdateCheck {
  current_version: string;
  latest_version: string | null;
  update_available: boolean;
}
export interface BugReportRequest {
  description: string;
  email?: string;
  screenshot_base64?: string;
  include_support_info?: boolean;
  debug_logs?: string;
}
export interface BugReportResponse {
  success: boolean;
  message: string;
  issue_url?: string;
  issue_number?: number;
}
export type AnnouncementLevel = 'info' | 'important' | 'critical';
export interface AnnouncementText {
  title: string;
  body: string;
  link_label?: string;
}
export interface Announcement {
  id: string;
  level: AnnouncementLevel;
  texts: Record<string, AnnouncementText>;
  link_url: string | null;
  published_at: string | null;
  expires_at: string | null;
  // Past its expiry: kept as history, listed under "Earlier", never unread.
  archived: boolean;
  read: boolean;
}
export interface AnnouncementList {
  visible: boolean;
  announcements: Announcement[];
}

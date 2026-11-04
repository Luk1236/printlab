// Aus types.ts ausgelagerte Typen: AMS-/Heizverlauf, Systeminformationen und Lagerverbrauch.

export interface AMSHistoryPoint {
  recorded_at: string;
  humidity: number | null;
  humidity_raw: number | null;
  temperature: number | null;
}
export interface AMSHistoryResponse {
  printer_id: number;
  ams_id: number;
  data: AMSHistoryPoint[];
  min_humidity: number | null;
  max_humidity: number | null;
  avg_humidity: number | null;
  min_temperature: number | null;
  max_temperature: number | null;
  avg_temperature: number | null;
}
export type HeaterSensorKind = 'nozzle' | 'nozzle_2' | 'bed' | 'chamber';
export interface HeaterHistoryPoint {
  recorded_at: string;
  value: number | null;
  target: number | null;
}
export interface HeaterSeries {
  sensor_kind: HeaterSensorKind;
  data: HeaterHistoryPoint[];
  min_value: number | null;
  max_value: number | null;
  avg_value: number | null;
}
export interface PrinterSensorHistoryResponse {
  printer_id: number;
  series: HeaterSeries[];
}
export interface SystemInfo {
  app: {
    version: string;
    base_dir: string;
    archive_dir: string;
  };
  database: {
    engine: string;
    version: string;
    archives: number;
    archives_completed: number;
    archives_failed: number;
    archives_printing: number;
    printers: number;
    filaments: number;
    projects: number;
    smart_plugs: number;
    total_print_time_seconds: number;
    total_print_time_formatted: string;
    total_filament_grams: number;
    total_filament_kg: number;
  };
  printers: {
    total: number;
    connected: number;
    connected_list: Array<{
      id: number;
      name: string;
      state: string;
      model: string;
    }>;
  };
  storage: {
    archive_size_bytes: number;
    archive_size_formatted: string;
    database_size_bytes: number;
    database_size_formatted: string;
    disk_total_bytes: number;
    disk_total_formatted: string;
    disk_used_bytes: number;
    disk_used_formatted: string;
    disk_free_bytes: number;
    disk_free_formatted: string;
    disk_percent_used: number;
  };
  system: {
    platform: string;
    platform_release: string;
    platform_version: string;
    architecture: string;
    hostname: string;
    python_version: string;
    uptime_seconds: number;
    uptime_formatted: string;
    boot_time: string;
  };
  memory: {
    total_bytes: number;
    total_formatted: string;
    available_bytes: number;
    available_formatted: string;
    used_bytes: number;
    used_formatted: string;
    percent_used: number;
  };
  cpu: {
    count: number;
    count_logical: number;
    percent: number;
  };
}
export interface StorageUsageCategory {
  key: string;
  label: string;
  bytes: number;
  formatted: string;
  percent_of_total: number;
}
export interface StorageUsageOtherItem {
  bucket: string;
  label: string;
  kind: 'system' | 'data';
  deletable: boolean;
  bytes: number;
  formatted: string;
  percent_of_total: number;
}
export interface StorageUsageResponse {
  roots: string[];
  total_bytes: number;
  total_formatted: string;
  categories: StorageUsageCategory[];
  other_breakdown: StorageUsageOtherItem[];
  scan_errors: number;
  generated_at: string;
  cache: {
    hit: boolean;
    age_seconds: number;
    max_age_seconds: number;
  };
}

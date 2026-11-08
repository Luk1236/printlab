import { API_BASE, authToken, request } from './core';
import type {
  LayerInspectionConfig,
  LayerInspectionStatus,
  LayerInspectionTestResult,
} from './types_finance';

export const hardwareEndpoints = {
  // Phase 5: GPIO Hardware Buttons & Servo Tuning
  getGpioStatus: () =>
    request<{
      enabled: boolean;
      is_simulated: boolean;
      estop_triggered: boolean;
      estop_source: string | null;
      estop_button_physically_pressed: boolean;
      led_state: string;
      pins: Record<string, any>;
      servo_calibration: { min_angle: number; max_angle: number };
    }>('/printers/hardware/gpio/status'),
  updateGpioConfig: (payload: Record<string, any>) =>
    request<{ success: boolean; config: Record<string, any>; status: any }>('/printers/hardware/gpio/config', {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  triggerGpioEstop: () =>
    request<{ success: boolean; status: any }>('/printers/hardware/gpio/estop/trigger', { method: 'POST' }),
  resetGpioEstop: () =>
    request<{ success: boolean; message: string; status: any }>('/printers/hardware/gpio/estop/reset', { method: 'POST' }),
  testServo: (angle: number) =>
    request<{ success: boolean; message: string; angle: number }>('/printers/hardware/servo/test', {
      method: 'POST',
      body: JSON.stringify({ angle }),
    }),
  calibrateServo: (minAngle: number, maxAngle: number) =>
    request<{ success: boolean; message: string; status: any }>('/printers/hardware/servo/calibrate', {
      method: 'POST',
      body: JSON.stringify({ min_angle: minAngle, max_angle: maxAngle }),
    }),

  // Phase 6: Layer Inspection & Edge-Spaghetti-Detector
  getLayerInspection: (printerId: number) =>
    request<LayerInspectionStatus>(`/printers/${printerId}/layer-inspection`),
  updateLayerInspection: (printerId: number, config: Partial<LayerInspectionConfig>) =>
    request<{ status: string; config: LayerInspectionConfig }>(`/printers/${printerId}/layer-inspection`, {
      method: 'PUT',
      body: JSON.stringify(config),
    }),
  resetLayerInspection: (printerId: number) =>
    request<{ status: string; consecutive_alerts: number }>(`/printers/${printerId}/layer-inspection/reset`, {
      method: 'POST',
    }),
  testLayerInspection: async (printerId: number, file?: File): Promise<LayerInspectionTestResult> => {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: Record<string, string> = {};
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }
      const response = await fetch(`${API_BASE}/printers/${printerId}/layer-inspection/test`, {
        method: 'POST',
        headers,
        body: formData,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || `HTTP ${response.status}`);
      }
      return response.json();
    }
    return request<LayerInspectionTestResult>(`/printers/${printerId}/layer-inspection/test`, {
      method: 'POST',
    });
  },

  // Phase 10: Fleet Management (Overview, Batch Commands, Telemetry Sync)
  getFleetOverview: () =>
    request<{
      total_printers: number;
      online_printers: number;
      printing_count: number;
      paused_count: number;
      idle_count: number;
      maintenance_count: number;
      hms_error_count: number;
      active_jobs: Array<{
        printer_id: number;
        printer_name: string;
        model?: string | null;
        location?: string | null;
        state: string;
        subtask_name?: string | null;
        gcode_file?: string | null;
        progress: number;
        remaining_time_minutes?: number | null;
        current_layer: number;
        total_layers: number;
      }>;
      locations: Record<string, number>;
    }>('/fleet/overview'),
  executeFleetCommand: (payload: {
    action:
      | 'pause'
      | 'resume'
      | 'stop'
      | 'emergency_stop'
      | 'chamber_light_on'
      | 'chamber_light_off'
      | 'maintenance_enter'
      | 'maintenance_exit';
    printer_ids?: number[] | null;
    location?: string | null;
    reason?: string | null;
  }) =>
    request<{
      action: string;
      total_targeted: number;
      succeeded: number[];
      failed: Array<{ printer_id: number; name: string; reason: string }>;
      skipped: Array<{ printer_id: number; name: string; reason: string }>;
    }>('/fleet/command', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  syncFleetTelemetry: () =>
    request<{ total_printers: number; updates_requested: number }>('/fleet/sync', {
      method: 'POST',
    }),
  getFleetMetrics: () =>
    request<{
      active_ws_connections: number;
      total_ws_broadcasts: number;
      total_ws_messages_sent: number;
      dropped_ws_connections: number;
      last_broadcast_ms: number;
      avg_broadcast_ms: number;
      max_broadcast_ms: number;
      maintenance_printers_count: number;
    }>('/fleet/metrics'),

  // Phase 13: 2D Auto-Nesting, Batch Farm Split, 3D Orientation & G-Code M486
  autoNestParts: (payload: {
    parts: Array<{
      part_id: string;
      name: string;
      width_mm: number;
      depth_mm: number;
      height_mm?: number;
      copies?: number;
      allow_rotation?: boolean;
      filament_grams_per_copy?: number;
      print_minutes_per_copy?: number;
    }>;
    bed_width_mm?: number;
    bed_depth_mm?: number;
    bed_height_mm?: number;
    margin_mm?: number;
    spacing_mm?: number;
  }) =>
    request<{
      total_parts_requested: number;
      total_parts_placed: number;
      total_plates: number;
      average_utilization_percent: number;
      collision_free: boolean;
      total_filament_grams: number;
      total_estimated_minutes: number;
      plates: Array<Record<string, any>>;
      oversized_parts: Array<Record<string, any>>;
    }>('/fleet/auto-nest', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  splitBatchOrder: (payload: Record<string, any>) =>
    request<{
      nesting: Record<string, any>;
      fleet_split: {
        can_dispatch_parallel: boolean;
        eligible_printer_count: number;
        printers_used?: number;
        total_plates: number;
        single_printer_minutes: number;
        parallel_makespan_minutes: number;
        speedup_factor: number;
        assignments: Array<Record<string, any>>;
        unassigned_plates: number[];
      };
    }>('/fleet/batch-split', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  evaluatePartOrientation: (payload: {
    width_mm: number;
    depth_mm: number;
    height_mm: number;
    overhang_ratio_by_axis?: Record<string, number>;
  }) =>
    request<{
      recommended: Record<string, any>;
      alternatives: Array<Record<string, any>>;
    }>('/fleet/orientation-check', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  injectGcodeM486: (payload: { gcode: string; object_names?: string[] }) =>
    request<{
      total_objects: number;
      object_names: string[];
      injected_markers: number;
      already_had_m486: boolean;
      gcode: string;
    }>('/fleet/gcode-m486', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

export const qualityApi = {
  previewCertificate: (payload: {
    first_layer_score?: number;
    temp_dev_c?: number;
    anomaly_count?: number;
  }) =>
    request<{
      quality_score: number;
      quality_grade: string;
      status: string;
    }>('/quality/certificate/preview', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  skipObjects: (printerId: number, payload: { object_ids: number[]; reason?: string }) =>
    request<{
      success: boolean;
      printer_id: number;
      skipped_object_ids: number[];
      message: string;
    }>(`/quality/printers/${printerId}/skip-objects`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  detectAndSkip: (
    printerId: number,
    payload: {
      defect_x_mm: number;
      defect_y_mm: number;
      plate_objects: Array<{ id: number; name?: string; min_x: number; max_x: number; min_y: number; max_y: number }>;
      reason?: string;
    }
  ) =>
    request<{
      success: boolean;
      printer_id: number;
      matched_object_id: number | null;
      message: string;
    }>(`/quality/printers/${printerId}/detect-and-skip`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

export const accountingApi = {
  getKontenrahmen: () =>
    request<{ kontenrahmen: Record<string, any> }>("/accounting/kontenrahmen"),
  previewDatev: (params?: { skr?: string; from_date?: string; to_date?: string }) => {
    const q = new URLSearchParams(params as any).toString();
    return request<{
      invoice_count: number;
      total_net_eur: number;
      total_vat_eur: number;
      total_gross_eur: number;
      currency: string;
      selected_skr: string;
    }>(`/accounting/datev-preview${q ? `?${q}` : ""}`);
  },
  getDatevCsvUrl: (params?: { skr?: string; consultant?: number; client?: number; from_date?: string; to_date?: string }) => {
    const q = new URLSearchParams(params as any).toString();
    return `${API_BASE}/accounting/datev-csv${q ? `?${q}` : ""}`;
  },
  getZugferdPdfUrl: (invoiceId: string, lang = "de") =>
    `${API_BASE}/accounting/invoices/${invoiceId}/zugferd-pdf?lang=${lang}`,
};

export const kioskApi = {
  getStatus: () =>
    request<{
      printers: Array<any>;
      total_printers: number;
      active_printing_count: number;
      attention_needed_count: number;
      sd_wear_guard: Record<string, any>;
    }>("/kiosk/status"),
  quickAction: (
    printerId: number,
    payload: { action: string; preset?: string; confirmed?: boolean }
  ) =>
    request<{
      success: boolean;
      printer_id: number;
      action: string;
      message: string;
      preset?: string;
      bed_temp?: number;
      nozzle_temp?: number;
    }>(`/kiosk/printers/${printerId}/quick-action`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getSdGuardStats: () =>
    request<Record<string, any>>("/kiosk/sd-guard/stats"),
  cleanupSdGuard: () =>
    request<{ success: boolean; deleted_buffer_files: number }>("/kiosk/sd-guard/cleanup", {
      method: "POST",
    }),
};

export const maintenanceWearApi = {
  forecastWear: (payload: {
    printer_id: string;
    filament_type: string;
    print_time_hours: number;
    nozzle_type?: string;
  }) =>
    request<{
      printer_id: string;
      filament_type: string;
      is_abrasive: boolean;
      abrasive_multiplier: number;
      print_time_hours: number;
      effective_wear_hours: number;
      can_safely_print: boolean;
      warning_level: string;
      nozzle: Record<string, any>;
      ptfe: Record<string, any>;
      extruder: Record<string, any>;
      recommendations: string[];
    }>("/maintenance/wear/forecast", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  checkAmsDrying: (payload: {
    temp_c: number;
    humidity_pct: number;
    loaded_filaments: string[];
  }) =>
    request<{
      ambient_temp_c: number;
      humidity_pct: number;
      dew_point_c: number;
      condensation_margin_c: number;
      condensation_risk: boolean;
      overall_drying_recommended: boolean;
      critical_spools_count: number;
      spools: Array<any>;
    }>("/maintenance/ams/drying-guard", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  preflightCheck: (payload: {
    printer_id: string;
    filament_type: string;
    print_time_hours: number;
    ams_temp_c?: number;
    ams_humidity_pct?: number;
    nozzle_type?: string;
  }) =>
    request<{
      preflight_passed: boolean;
      can_start_immediately: boolean;
      critical_warnings: string[];
      wear_prediction: Record<string, any>;
      humidity_analysis: Record<string, any>;
    }>("/maintenance/preflight-check", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

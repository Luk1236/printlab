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

  // Phase 19: Purge Optimizer & Bed Damage Exclusion Zones
  optimizePurgeVolume: (payload: {
    gcode: string;
    flush_multiplier?: number;
    enable_purge_to_infill?: boolean;
    infill_purge_ratio?: number;
    cost_per_kg_eur?: number;
  }) =>
    request<{
      analysis: Record<string, any>;
      optimized: boolean;
      flush_multiplier_applied?: number;
      purge_to_infill_enabled?: boolean;
      original_purge_grams: number;
      optimized_purge_grams: number;
      saved_grams: number;
      saved_eur: number;
      savings_percent: number;
      message: string;
    }>("/fleet/purge-optimize", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
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
    exclusion_zones?: Array<{
      min_x: number;
      min_y: number;
      max_x: number;
      max_y: number;
      reason?: string;
    }>;
  }) =>
    request<{
      total_parts_requested: number;
      total_parts_placed: number;
      total_plates: number;
      average_utilization_percent: number;
      collision_free: boolean;
      exclusion_safe: boolean;
      exclusion_zones_applied: Array<any>;
      total_filament_grams: number;
      total_estimated_minutes: number;
      plates: Array<any>;
      oversized_parts: Array<any>;
    }>("/fleet/auto-nest", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Service-Position & Wartungs-Routinen (Düsenwechsel & Reinigung)
  moveToServicePosition: (printerId: string, payload?: {
    preheat_nozzle_c?: number;
    lower_bed_mm?: number;
  }) =>
    request<{
      printer_id: string;
      action: string;
      success: boolean;
      nozzle_target_temp_c: number;
      bed_z_pos_mm: number;
      safety_instructions: string[];
      steps: string[];
    }>(`/maintenance/printers/${printerId}/service-position`, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),
  exitServicePosition: (printerId: string, payload?: { perform_home?: boolean }) =>
    request<{
      printer_id: string;
      action: string;
      success: boolean;
      message: string;
    }>(`/maintenance/printers/${printerId}/exit-service-position`, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),
  runColdPullRoutine: (printerId: string, payload: {
    step: "heat" | "cooldown" | "pull" | "inspect";
    filament_type?: string;
  }) =>
    request<{
      printer_id: string;
      step: string;
      target_temp_c: number;
      status_message: string;
      next_action: string;
      is_completed: boolean;
    }>(`/maintenance/printers/${printerId}/cold-pull`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  runCleaningMotion: (printerId: string, payload: {
    routine: "carbon_rods" | "z_lead_screws" | "nozzle_wipe";
    cycles?: number;
  }) =>
    request<{
      printer_id: string;
      routine: string;
      cycles: number;
      status: string;
      instructions: string;
    }>(`/maintenance/printers/${printerId}/cleaning-motion`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  completeMaintenanceCleaningTask: (printerId: string, payload: {
    component: "nozzle" | "ptfe" | "z_spindle" | "steel_rods" | "carbon_filter";
    notes?: string;
  }) =>
    request<{
      success: boolean;
      printer_id: string;
      component: string;
      message: string;
      wear_status: Record<string, any>;
    }>(`/maintenance/printers/${printerId}/complete-task`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Phase 21: HX711 Spool Scale & Barcode Scanner
  getScaleStatus: () =>
    request<{
      is_active: boolean;
      is_simulated: boolean;
      pins: { dt_pin: number; sck_pin: number };
      tare_offset: number;
      calibration_factor: number;
      last_gross_weight_grams: number;
      spool_profiles: Record<string, number>;
    }>("/hardware/scale/status"),
  tareScale: () =>
    request<{
      success: boolean;
      tare_offset: number;
      message: string;
    }>("/hardware/scale/tare", { method: "POST" }),
  calibrateScale: (payload: { known_weight_grams: number }) =>
    request<{
      success: boolean;
      calibration_factor: number;
      message: string;
    }>("/hardware/scale/calibrate", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  readSpoolWeight: (payload?: { spool_type?: string; custom_tare_grams?: number }) =>
    request<{
      gross_weight_grams: number;
      tare_weight_grams: number;
      net_filament_grams: number;
      spool_type: string;
      timestamp: string;
    }>("/hardware/scale/read-spool", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),
  verifySpoolPreflight: (payload: {
    required_grams: number;
    spool_type?: string;
    safety_margin_grams?: number;
  }) =>
    request<{
      can_safely_print: boolean;
      net_filament_grams: number;
      required_grams: number;
      remaining_after_job_grams: number;
      deficit_grams: number;
      warning: string | null;
    }>("/hardware/scale/verify-preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  processScannerInput: (payload: { raw_barcode: string }) =>
    request<{
      action_type: "spool_identify" | "job_inspect" | "order_update" | "unknown";
      code: string;
      matched_entity: Record<string, any>;
      message: string;
    }>("/hardware/scanner/scan", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  assignSpoolViaScan: (payload: {
    spool_id: string;
    printer_id: string;
    tray_slot: number;
  }) =>
    request<{
      success: boolean;
      printer_id: string;
      tray_slot: number;
      spool: Record<string, any>;
      message: string;
    }>("/hardware/scanner/assign-spool-to-slot", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Phase 22: Automatischer Druckbett-Auswurf (Auto Ejector)
  getEjectorConfig: () =>
    request<{
      enabled: boolean;
      mode: string;
      gpio_pin: number;
      gpio_pulse_seconds: number;
      max_bed_temp_c: number;
      auto_advance_queue: boolean;
      cooldown_check_enabled: boolean;
    }>("/automation/ejector/config"),
  updateEjectorConfig: (payload: {
    enabled?: boolean;
    mode?: string;
    gpio_pin?: number;
    gpio_pulse_seconds?: number;
    max_bed_temp_c?: number;
    auto_advance_queue?: boolean;
    cooldown_check_enabled?: boolean;
  }) =>
    request<Record<string, any>>("/automation/ejector/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  triggerEjection: (payload: {
    printer_id: string;
    current_bed_temp_c?: number;
    filament_type?: string;
    force?: boolean;
  }) =>
    request<{
      success: boolean;
      printer_id: string;
      ejected: boolean;
      mode: string;
      message: string;
    }>("/automation/ejector/trigger", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getEjectorStatus: (printerId: string, currentBedTempC: number = 25.0, filamentType: string = "PLA") =>
    request<{
      printer_id: string;
      can_eject: boolean;
      current_bed_temp_c: number;
      target_bed_temp_c: number;
      temp_delta_c: number;
      reason: string;
    }>(`/automation/ejector/status/${printerId}?current_bed_temp_c=${currentBedTempC}&filament_type=${filamentType}`),

  // Phase 23: KI-Druckbett-Räumungsprüfung (Plate Clearance AI)
  inspectPlateClearance: (printerId: string, payload?: {
    threshold?: number;
    mock_has_obstacle?: boolean;
    mock_obstacle_type?: string;
  }) =>
    request<{
      printer_id: string;
      can_safely_print: boolean;
      clearance_score: number;
      threshold: number;
      status: string;
      detected_anomalies: string[];
      message: string;
    }>(`/plate-clearance/inspect/${printerId}`, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),
  setPlateClearanceBaseline: (printerId: string, payload: {
    resolution?: string;
    mean_brightness?: number;
    edge_density?: number;
  }) =>
    request<{
      success: boolean;
      printer_id: string;
      baseline: Record<string, any>;
      message: string;
    }>(`/plate-clearance/set-baseline/${printerId}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  overridePlateClearance: (printerId: string, payload: {
    operator_name: string;
    notes?: string;
  }) =>
    request<{
      success: boolean;
      printer_id: string;
      override: Record<string, any>;
      message: string;
    }>(`/plate-clearance/override/${printerId}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getPlateClearanceStatus: (printerId: string) =>
    request<{
      printer_id: string;
      has_baseline: boolean;
      baseline_info: Record<string, any> | null;
      latest_inspection: Record<string, any>;
    }>(`/plate-clearance/status/${printerId}`),

  // Phase 24: E-Commerce & ERP Webhook-Brücke
  getEcommerceConfig: () =>
    request<{
      enabled: boolean;
      shopify_webhook_secret: string;
      woocommerce_webhook_secret: string;
      sap_erp_api_token: string;
      auto_queue_incoming_orders: boolean;
      default_material: string;
    }>("/integrations/ecommerce/config"),
  updateEcommerceConfig: (payload: Record<string, any>) =>
    request<Record<string, any>>("/integrations/ecommerce/config", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  submitSapOrder: (payload: {
    sap_sales_order_id: string;
    plant_id?: string;
    company_code?: string;
    delivery_date?: string;
    materials: Array<Record<string, any>>;
  }, authToken?: string) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (authToken) {
      headers["Authorization"] = `Bearer ${authToken}`;
    }
    return request<Record<string, any>>("/integrations/ecommerce/sap-erp/order", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
  },

  // Phase 25: Multi-Location Farm Mesh & Cloud-Relay
  getMeshNodes: () =>
    request<{
      local_node: Record<string, any>;
      peer_nodes: Array<Record<string, any>>;
    }>("/mesh/nodes"),
  registerMeshNode: (payload: {
    node_id: string;
    name: string;
    location: string;
    api_url: string;
    auth_token?: string;
    printers_count?: number;
  }) =>
    request<{
      success: boolean;
      node: Record<string, any>;
      message: string;
    }>("/mesh/nodes/register", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  unregisterMeshNode: (nodeId: string) =>
    request<{ success: boolean; message: string }>(`/mesh/nodes/${nodeId}`, {
      method: "DELETE",
    }),
  sendMeshHeartbeat: (payload: {
    node_id: string;
    active_printers: number;
    queue_depth: number;
    latency_ms?: number;
  }) =>
    request<Record<string, any>>("/mesh/heartbeat", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getMeshOverview: () =>
    request<{
      mesh_health: string;
      total_locations_count: number;
      online_nodes_count: number;
      total_cluster_printers: number;
      total_cluster_queue_jobs: number;
      local_node: Record<string, any>;
      remote_nodes: Array<Record<string, any>>;
      timestamp: string;
    }>("/mesh/overview"),
  routeMeshJob: (payload: {
    job_name: string;
    material?: string;
    required_grams?: number;
    local_farm_busy?: boolean;
  }) =>
    request<{
      routed_target: string;
      target_node_id: string;
      target_node_name: string;
      target_location?: string;
      reason: string;
      job_name: string;
      material: string;
    }>("/mesh/route-job", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

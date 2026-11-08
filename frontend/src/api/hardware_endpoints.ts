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
};

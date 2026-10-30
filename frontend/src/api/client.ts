import { API_BASE, authToken, parseContentDispositionFilename, request } from './core';
export * from './core';
export * from './types';
export { api } from './endpoints';
import type {
  AnnouncementList,
  BugReportRequest,
  BugReportResponse,
  DaemonUpdateCheck,
  DebugLoggingState,
  DiscoveredPrinter,
  DiscoveryInfo,
  DiscoveryStatus,
  FirmwareUpdateInfo,
  FirmwareUploadPrepare,
  FirmwareUploadStatus,
  LogsResponse,
  PendingUpload,
  SpoolBuddyDevice,
  SpoolLabelField,
  SubnetScanStatus,
  TailscaleStatusResponse,
  VPCaCertificate,
  VPDiagnosticResult,
  VirtualPrinterConfig,
  VirtualPrinterListResponse,
  VirtualPrinterModels,
  VirtualPrinterSettings,
} from './types';


export type {
  RemoteAccessStatus,
  CompanyProfile,
  PiHealthWarning,
  PiHealth,
  AlertChannelsStatus,
  SetupStatus,
  UpdateBackup,
  UpdateBackups,
  PlateTuningAnalysis,
  Invoice,
  InvoicesResponse,
  QuoteItem,
  QuoteActuals,
  QuoteActualsLine,
  AssistantConfig,
  AssistantStatus,
  AssistantAction,
  AssistantAnswer,
  SelfTestResult,
  SelfTestReport,
} from './forkApi';



// Connection diagnostic (GET /printers/{id}/diagnostic and
// POST /printers/diagnostic). Each check's `id` + `status` resolve a
// localized title/fix under `diagnostic.check.*`; `params` interpolate it.



// --- Log-health scan: self-service triage on the System page + bug reporter.
// The backend matches recent logs against a curated known-issue catalog;
// human-readable cause/fix text is rendered from i18n keys keyed by signature_id.



// Long-lived camera tokens (#1108). The `token` field is populated only on the
// create response — listing endpoints set it to null because the plaintext
// value is shown to the user exactly once.
//
// 'camera_stream' reaches the video endpoints only. 'camwall' additionally
// reaches the read-only Cam Wall feed, which names the printers (#2531), so it
// is a separate scope rather than a widening of tokens already in the wild.


// An external application that signs users in with their PrintLab account.
// `client_secret` is present only in the create / rotate responses.


// One row of the token-authenticated Cam Wall feed (#2531). Deliberately
// smaller than PrinterStatus: no serial, no IP, no print filename — a kiosk URL
// is not a secret, so the payload behind it must not be either.

// Streaming-overlay feed (#2613). The subset of print state the /overlay page
// draws for one printer, served behind an `overlay`-scoped token so OBS embeds
// with no login session can read it. Unlike CamWallPrinter this names the file
// being printed (the overlay shows the part on screen).

// Printer types










// Which AMS slot one hotend is currently fed from. ams_id/slot_id are null when
// the hotend holds nothing. Keyed by extruder id ('0' = right, '1' = left).
// tray_now cannot answer this — it is one value for the whole printer, so on a
// dual-nozzle machine it names only one of the two loaded hotends.

// Which FTS inlet an AMS is plumbed into: 'A' | 'B'.



// Plate Detection





// Archive types



/** How a post-print outcome verdict reached the archive (#1898). */









// Archive Comparison types






// Project types

// A sub-project as listed on its parent's page. The figures cover the child's
// own subtree, so the listed rows add up to the parent's roll-up minus the
// parent's own prints (#1264).



// Completed-run count for one library file inside a project (#1897)





// BOM Types - Tracks sourced/purchased parts (hardware, electronics, etc.)



// Project Export/Import Types




// Timeline Types

// API Key types




/**
 * Tri-state calibration option (BambuStudio parity): "off" never runs it,
 * "on" forces it every print, "auto" lets the printer skip it if it was done
 * recently. Used by bed_levelling, flow_cali, and nozzle_offset_cali.
 */

// Settings types


// MQTT relay status

// Cloud types


// Orca Cloud types — paste-flow PKCE handshake against auth.orcaslicer.com.
// See backend/app/services/orca_cloud.py for the deep dive on why this
// flow is paste-based rather than callback-based.




// Orca profiles are shaped to match Bambu Cloud's SlicerSetting on the wire
// so the frontend can use the same visual components for both surfaces (cards,
// grouped sections, filter bar). Backend handles the source-specific
// transformation in routes/orca_cloud.py::_orca_to_setting.



// MakerWorld integration. Full metadata/instance shapes come back as
// Record<string, unknown> — MakerWorld's API adds fields over time, so we
// pass them through verbatim rather than maintaining a brittle mirror.














// Built-in filament fallback (static table from backend)

// Slice request/response — POST /library/files/{id}/slice and /archives/{id}/slice
//
// Two preset shapes are accepted per slot:
//   - Legacy bare integer ids (`*_preset_id`) — pre-cloud-tier clients.
//   - Source-aware refs (`*_preset: PresetRef`) — new SliceModal that picks
//     across cloud / local / standard tiers. Source-aware refs win when both
//     are present in the same payload.
/**
 * Why a preset's effective values are unavailable.
 *
 * `sidecar_outdated` is the one that matters in practice: an install pulls its
 * sidecar as `SIDECAR_TAG:-latest` regardless of which PrintLab channel it is
 * on, so a user can perfectly well be running a current PrintLab against a
 * sidecar that predates this endpoint. That has a one-line fix, and saying so
 * beats a generic "could not read the values".
 */



// GET /api/v1/slicer/presets — unified listing across cloud / local / standard.

// Slicer Pipelines (#1425) — named bundles of preset slots the SliceModal
// can apply in one click. PR A surfaces only the bundle; target_* and
// fanout_strategy round-trip from the backend but the UI doesn't yet expose
// them (they come alive in PR B / PR C).

// Slicer Pipeline runs (#1425 PR B + PR C)



// Background slice-job lifecycle. POST /slice returns 202 + this shape;
// the frontend polls /slice-jobs/{id} until status is terminal.




// Local preset types (OrcaSlicer imports)








// Smart Plug types



// Home Assistant entity for smart plug selection

// Home Assistant sensor entity for energy monitoring


// A Home Assistant entity bound to a printer for display on its card (#1148, #448).
// Read-only: unlike a SmartPlug there is nothing here to switch.








// An entity offered by the binding picker.




// Tasmota Discovery types


// Print Queue types





/** One candidate file for a cross-model queue item (#671). */







// MQTT Logging types


// K-Profile types






// Slot Preset Mapping

// Filament types

// Notification Provider types
// How a Telegram provider collects the outcome verdict (#3046)




// GitHub Backup types

/** How many cloud accounts a backup would collect presets from. Counts only —
 *  with auth enabled the accounts belong to individual users, so the backup
 *  administrator sees how many, never whose. */





// Restore from a Git backup (#2656). Cloud profiles are absent deliberately —
// the backup collector never writes them, so there is nothing to restore.



/**
 * Values the server interpolates into a translated note or preview detail.
 * Kept to strings and numbers on purpose — anything richer would have to be
 * formatted server-side and could not be translated.
 */




/**
 * One tally note, as a translation code plus its parameters (#2656).
 *
 * Same contract as {@link LocalBackupPathCheck} one card down: the server picks
 * the code and supplies typed params, and the client renders
 * ``t(`backup.restoreFromGit.notes.${code}`, { ...params, defaultValue: message })``.
 * A code the client does not know yet falls back to the English `message`
 * rather than showing the raw key.
 */





/** Result of writing a probe file into the configured backup directory (#2544). */



// Lightweight subset served under printers:read for the printer-card badge (#1546)






// Provider-specific config types for reference





// Notification Template types





// Notification Log types


// Spoolman types








// Inventory types
// Label printing (#809). Mirror of backend.app.services.label_renderer.TemplateName.

// Mirror of backend.app.services.label_renderer.LabelField, in print order (#2981).
// Mirror of DEFAULT_LABEL_FIELDS: what a label carried before fields were selectable.
export const DEFAULT_SPOOL_LABEL_FIELDS: SpoolLabelField[] = [
  'brand',
  'material',
  'hex',
  'name',
  'location',
  'qr',
  'spool_id',
];




// ── Suppliers (#2988) ──────────────────────────────────────────────────────

/** Where filament is bought — distinct from brand (who made it). */


/** One spool-to-supplier assignment as written by the spool dialog. */


/** Per-supplier inventory aggregate (#2988), purchase-source spools only. */

/** Per-material-number inventory aggregate (#2870). */


// ── CSV import/export (#1576) ──────────────────────────────────────────────
/** One row's outcome from the import preview / real import. */

/** Dry-run preview: per-row classification, no rows written. */

/** Summary returned after a real (non-dry-run) import. */




/**
 * One per-printer-model override of a spool's slicer filament preset.
 *
 * A cloud or Orca preset is bound to a printer model ("@BBL X1C"), so the
 * spool's single `slicer_filament` is wrong as soon as the spool is used on a
 * second model. `nozzle_diameter` is "" for the model's own default and a bare
 * decimal ("0.2") for a per-hotend exception; the backend resolves
 * exact (model, diameter) -> (model, "") -> the spool's own preset.
 */



/** One inventory-bound AMS slot, as returned by `/printers/{id}/inventory-remain`. */

/** Display identity of an inventory-bound slot. See `SlotMaterial.spool`. */






// Update types



// Maintenance types






// Maintenance programs (ported from Bambu-Monitor)



// Hardware extension (door servo + plate changer), ported from Bambu-Monitor

/** Teil-Update eines Magazin-Fachs (der Server akzeptiert id + beliebiges davon). */




















// External Links (sidebar)



// Finance types















// Permission type - all available permissions

// Group types








// User email notification preferences

// Auth types



/**
 * Just enough to label an owner id (#1894). Backed by GET /users/slim, which
 * is readable with `users:read_slim` as well as the admin-level `users:read`
 * -- use it anywhere a screen only needs to turn a `created_by_id` into a
 * name, so operators are not forced into the full listing to get one.
 */









// 2FA / MFA interfaces





/**
 * A URL that is known to be same-origin (a relative path starting with ``/``).
 *
 * Branded so that producers of same-origin URLs (e.g. ``api.oidcProviderIconUrl``)
 * can be distinguished from arbitrary strings at the type level.  The brand
 * is compile-time only; at runtime these are plain strings.
 *
 * Purpose: CSP-safe image sources for ``<img src=...>``. The strict
 * ``img-src 'self' data: blob:`` CSP rejects anything that isn't same-origin,
 * so callers that demand a ``SameOriginUrl`` get a compile-time guarantee
 * that no external URL slips through.
 */

// OIDC interfaces
/** What the unauthenticated GET /auth/oidc/providers returns (#3107): only
 *  what the login page renders. The full provider, group sync config
 *  included, needs the admin-only /auth/oidc/providers/all. */














// API functions

// AMS History types






// System Info types




// Library (File Manager) types









// Variant groups (#671 / #2570): the same job sliced for different printers.


// Library tag catalog (#1268)



// Library trash (#1008)











// STL Thumbnail Generation types


// Library Queue types



// Discovery types




// Discovery API
export const discoveryApi = {
  getInfo: () => request<DiscoveryInfo>('/discovery/info'),

  getStatus: () => request<DiscoveryStatus>('/discovery/status'),

  startDiscovery: (duration: number = 10) =>
    request<DiscoveryStatus>(`/discovery/start?duration=${duration}`, { method: 'POST' }),

  stopDiscovery: () =>
    request<DiscoveryStatus>('/discovery/stop', { method: 'POST' }),

  getDiscoveredPrinters: () =>
    request<DiscoveredPrinter[]>('/discovery/printers'),

  // Subnet scanning (for Docker environments)
  startSubnetScan: (subnet: string, timeout: number = 1.0) =>
    request<SubnetScanStatus>('/discovery/scan', {
      method: 'POST',
      body: JSON.stringify({ subnet, timeout }),
    }),

  getScanStatus: () => request<SubnetScanStatus>('/discovery/scan/status'),

  stopSubnetScan: () =>
    request<SubnetScanStatus>('/discovery/scan/stop', { method: 'POST' }),
};

// Virtual Printer types
// Canonical wire values: `archive`, `review`, `queue`, `proxy`. The legacy
// `immediate` (→ archive) and `print_queue` (→ queue) names are still
// accepted by the backend so older API clients keep working, but new code
// should send the canonical names.







// Virtual Printer API
export const virtualPrinterApi = {
  getSettings: () => request<VirtualPrinterSettings>('/settings/virtual-printer'),

  getModels: () => request<VirtualPrinterModels>('/settings/virtual-printer/models'),

  updateSettings: (data: {
    enabled?: boolean;
    access_code?: string;
    mode?: 'archive' | 'review' | 'queue' | 'proxy';
    model?: string;
    target_printer_id?: number;
    remote_interface_ip?: string;
    tailscale_disabled?: boolean;
    archive_name_source?: 'metadata' | 'filename';
  }) => {
    const params = new URLSearchParams();
    if (data.enabled !== undefined) params.set('enabled', String(data.enabled));
    if (data.access_code !== undefined) params.set('access_code', data.access_code);
    if (data.mode !== undefined) params.set('mode', data.mode);
    if (data.model !== undefined) params.set('model', data.model);
    if (data.target_printer_id !== undefined) params.set('target_printer_id', String(data.target_printer_id));
    if (data.remote_interface_ip !== undefined) params.set('remote_interface_ip', data.remote_interface_ip);
    if (data.tailscale_disabled !== undefined) params.set('tailscale_disabled', String(data.tailscale_disabled));
    if (data.archive_name_source !== undefined) params.set('archive_name_source', data.archive_name_source);

    return request<VirtualPrinterSettings>(`/settings/virtual-printer?${params.toString()}`, {
      method: 'PUT',
    });
  },
};

// Multi Virtual Printer API


export const multiVirtualPrinterApi = {
  list: () => request<VirtualPrinterListResponse>('/virtual-printers'),

  get: (id: number) => request<VirtualPrinterConfig>(`/virtual-printers/${id}`),

  create: (data: {
    name?: string;
    enabled?: boolean;
    mode?: string;
    model?: string;
    access_code?: string;
    target_printer_id?: number;
    auto_dispatch?: boolean;
    queue_force_color_match?: boolean;
    save_ams_mapping?: boolean;
    gcode_injection?: boolean;
    bind_ip?: string;
    remote_interface_ip?: string;
  }) =>
    request<VirtualPrinterConfig>('/virtual-printers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  update: (id: number, data: {
    name?: string;
    enabled?: boolean;
    mode?: string;
    model?: string;
    access_code?: string;
    target_printer_id?: number;
    auto_dispatch?: boolean;
    queue_force_color_match?: boolean;
    save_ams_mapping?: boolean;
    gcode_injection?: boolean;
    tailscale_disabled?: boolean;
    bind_ip?: string;
    remote_interface_ip?: string;
  }) =>
    request<VirtualPrinterConfig>(`/virtual-printers/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  remove: (id: number) =>
    request<{ detail: string; id: number }>(`/virtual-printers/${id}`, {
      method: 'DELETE',
    }),

  getTailscaleStatus: () =>
    request<TailscaleStatusResponse>('/virtual-printers/tailscale-status'),

  getCaCertificate: () =>
    request<VPCaCertificate>('/virtual-printers/ca-certificate'),

  diagnose: (id: number) =>
    request<VPDiagnosticResult>(`/virtual-printers/${id}/diagnostic`),
};

/** The shared CA certificate every virtual printer presents — imported once
 *  into the slicer's trust store. Only the public certificate is returned. */





// Pending Uploads API
export const pendingUploadsApi = {
  list: () => request<PendingUpload[]>('/pending-uploads/'),

  getCount: () => request<{ count: number }>('/pending-uploads/count'),

  get: (id: number) => request<PendingUpload>(`/pending-uploads/${id}`),

  archive: (id: number, data?: { tags?: string; notes?: string; project_id?: number }) =>
    request<{ id: number; print_name: string; filename: string }>(`/pending-uploads/${id}/archive`, {
      method: 'POST',
      body: JSON.stringify(data || {}),
    }),

  discard: (id: number) =>
    request<{ success: boolean }>(`/pending-uploads/${id}`, { method: 'DELETE' }),

  archiveAll: () =>
    request<{ archived: number; failed: number }>('/pending-uploads/archive-all', { method: 'POST' }),

  discardAll: () =>
    request<{ discarded: number }>('/pending-uploads/discard-all', { method: 'DELETE' }),
};

// Firmware API Types




// Firmware API
export const firmwareApi = {
  checkUpdates: () =>
    request<{ updates: FirmwareUpdateInfo[]; updates_available: number }>('/firmware/updates'),

  checkPrinterUpdate: (printerId: number) =>
    request<FirmwareUpdateInfo>(`/firmware/updates/${printerId}`),

  prepareUpload: (printerId: number, version?: string) =>
    request<FirmwareUploadPrepare>(
      `/firmware/updates/${printerId}/prepare${version ? `?version=${encodeURIComponent(version)}` : ''}`,
    ),

  startUpload: (printerId: number, version?: string) =>
    request<{ started: boolean; message: string }>(
      `/firmware/updates/${printerId}/upload${version ? `?version=${encodeURIComponent(version)}` : ''}`,
      { method: 'POST' },
    ),

  getUploadStatus: (printerId: number) =>
    request<FirmwareUploadStatus>(`/firmware/updates/${printerId}/upload/status`),
};

// Support types



// Support API
export const supportApi = {
  getDebugLoggingState: () =>
    request<DebugLoggingState>('/support/debug-logging'),

  setDebugLogging: (enabled: boolean) =>
    request<DebugLoggingState>('/support/debug-logging', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  downloadSupportBundle: async () => {
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/support/bundle`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    // Get filename from Content-Disposition header or use default
    const disposition = response.headers.get('Content-Disposition');
    const filename = parseContentDispositionFilename(disposition) || 'printlab-support.zip';

    // Download the blob
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },

  getLogs: (params?: { limit?: number; level?: string; search?: string }) => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.set('limit', params.limit.toString());
    if (params?.level) searchParams.set('level', params.level);
    if (params?.search) searchParams.set('search', params.search);
    const query = searchParams.toString();
    return request<LogsResponse>(`/support/logs${query ? `?${query}` : ''}`);
  },

  clearLogs: () =>
    request<{ message: string }>('/support/logs', { method: 'DELETE' }),
};

// SpoolBuddy types


// SpoolBuddy API
export const spoolbuddyApi = {
  getDevices: () =>
    request<SpoolBuddyDevice[]>('/spoolbuddy/devices'),

  deleteDevice: (deviceId: string) =>
    request<{ status: string; device_id: string }>(`/spoolbuddy/devices/${deviceId}`, {
      method: 'DELETE',
    }),

  tare: (deviceId: string) =>
    request<{ status: string }>(`/spoolbuddy/devices/${deviceId}/calibration/tare`, {
      method: 'POST',
      body: '{}',
    }),

  getCalibration: (deviceId: string) =>
    request<{ tare_offset: number; calibration_factor: number }>(`/spoolbuddy/devices/${deviceId}/calibration`),

  setCalibrationFactor: (deviceId: string, knownWeightGrams: number, rawAdc: number, tareRawAdc?: number) =>
    request<{ tare_offset: number; calibration_factor: number }>(`/spoolbuddy/devices/${deviceId}/calibration/set-factor`, {
      method: 'POST',
      body: JSON.stringify({ known_weight_grams: knownWeightGrams, raw_adc: rawAdc, tare_raw_adc: tareRawAdc }),
    }),

  updateSpoolWeight: (spoolId: number, weightGrams: number) =>
    request<{ status: string; weight_used: number }>('/spoolbuddy/scale/update-spool-weight', {
      method: 'POST',
      body: JSON.stringify({ spool_id: spoolId, weight_grams: weightGrams }),
    }),

  updateDisplay: (deviceId: string, brightness: number, blankTimeout: number) =>
    request<{ status: string }>(`/spoolbuddy/devices/${deviceId}/display`, {
      method: 'PUT',
      body: JSON.stringify({ brightness, blank_timeout: blankTimeout }),
    }),

  updateSystemConfig: (deviceId: string, backendUrl: string, apiKey?: string) =>
    request<{ status: string; message: string }>(`/spoolbuddy/devices/${deviceId}/system/config`, {
      method: 'POST',
      body: JSON.stringify({ backend_url: backendUrl, ...(apiKey ? { api_key: apiKey } : {}) }),
    }),

  checkDaemonUpdate: (deviceId: string) =>
    request<DaemonUpdateCheck>(`/spoolbuddy/devices/${deviceId}/update-check`),

  triggerUpdate: (deviceId: string) =>
    request<{ status: string; message: string }>(`/spoolbuddy/devices/${deviceId}/update`, {
      method: 'POST',
      body: '{}',
    }),

  getSSHPublicKey: () =>
    request<{ public_key: string }>('/spoolbuddy/ssh/public-key'),

  writeTag: (deviceId: string, spoolId: number) =>
    request<{ status: string; warnings?: string[] }>('/spoolbuddy/nfc/write-tag', {
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId, spool_id: spoolId }),
    }),

  cancelWrite: (deviceId: string) =>
    request<{ status: string }>(`/spoolbuddy/devices/${deviceId}/cancel-write`, {
      method: 'POST',
      body: '{}',
    }),

  systemCommand: (deviceId: string, command: 'reboot' | 'shutdown' | 'restart_daemon' | 'restart_browser') =>
    request<{ status: string; command: string }>(`/spoolbuddy/devices/${deviceId}/system/command`, {
      method: 'POST',
      body: JSON.stringify({ command }),
    }),

  queueDiagnostics: (deviceId: string, type: 'nfc' | 'scale' | 'read_tag') =>
    request<{ status: string; diagnostic: string; message: string }>(
      `/spoolbuddy/diagnostics/${deviceId}/run?diagnostic=${type}`,
      { method: 'POST', body: '{}' }
    ),

  getDiagnosticResult: (deviceId: string, type: 'nfc' | 'scale' | 'read_tag') =>
    request<{ diagnostic: string; success: boolean; output: string; exit_code: number }>(
      `/spoolbuddy/diagnostics/${deviceId}/result?diagnostic=${type}`,
      { method: 'GET' }
    ),
};



export const bugReportApi = {
  status: () => request<{ enabled: boolean }>('/bug-report/status'),
  submit: (data: BugReportRequest) =>
    request<BugReportResponse>('/bug-report/submit', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  startLogging: () =>
    request<{ started: boolean; was_debug: boolean }>('/bug-report/start-logging', {
      method: 'POST',
    }),
  stopLogging: (wasDebug: boolean) =>
    request<{ logs: string }>(`/bug-report/stop-logging?was_debug=${wasDebug}`, {
      method: 'POST',
    }),
};



// One message from the PrintLab maintainers. `texts` holds every language the
// message was written in; English is always there.

// `visible` says whether this user may see announcements at all (switched on,
// and admin or "show to all users"); it keeps the sidebar entry while nothing
// is published.

export const announcementsApi = {
  list: () => request<AnnouncementList>('/announcements'),
  markRead: (id: string) =>
    request<void>(`/announcements/${encodeURIComponent(id)}/read`, { method: 'POST' }),
};



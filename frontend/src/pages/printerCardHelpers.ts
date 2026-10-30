/**
 * Konstanten, Typen und reine Funktionen der Druckerkarte.
 *
 * Getrennt von PrinterCardParts.tsx, damit dort nur Komponenten stehen
 * (Fast Refresh) und die Karte selbst wieder eine reine Komponentendatei wird.
 */

import { type DryingPreset } from '../utils/dryingPresets';
import { NOZZLE_TEMP_DEFAULTS, buildPresetOptions } from '../utils/temperatureFanPresets';
import type { HMSError } from '../api/client';
import { type PrinterState } from '../components/BulkPrinterToolbar';
import { filterKnownHMSErrors } from '../components/HMSErrorModal';

export const DRYING_POPOVER_WIDTH = 240;
// Height in "now" mode plus the tallest start-mode control; a conservative
// over-estimate just flips the popover above the trigger sooner.
export const DRYING_POPOVER_ESTIMATED_HEIGHT = 440;
// Delay presets for the "After delay" drying start mode, in minutes.
export const DRYING_DELAY_OPTIONS = [30, 60, 120, 240, 480, 720, 1440];

// Every printer card reads the same fleet-wide scheduled-drying list.
export const SCHEDULED_DRYINGS_KEY = ['scheduled-dryings'] as const;

// Why a due run has not started yet: every waiting_reason the scheduler can
// set. An unmapped one leaves the card showing a bare "Drying scheduled
// for ..." with no hint why nothing is happening.
export const WAITING_REASON_KEYS: Record<string, string> = {
  ams_power_required: 'printers.drying.powerRequired',
  ams_retract_filament: 'printers.drying.retractFilament',
  ams_blocked: 'printers.drying.cannotDryNow',
  ams_not_found: 'printers.drying.waitingAmsNotFound',
  printer_offline: 'printers.drying.waitingOffline',
  printer_busy: 'printers.drying.waitingPrinterBusy',
  already_drying: 'printers.drying.waitingAlreadyDrying',
  interrupted: 'printers.drying.waitingInterrupted',
};
export function waitingReasonKey(reason: string | null | undefined): string | undefined {
  return reason ? WAITING_REASON_KEYS[reason] : undefined;
}

// Why a scheduled drying failed, by the code the scheduler stores. A row with
// no code (failed before codes existed) or an unknown one shows the backend's
// English error_message instead.
export const FAILED_REASON_KEYS: Record<string, string> = {
  screen_only: 'printers.drying.screenOnly',
  unsupported: 'printers.drying.notSupported',
  did_not_start: 'printers.drying.scheduleFailedDidNotStart',
};
export function failedReasonKey(code: string | null | undefined): string | undefined {
  return code ? FAILED_REASON_KEYS[code] : undefined;
}

// Which cannot-dry code to name when the firmware reports several at once.
// Same priority as the backend's drying_preflight.primary_reason_code, so the
// button's tooltip and a scheduled row's waiting reason describe one blocked
// AMS the same way: codes 1 and 8 are a power-supply problem, 3 is filament
// left at the outlet, and both need the user to go and do something. The rest
// (AMS busy, cooling down) clear by themselves and share the generic wording.
export function dryingBlockedKey(reasons: Array<number | string> | undefined): string {
  const codes = (reasons ?? []).map(r => Number(r));
  if (codes.some(c => c === 1 || c === 8)) return 'printers.drying.powerRequired';
  if (codes.includes(3)) return 'printers.drying.retractFilament';
  return 'printers.drying.cannotDryNow';
}

// Aliased: lucide-react already exports a `Link` icon into this module.

// The status filter's options, and the only values it may hold. One list so a
// saved filter cannot be validated against a set the dropdown has since moved
// on from (#2833). Labels stay literal so they remain greppable.
export const STATUS_FILTER_OPTIONS = [
  { value: 'all', labelKey: 'printers.filter.allStatuses' },
  { value: 'printing', labelKey: 'printers.status.printing' },
  { value: 'paused', labelKey: 'printers.status.paused' },
  { value: 'idle', labelKey: 'printers.status.idle' },
  { value: 'finished', labelKey: 'printers.status.finished' },
  { value: 'error', labelKey: 'printers.status.error' },
  { value: 'offline', labelKey: 'printers.status.offline' },
] as const;
export function isKnownStatusFilter(value: string | null): boolean {
  return STATUS_FILTER_OPTIONS.some(option => option.value === value);
}
export interface SpoolmanSlotAssignmentRow {
  printer_id: number;
  ams_id: number;
  tray_id: number;
  spoolman_spool_id: number;
}

// Color names resolve via getColorName() which reads the backend color_catalog
// (loaded once by ColorCatalogProvider). No hardcoded tables here — see #857.

// Format K value with 3 decimal places, default to 0.020 if null
export function amsSideBadge(
  amsId: number,
  amsExtruderMap: Record<string, number>,
  amsSwitchInlet: Record<string, 'A' | 'B'>,
  ftsInstalled: boolean
): { kind: 'inlet'; inlet: 'A' | 'B' } | { kind: 'nozzle'; side: 'L' | 'R' } | null {
  const inlet = amsSwitchInlet[String(amsId)];
  if (inlet) return { kind: 'inlet', inlet };

  const mapped = amsExtruderMap[String(amsId)];
  const extruderId = mapped !== undefined ? mapped : ftsInstalled ? undefined : amsId >= 128 ? amsId - 128 : amsId;
  if (extruderId === 1) return { kind: 'nozzle', side: 'L' };
  if (extruderId === 0) return { kind: 'nozzle', side: 'R' };
  return null;
}

// Expand nozzle type codes to material names
// Handles full text ("hardened_steel"), 2-char codes ("HS"/"HH"), and 4-char codes ("HS01")
// Material mapping: 00=stainless steel, 01=hardened steel, 05=tungsten carbide
export function nozzleTypeName(type: string, t: (key: string) => string): string {
  if (!type) return '';
  // Full text names (from main nozzle info)
  if (type.includes('hardened')) return t('printers.nozzleHardenedSteel');
  if (type.includes('stainless')) return t('printers.nozzleStainlessSteel');
  if (type.includes('tungsten')) return t('printers.nozzleTungstenCarbide');
  // 4-char codes (e.g. "HS01"): last 2 digits = material
  if (type.length >= 4) {
    const material = type.slice(2, 4);
    if (material === '00') return t('printers.nozzleStainlessSteel');
    if (material === '01') return t('printers.nozzleHardenedSteel');
    if (material === '05') return t('printers.nozzleTungstenCarbide');
  }
  // 2-digit numeric codes
  if (type === '00') return t('printers.nozzleStainlessSteel');
  if (type === '01') return t('printers.nozzleHardenedSteel');
  if (type === '05') return t('printers.nozzleTungstenCarbide');
  // 2-char alpha codes: H prefix = hardened steel
  if (type.startsWith('H')) return t('printers.nozzleHardenedSteel');
  return type;
}

// Parse flow type from nozzle type code
// HH = high flow, HS = standard/normal
export function nozzleFlowName(type: string, t: (key: string) => string): string {
  if (!type) return '';
  if (type.startsWith('HH')) return t('printers.nozzleHighFlow');
  if (type.startsWith('HS')) return t('printers.nozzleStandardFlow');
  return '';
}

// Per-slot hover card for nozzle rack
// activeStatus: when true, show "Active" instead of "Mounted"/"Docked" (for hotend nozzles)
export const DRY_START_CONFIRM_MS = 30_000;
export interface PrinterMaintenanceInfo {
  due_count: number;
  warning_count: number;
  total_print_hours: number;
}

// Status summary bar component - uses queryClient to read cached statuses
export type SortOption = 'name' | 'status' | 'model' | 'location' | 'eta';
export type ViewMode = 'expanded' | 'compact';
export type ToolbarDropdownOption<T extends string> = {
  value: T;
  label: string;
};
export const NOZZLE_TEMPERATURE_OPTIONS = buildPresetOptions(NOZZLE_TEMP_DEFAULTS, 'C');
export const STATUS_GROUP_ORDER: string[] = ['error', 'printing', 'paused', 'finished', 'idle', 'offline'];
export const STATUS_GROUP_META: Record<string, { labelKey: string; dot: string }> = {
  error:    { labelKey: 'printers.status.problem',   dot: 'bg-status-error' },
  printing: { labelKey: 'printers.status.printing',  dot: 'bg-bambu-green animate-pulse' },
  paused:   { labelKey: 'printers.status.paused',    dot: 'bg-status-warning' },
  finished: { labelKey: 'printers.status.finished',  dot: 'bg-blue-400' },
  idle:     { labelKey: 'printers.status.idle',       dot: 'bg-bambu-green' },
  offline:  { labelKey: 'printers.status.offline',   dot: 'bg-gray-400' },
};

/** Classify a printer into one of the UI status buckets. */
export function classifyPrinterStatus(
  status: { connected: boolean; state: string | null; hms_errors?: HMSError[] } | undefined,
): PrinterState {
  if (!status?.connected) return 'offline';
  const hmsErrors = status.hms_errors ? filterKnownHMSErrors(status.hms_errors) : [];
  if (hmsErrors.length > 0) return 'error';
  switch (status.state) {
    case 'RUNNING': return 'printing';
    case 'PAUSE':   return 'paused';
    case 'FINISH':  return 'finished';
    // FAILED without an active HMS error is the printer's terminal state after
    // any unsuccessful end — including user-cancellations. Treat the same as
    // FINISH for grouping/badging purposes; only escalate to "error" when an
    // HMS code is actually attached (handled by the early-return above).
    case 'FAILED':  return 'finished';
    default:        return 'idle';
  }
}

/**
 * Get human-readable status display text for a printer.
 * Uses stg_cur_name for detailed calibration/preparation stages,
 * otherwise formats the gcode_state nicely.
 */
export function getStatusDisplay(state: string | null | undefined, stg_cur_name: string | null | undefined): string {
  // If we have a specific stage name (calibration, heating, etc.), use it
  if (stg_cur_name) {
    return stg_cur_name;
  }

  // Format the gcode_state nicely
  switch (state) {
    case 'RUNNING':
      return 'Printing';
    case 'PAUSE':
      return 'Paused';
    case 'FINISH':
      return 'Finished';
    case 'FAILED':
      return 'Failed';
    case 'IDLE':
      return 'Idle';
    default:
      return state ? state.charAt(0) + state.slice(1).toLowerCase() : 'Idle';
  }
}

// Bambu models that ship with an enclosure chamber fan (firmware field
// `big_fan2_speed`). Open-frame models (A1 / A1 Mini / A2L / P1P) have no
// chamber fan — `big_fan2_speed` is meaningless / always 0 there, so the
// widget is hidden in fanItems instead of rendered greyed-out.
export const MODELS_WITH_CHAMBER_FAN: ReadonlySet<string> = new Set([
  'X1C',
  'X1',
  'X1E',
  'X2D',
  'P1S',
  'P2S',
  'H2D',
  'H2D Pro',
  'H2C',
  'H2S',
]);

// On the P2S/X2D, the enclosure fan (big_fan2 / airduct part id 3) is a
// dedicated chamber EXHAUST fan: it's its own control and stays the same
// regardless of cooling/heating mode (unlike the aux fan, id 2, which a flap
// re-tasks between part-cooling and chamber-filter recirculation). Bambu's own
// firmware/UI and Bambu Studio (FAN_CHAMBER_0_IDX -> "Exhaust") label it
// "Exhaust" on these models. Other enclosed models (X1/P1S/H2*) keep "Chamber".
export const MODELS_WITH_EXHAUST_LABEL: ReadonlySet<string> = new Set([
  'P2S',
  'X2D',
]);

// ─── AMS Name Hover Card ──────────────────────────────────────────────────────
// Wraps the AMS label (e.g. "AMS-A") and shows a popup with:
//  • User-defined friendly name (editable, protected by printers:update)
//  • AMS serial number
//  • AMS firmware version
export const DRYING_PRESETS: Record<string, DryingPreset> = {
  'PLA':   { n3f: 45, n3s: 45, n3f_hours: 12, n3s_hours: 12 },
  'PETG':  { n3f: 65, n3s: 65, n3f_hours: 12, n3s_hours: 12 },
  'TPU':   { n3f: 65, n3s: 75, n3f_hours: 12, n3s_hours: 18 },
  'ABS':   { n3f: 65, n3s: 80, n3f_hours: 12, n3s_hours: 8 },
  'ASA':   { n3f: 65, n3s: 80, n3f_hours: 12, n3s_hours: 8 },
  'PA':    { n3f: 65, n3s: 85, n3f_hours: 12, n3s_hours: 12 },
  'PC':    { n3f: 65, n3s: 80, n3f_hours: 12, n3s_hours: 8 },
  'PVA':   { n3f: 65, n3s: 85, n3f_hours: 12, n3s_hours: 18 },
};

// How much the printer card's body type and icons grow at each card size
// (#1848). S is the dense fleet view and M is the default, so both stay at
// 1.0 and an existing install looks identical until the user picks L or XL --
// the same control the request asked to have this follow.
export const CARD_BODY_SCALE: Record<number, number> = { 1: 1, 2: 1, 3: 1.2, 4: 1.4 };

// The scaled sizes, handed to the card subtree as custom properties. Every
// converted class names its old fixed value as the fallback, so anything that
// renders outside a card root -- the portalled temperature popover -- keeps
// exactly the size it has today.
export function buildCardScaleStyle(cardSize: number): React.CSSProperties {
  const scale = CARD_BODY_SCALE[cardSize] ?? 1;
  // Rounded to a tenth so the values stay readable in devtools.
  const px = (base: number) => `${Math.round(base * scale * 10) / 10}px`;
  return {
    '--pc-t8': px(8),
    '--pc-t9': px(9),
    '--pc-t10': px(10),
    '--pc-t11': px(11),
    '--pc-i2': px(8),
    '--pc-i25': px(10),
    '--pc-i3': px(12),
    '--pc-i35': px(14),
    '--pc-i4': px(16),
    '--pc-i5': px(20),
    '--pc-i7': px(28),
  } as React.CSSProperties;
}

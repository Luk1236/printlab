/**
 * Anzeigen der Druckerkarte, die nur sie benutzt.
 *
 * Aus PrintersPage.tsx ausgelagert. Werte und reine Funktionen liegen in
 * printerCardHelpers.ts, damit diese Datei nur Komponenten exportiert.
 */

import { useState, useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { computePopoverPosition } from '../utils/popoverPosition';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ChevronDown, X } from 'lucide-react';
import { api } from '../api/client';
import { formatDateTime, formatDuration } from '../utils/date';
import type { Printer, HMSError } from '../api/client';
import { filterKnownHMSErrors } from '../components/HMSErrorModal';
import { useToast } from '../contexts/ToastContext';
import { parseFilamentColor, isLightColor } from '../utils/colors';

import {
  NOZZLE_TEMPERATURE_OPTIONS,
  SCHEDULED_DRYINGS_KEY,
  type ToolbarDropdownOption,
  failedReasonKey,
  nozzleFlowName,
  nozzleTypeName,
  waitingReasonKey
} from './printerCardHelpers';

export function NozzleSlotHoverCard({ slot, index, activeStatus, filamentName, children }: {
  slot: import('../api/client').NozzleRackSlot;
  index: number;
  activeStatus?: boolean;
  filamentName?: string;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<'top' | 'bottom'>('top');
  const triggerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isEmpty = !slot.nozzle_diameter && !slot.nozzle_type;
  const isMounted = slot.stat === 1;

  useEffect(() => {
    if (isVisible && triggerRef.current && cardRef.current) {
      const triggerRect = triggerRef.current.getBoundingClientRect();
      const cardHeight = cardRef.current.offsetHeight;
      const headerHeight = 56;
      const spaceAbove = triggerRect.top - headerHeight;
      const spaceBelow = window.innerHeight - triggerRect.bottom;
      if (spaceAbove < cardHeight + 12 && spaceBelow > spaceAbove) {
        setPosition('bottom');
      } else {
        setPosition('top');
      }
    }
  }, [isVisible]);

  const handleMouseEnter = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setIsVisible(true), 80);
  };

  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setIsVisible(false), 100);
  };

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const filamentCss = parseFilamentColor(slot.filament_color);
  const typeFull = nozzleTypeName(slot.nozzle_type, t);
  const flowFull = nozzleFlowName(slot.nozzle_type, t);

  return (
    <div
      ref={triggerRef}
      className="relative"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}

      {isVisible && (
        <div
          ref={cardRef}
          className={`
            absolute left-1/2 -translate-x-1/2 z-50
            ${position === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'}
            animate-in fade-in-0 zoom-in-95 duration-150
          `}
          style={{ maxWidth: 'calc(100vw - 24px)' }}
        >
          <div className="w-44 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-xl overflow-hidden backdrop-blur-sm">
            {isEmpty ? (
              <div className="px-3 py-2 text-xs text-bambu-gray text-center whitespace-nowrap">
                Slot {index + 1} — Empty
              </div>
            ) : (
              <div className="p-2.5 space-y-1.5">
                {/* Diameter */}
                <div className="flex items-center justify-between">
                  <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleDiameter')}</span>
                  <span className="text-xs text-white font-semibold">{slot.nozzle_diameter} mm</span>
                </div>

                {/* Type */}
                {typeFull && (
                  <div className="flex items-center justify-between">
                    <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleType')}</span>
                    <span className="text-xs text-white font-semibold truncate max-w-[100px]">{typeFull}</span>
                  </div>
                )}

                {/* Flow (hide if empty) */}
                {flowFull && (
                  <div className="flex items-center justify-between">
                    <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleFlow')}</span>
                    <span className="text-xs text-white font-semibold">{flowFull}</span>
                  </div>
                )}

                {/* Status badge */}
                <div className="flex items-center justify-between">
                  <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleStatus')}</span>
                  <span className={`text-[length:var(--pc-t10,10px)] font-bold px-1.5 py-0.5 rounded ${
                    activeStatus || isMounted
                      ? 'bg-green-900/50 text-green-400'
                      : 'bg-bambu-dark-tertiary text-bambu-gray'
                  }`}>
                    {activeStatus ? t('printers.nozzleActive') : isMounted ? t('printers.nozzleMounted') : t('printers.nozzleDocked')}
                  </span>
                </div>

                {/* Wear (hide if null) */}
                {slot.wear != null && (
                  <div className="flex items-center justify-between">
                    <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleWear')}</span>
                    <span className="text-xs text-white font-semibold">{slot.wear}%</span>
                  </div>
                )}

                {/* Max Temp (hide if 0) */}
                {slot.max_temp > 0 && (
                  <div className="flex items-center justify-between">
                    <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleMaxTemp')}</span>
                    <span className="text-xs text-white font-semibold">{slot.max_temp}°C</span>
                  </div>
                )}

                {/* Serial (hide if empty) */}
                {slot.serial_number && (
                  <div className="flex items-center justify-between">
                    <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleSerial')}</span>
                    <span className="text-[length:var(--pc-t10,10px)] text-white font-mono truncate max-w-[80px]">{slot.serial_number}</span>
                  </div>
                )}

                {/* Filament: material type + color swatch (hide if no color) */}
                {(filamentCss || slot.filament_type) && (
                  <div className="flex items-center justify-between">
                    <span className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{t('printers.nozzleFilament')}</span>
                    <div className="flex items-center gap-1">
                      {filamentCss && (
                        <div className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)] rounded-sm border border-white/20" style={{ backgroundColor: filamentCss }} />
                      )}
                      <span className="text-[length:var(--pc-t10,10px)] text-white font-semibold truncate max-w-[100px]">{filamentName || slot.filament_type || slot.filament_id || ''}</span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Arrow pointer */}
          <div
            className={`
              absolute left-1/2 -translate-x-1/2 w-0 h-0
              border-l-[6px] border-l-transparent
              border-r-[6px] border-r-transparent
              ${position === 'top'
                ? 'top-full border-t-[6px] border-t-bambu-dark-tertiary'
                : 'bottom-full border-b-[6px] border-b-bambu-dark-tertiary'}
            `}
          />
        </div>
      )}
    </div>
  );
}

// Dual-nozzle hover card showing L and R nozzle details side by side
export function DualNozzleHoverCard({ leftSlot, rightSlot, activeNozzle, filamentInfo, children }: {
  leftSlot?: import('../api/client').NozzleRackSlot;
  rightSlot?: import('../api/client').NozzleRackSlot;
  activeNozzle: 'L' | 'R';
  filamentInfo?: Record<string, { name: string; k: number | null }>;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<'top' | 'bottom'>('top');
  const triggerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isVisible && triggerRef.current && cardRef.current) {
      const triggerRect = triggerRef.current.getBoundingClientRect();
      const cardHeight = cardRef.current.offsetHeight;
      const headerHeight = 56;
      const spaceAbove = triggerRect.top - headerHeight;
      const spaceBelow = window.innerHeight - triggerRect.bottom;
      if (spaceAbove < cardHeight + 12 && spaceBelow > spaceAbove) {
        setPosition('bottom');
      } else {
        setPosition('top');
      }
    }
  }, [isVisible]);

  const handleMouseEnter = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setIsVisible(true), 80);
  };

  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setIsVisible(false), 100);
  };

  useEffect(() => {
    return () => { if (timeoutRef.current) clearTimeout(timeoutRef.current); };
  }, []);

  if (!leftSlot && !rightSlot) return <>{children}</>;

  const renderColumn = (slot: import('../api/client').NozzleRackSlot, side: 'L' | 'R') => {
    const isActive = activeNozzle === side;
    const typeFull = nozzleTypeName(slot.nozzle_type, t);
    const flowFull = nozzleFlowName(slot.nozzle_type, t);
    const filamentCss = parseFilamentColor(slot.filament_color);
    const filamentName = slot.filament_id ? filamentInfo?.[slot.filament_id]?.name : undefined;
    return (
      <div className="flex-1 space-y-1.5">
        <div className={`text-[length:var(--pc-t10,10px)] font-bold pb-1 border-b border-bambu-dark-tertiary/50 ${isActive ? 'text-amber-700 dark:text-amber-400' : 'text-bambu-gray'}`}>
          {side === 'L' ? t('common.left') : t('common.right')}
        </div>
        {slot.nozzle_diameter && (
          <div className="flex items-center justify-between">
            <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleDiameter')}</span>
            <span className="text-xs text-white font-semibold">{slot.nozzle_diameter} mm</span>
          </div>
        )}
        {typeFull && (
          <div className="flex items-center justify-between">
            <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleType')}</span>
            <span className="text-[length:var(--pc-t10,10px)] text-white font-semibold">{typeFull}</span>
          </div>
        )}
        {flowFull && (
          <div className="flex items-center justify-between">
            <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleFlow')}</span>
            <span className="text-[length:var(--pc-t10,10px)] text-white font-semibold">{flowFull}</span>
          </div>
        )}
        <div className="flex items-center justify-between">
          <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleStatus')}</span>
          <span className={`text-[length:var(--pc-t10,10px)] font-bold px-1.5 py-0.5 rounded ${
            isActive
              ? 'bg-green-900/50 text-green-400'
              : 'bg-bambu-dark-tertiary text-bambu-gray'
          }`}>
            {isActive ? t('printers.nozzleActive') : t('printers.nozzleIdle')}
          </span>
        </div>
        {slot.wear != null && (
          <div className="flex items-center justify-between">
            <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleWear')}</span>
            <span className="text-xs text-white font-semibold">{slot.wear}%</span>
          </div>
        )}
        {/* Serial and max temp only available on the right (removable) nozzle */}
        {side === 'R' && slot.max_temp > 0 && (
          <div className="flex items-center justify-between">
            <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleMaxTemp')}</span>
            <span className="text-xs text-white font-semibold">{slot.max_temp}°C</span>
          </div>
        )}
        {side === 'R' && slot.serial_number && (
          <div className="flex items-center justify-between">
            <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleSerial')}</span>
            <span className="text-[length:var(--pc-t10,10px)] text-white font-mono">{slot.serial_number}</span>
          </div>
        )}
        {(filamentCss || slot.filament_type || slot.filament_id) && (
          <div className="flex items-center justify-between">
            <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.nozzleFilament')}</span>
            <div className="flex items-center gap-1">
              {filamentCss && (
                <div className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)] rounded-sm border border-white/20" style={{ backgroundColor: filamentCss }} />
              )}
              <span className="text-[length:var(--pc-t10,10px)] text-white font-semibold truncate max-w-[100px]">
                {filamentName || slot.filament_type || slot.filament_id || ''}
              </span>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div
      ref={triggerRef}
      className="relative flex-1"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}

      {isVisible && (
        <div
          ref={cardRef}
          className={`
            absolute left-1/2 -translate-x-1/2 z-50
            ${position === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'}
            animate-in fade-in-0 zoom-in-95 duration-150
          `}
          style={{ maxWidth: 'calc(100vw - 24px)' }}
        >
          <div className="w-96 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-xl overflow-hidden backdrop-blur-sm">
            <div className="p-2.5 flex gap-3">
              {leftSlot && renderColumn(leftSlot, 'L')}
              {leftSlot && rightSlot && <div className="w-px bg-bambu-dark-tertiary/50" />}
              {rightSlot && renderColumn(rightSlot, 'R')}
            </div>
          </div>

          {/* Arrow pointer */}
          <div
            className={`
              absolute left-1/2 -translate-x-1/2 w-0 h-0
              border-l-[6px] border-l-transparent
              border-r-[6px] border-r-transparent
              ${position === 'top'
                ? 'top-full border-t-[6px] border-t-bambu-dark-tertiary'
                : 'bottom-full border-b-[6px] border-b-bambu-dark-tertiary'}
            `}
          />
        </div>
      )}
    </div>
  );
}

// H2C Nozzle Rack Card — compact single row showing 6-position tool-changer dock
export function NozzleRackCard({ slots, filamentInfo }: { slots: import('../api/client').NozzleRackSlot[]; filamentInfo?: Record<string, { name: string; k: number | null }> }) {
  const { t } = useTranslation();
  // Rack nozzles only (IDs >= 2) — excludes L/R hotend nozzles (IDs 0, 1).
  // H2C rack slot IDs are fixed at 16..21. When a nozzle is picked up into the
  // hotend the firmware omits that rack ID entirely, so we must map by the fixed
  // base — computing it from min(present IDs) shifts everything left when slot 16
  // is the one currently mounted (#943).
  const rackNozzles = slots.filter(s => s.id >= 2);
  const RACK_SIZE = 6;
  const RACK_BASE_ID = 16;
  const rackSlots: (import('../api/client').NozzleRackSlot)[] = Array.from(
    { length: RACK_SIZE },
    (_, i) => rackNozzles.find(s => s.id === RACK_BASE_ID + i) ?? {
      id: -(i + 1), nozzle_type: '', nozzle_diameter: '', wear: null, stat: null,
      max_temp: 0, serial_number: '', filament_color: '', filament_id: '', filament_type: '',
    },
  );

  return (
    // Sized to its contents rather than growing: the six chips are a fixed
    // width at any one card size, so extra width would be dead space taken
    // from the temperature cards beside it — which are flex-1 with a 0 basis
    // and wrap their values ("220° / 220°") as soon as they lose it. Shrink
    // stays enabled so the card still gives way on a narrow printer card
    // instead of overflowing.
    <div className="text-center px-2.5 py-1.5 bg-bambu-dark rounded-lg flex-[0_1_auto] flex flex-col justify-center">
      <p className="text-[length:var(--pc-t9,9px)] text-bambu-gray mb-1">{t('printers.nozzleRack')}</p>
      <div className="flex gap-[3px] justify-center">
        {rackSlots.map((slot, i) => {
          const isEmpty = !slot.nozzle_diameter && !slot.nozzle_type;
          const filamentBg = !isEmpty ? parseFilamentColor(slot.filament_color) : null;
          const lightBg = filamentBg ? isLightColor(slot.filament_color) : false;

          return (
            <NozzleSlotHoverCard key={slot.id >= 0 ? slot.id : `empty-${i}`} slot={slot} index={i} filamentName={slot.filament_id ? filamentInfo?.[slot.filament_id]?.name : undefined}>
              <div className="flex flex-col items-center gap-0.5">
                <div
                  className={`w-[var(--pc-i7,28px)] h-[var(--pc-i7,28px)] rounded flex items-center justify-center cursor-default transition-colors border-b-2 ${
                    isEmpty
                      ? 'bg-bambu-dark-tertiary/20 border-bambu-dark-tertiary/20'
                      : 'bg-bambu-dark-tertiary/40 border-bambu-dark-tertiary/40'
                  }`}
                  style={filamentBg ? { backgroundColor: filamentBg } : undefined}
                >
                  <span
                    data-rack-diameter
                    className={`text-[length:var(--pc-t10,10px)] font-semibold ${isEmpty ? 'text-bambu-gray/30' : lightBg ? 'text-black/80' : 'text-white'}`}
                    style={filamentBg && !lightBg ? { textShadow: '0 1px 3px rgba(0,0,0,0.9)' } : undefined}
                  >
                    {isEmpty ? '—' : (slot.nozzle_diameter || '?')}
                  </span>
                </div>
                {/* Physical rack position, so "swap the nozzle in slot 4" can be
                    acted on without counting chips. Sits below the chip rather
                    than inside it: the chip is barely wider than its own
                    diameter text and already carries that over a
                    filament-coloured background. */}
                <span className="text-[length:var(--pc-t8,8px)] leading-none tabular-nums text-bambu-gray/70">
                  {i + 1}
                </span>
              </div>
            </NozzleSlotHoverCard>
          );
        })}
      </div>
    </div>
  );
}

// Water drop SVG - empty outline (Bambu Lab style from bambu-humidity)
// How long to wait for an AMS to report a live drying cycle after the printer
// acked the start command (#2533). Firmware moves to DryStatus 1 (Checking)
// within a couple of seconds; 30s covers the slowest observed push cadence
// without leaving the user waiting on a verdict.
export function StatusSummaryBar({ printers }: { printers: Printer[] | undefined }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  // Subscribe to query cache changes to re-render when status updates
  // Throttled to prevent rapid re-renders from causing tab crashes
  const [cacheTick, setCacheTick] = useState(0);
  useEffect(() => {
    let pending = false;
    const unsubscribe = queryClient.getQueryCache().subscribe(() => {
      if (!pending) {
        pending = true;
        requestAnimationFrame(() => {
          setCacheTick(t => t + 1);
          pending = false;
        });
      }
    });
    return () => unsubscribe();
  }, [queryClient]);

  const { counts, nextFinish } = useMemo(() => {
    let printing = 0;
    let paused = 0;
    let finished = 0;
    let idle = 0;
    let offline = 0;
    let loading = 0;
    let error = 0;
    let nextPrinterName: string | null = null;
    let nextRemainingMin: number | null = null;
    let nextProgress: number = 0;

    printers?.forEach((printer) => {
      const status = queryClient.getQueryData<{ connected: boolean; state: string | null; remaining_time: number | null; progress: number | null; hms_errors?: HMSError[] }>(['printerStatus', printer.id]);
      if (status === undefined) {
        // Status not yet loaded - don't count as offline yet
        loading++;
      } else if (!status.connected) {
        offline++;
      } else {
        // Count printers with active HMS errors as problems
        const knownHmsCount =
          status.hms_errors ? filterKnownHMSErrors(status.hms_errors).length : 0;
        if (knownHmsCount > 0) {
          error++;
        }
        switch (status.state) {
          case 'RUNNING':
            printing++;
            if (status.remaining_time != null && status.remaining_time > 0) {
              if (nextRemainingMin === null || status.remaining_time < nextRemainingMin) {
                nextRemainingMin = status.remaining_time;
                nextPrinterName = printer.name;
                nextProgress = status.progress || 0;
              }
            }
            break;
          case 'PAUSE':
            paused++;
            break;
          case 'FINISH':
            finished++;
            break;
          case 'FAILED':
            // FAILED is the printer's terminal gcode_state after a print stops —
            // including user cancellations, where there's no actual fault. Only
            // count it as a "problem" when an HMS error is also active; otherwise
            // it's just a print that ended unsuccessfully and the plate needs
            // clearing (same as FINISH from the operator's perspective).
            if (knownHmsCount > 0) {
              // Already counted above
            } else {
              finished++;
            }
            break;
          default:
            idle++;
            break;
        }
      }
    });

    return {
      counts: { printing, paused, finished, idle, offline, loading, error, total: (printers?.length || 0) },
      nextFinish: nextPrinterName && nextRemainingMin ? { name: nextPrinterName, remainingMin: nextRemainingMin, progress: nextProgress } : null,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [printers, queryClient, cacheTick]);

  if (!printers?.length) return null;

  const badges: { count: number; dot: string; label: string }[] = [
    { count: counts.printing, dot: 'bg-bambu-green animate-pulse', label: t('printers.status.printing').toLowerCase() },
    { count: counts.paused, dot: 'bg-status-warning', label: t('printers.status.paused', 'paused').toLowerCase() },
    { count: counts.finished, dot: 'bg-blue-400', label: t('printers.status.finished', 'finished').toLowerCase() },
    { count: counts.idle, dot: counts.idle > 0 ? 'bg-bambu-green' : 'bg-gray-500', label: t('printers.status.available').toLowerCase() },
    { count: counts.error, dot: 'bg-status-error', label: t('printers.status.problem').toLowerCase() },
    { count: counts.offline, dot: 'bg-gray-400', label: t('printers.status.offline').toLowerCase() },
  ];

  return (
    <div className="mt-1 flex flex-wrap items-center gap-4 gap-y-2 text-bambu-gray">
      {badges.map(({ count, dot, label }) => count > 0 && (
        <div key={label} className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${dot}`} />
          <span className="text-bambu-gray">
            <span className="text-white font-medium">{count}</span> {label}
          </span>
        </div>
      ))}
      {nextFinish && (
        <>
          <div className="w-px h-4 bg-bambu-dark-tertiary" />
          <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2">
            <div className="flex items-center gap-2">
              <span className="text-bambu-green font-medium">{t('printers.nextAvailable')}:</span>
              <span className="text-white font-medium">{nextFinish.name}</span>
            </div>
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <div className="w-full sm:w-16 bg-bambu-dark-tertiary rounded-full h-1.5">
                <div
                  className="bg-bambu-green h-1.5 rounded-full transition-all"
                  style={{ width: `${nextFinish.progress}%` }}
                />
              </div>
              <span className="text-white font-medium">{Math.round(nextFinish.progress)}%</span>
              <span className="text-bambu-gray">({formatDuration(nextFinish.remainingMin * 60)})</span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
export function ToolbarDropdown<T extends string>({
  value,
  options,
  onChange,
  fullWidth = false,
}: {
  value: T;
  options: ToolbarDropdownOption<T>[];
  onChange: (value: T) => void;
  fullWidth?: boolean;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedOption = options.find(option => option.value === value) ?? options[0];

  return (
    <div className={`relative ${fullWidth ? 'w-full min-w-0' : ''}`}>
      <button
        type="button"
        onClick={() => setIsOpen(open => !open)}
        className={`h-8 px-2 rounded-lg border bg-bambu-dark border-bambu-dark-tertiary text-white text-sm font-medium transition-colors hover:bg-bambu-dark-tertiary focus:outline-none focus:border-bambu-green flex items-center justify-between gap-2 ${fullWidth ? 'w-full' : 'min-w-28'}`}
      >
        <span className="truncate">{selectedOption?.label}</span>
        <ChevronDown className={`w-4 h-4 text-bambu-gray transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 min-w-full rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary py-1 shadow-xl">
            {options.map(option => (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  onChange(option.value);
                  setIsOpen(false);
                }}
                className={`w-full px-3 py-2 text-left text-sm transition-colors hover:bg-bambu-dark-tertiary ${
                  option.value === value ? 'text-bambu-green' : 'text-white'
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
export function ToolbarMenu({
  label,
  icon,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setIsOpen(open => !open)}
        className="h-8 w-8 rounded-lg border bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary transition-colors flex items-center justify-center"
        aria-label={label}
        title={label}
      >
        {icon}
      </button>

      {isOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setIsOpen(false)} />
          <div className="absolute right-0 top-full z-20 mt-1 min-w-40 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary p-2 shadow-xl">
            {children}
          </div>
        </>
      )}
    </div>
  );
}
export function IndicatorControlPopover({
  title,
  options = [],
  unit,
  customMin,
  customMax,
  customStep = 1,
  widthClass = 'w-[240px]',
  popoverWidth = 240,
  popoverHeight = 280,
  isPending,
  onClose,
  onSubmit,
  children,
}: {
  title: string;
  options?: Array<{ label: string; value: number }>;
  unit?: string;
  customMin?: number;
  customMax?: number;
  customStep?: number;
  widthClass?: string;
  popoverWidth?: number;
  popoverHeight?: number;
  isPending?: boolean;
  onClose: () => void;
  onSubmit?: (value: number) => void;
  children?: React.ReactNode;
}) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null);
  const [customValue, setCustomValue] = useState('');

  // Anchor to the trigger (the popover's DOM parent before portaling) so we
  // can position via fixed coords. Portaling to document.body escapes
  // ancestor stacking contexts — sibling PrinterCard wrappers create their
  // own contexts and would otherwise cover the popover even at z-[60].
  useLayoutEffect(() => {
    const trigger = anchorRef.current?.parentElement;
    if (!trigger) return;
    const measure = () => {
      const rect = trigger.getBoundingClientRect();
      setCoords(computePopoverPosition({
        triggerRect: rect,
        popoverWidth,
        estimatedHeight: popoverHeight,
        horizontalAlign: 'center',
      }));
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [popoverWidth, popoverHeight]);

  const showCustomInput = unit !== undefined;
  const submitCustom = () => {
    const value = Number(customValue);
    if (!Number.isFinite(value)) return;
    const bounded = Math.min(customMax ?? value, Math.max(customMin ?? value, value));
    onSubmit?.(Math.round(bounded));
  };

  return (
    <>
      <span ref={anchorRef} className="hidden" aria-hidden="true" />
      {createPortal(
        <>
          <div className="fixed inset-0 z-[1000]" onClick={onClose} />
          <div
            className={`fixed z-[1001] flex ${widthClass} flex-col overflow-hidden rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary shadow-2xl`}
            style={{
              top: coords?.top ?? -9999,
              left: coords?.left ?? -9999,
              visibility: coords ? 'visible' : 'hidden',
            }}
            onClick={e => e.stopPropagation()}
          >
        <div className="shrink-0 px-3 py-2.5 text-center text-sm font-medium text-white">{title}</div>
        <div className="shrink-0 h-px bg-bambu-dark-tertiary" />
        {options.length > 0 && (
          <div className="px-3 py-2.5">
            <div className="grid grid-cols-2 gap-1.5">
              {options.map(option => (
                <button
                  key={`${option.label}-${option.value}`}
                  type="button"
                  disabled={isPending}
                  onClick={() => onSubmit?.(option.value)}
                  className="h-8 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-2 text-xs font-medium text-white transition-colors hover:bg-bambu-dark-tertiary disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
        )}
        {children}
        {showCustomInput && (
          <>
            <div className="shrink-0 h-px bg-bambu-dark-tertiary" />
            <form
              className="flex gap-1.5 px-3 pt-2.5 pb-3"
              onSubmit={(e) => {
                e.preventDefault();
                submitCustom();
              }}
            >
              <input
                type="number"
                min={customMin}
                max={customMax}
                step={customStep}
                value={customValue}
                onChange={e => setCustomValue(e.target.value)}
                placeholder="Custom"
                className="h-8 min-w-0 flex-1 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-2 text-xs text-white placeholder:text-bambu-gray/60 focus:border-bambu-green focus:outline-none"
              />
              <button
                type="submit"
                disabled={isPending || customValue.trim() === ''}
                className="h-8 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-2 text-xs font-medium text-white transition-colors hover:bg-bambu-dark-tertiary disabled:cursor-not-allowed disabled:opacity-50"
              >
                Set
              </button>
            </form>
          </>
        )}
          </div>
        </>,
        document.body
      )}
    </>
  );
}
export function NozzleTemperatureControlBox({
  label,
  current,
  target,
  isActive,
  isPending,
  onSubmit,
  options = NOZZLE_TEMPERATURE_OPTIONS,
}: {
  label: string;
  current?: number;
  target?: number;
  isActive: boolean;
  isPending?: boolean;
  onSubmit: (value: number) => void;
  options?: Array<{ label: string; value: number }>;
}) {
  const [customValue, setCustomValue] = useState('');

  const submitCustom = () => {
    const value = Number(customValue);
    if (!Number.isFinite(value)) return;
    onSubmit(Math.min(320, Math.max(0, Math.round(value))));
  };

  return (
    <div className={`rounded-lg border p-2 ${isActive ? 'border-amber-500/60 dark:border-amber-400/60 bg-amber-50 dark:bg-amber-400/10' : 'border-bambu-dark-tertiary bg-bambu-dark'}`}>
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className={`text-xs font-medium ${isActive ? 'text-amber-700 dark:text-amber-300' : 'text-white'}`}>{label}</span>
        <span className="text-[10px] text-bambu-gray">
          {Math.round(current ?? 0)}°C
          {target !== undefined ? ` / ${Math.round(target)}°` : ''}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-1">
        {options.map(option => (
          <button
            key={`${label}-${option.value}`}
            type="button"
            disabled={isPending}
            onClick={() => onSubmit(option.value)}
            className="h-7 rounded-md border border-bambu-dark-tertiary bg-bambu-dark-secondary px-1.5 text-[11px] font-medium text-white transition-colors hover:bg-bambu-dark-tertiary disabled:cursor-not-allowed disabled:opacity-50"
          >
            {option.label}
          </button>
        ))}
      </div>
      <form
        className="mt-1.5 flex gap-1"
        onSubmit={(e) => {
          e.preventDefault();
          submitCustom();
        }}
      >
        <input
          type="number"
          min={0}
          max={320}
          step={1}
          value={customValue}
          onChange={e => setCustomValue(e.target.value)}
          placeholder="Custom"
          className="h-7 min-w-0 flex-1 rounded-md border border-bambu-dark-tertiary bg-bambu-dark-secondary px-1.5 text-[11px] text-white placeholder:text-bambu-gray/60 focus:border-bambu-green focus:outline-none"
        />
        <button
          type="submit"
          disabled={isPending || customValue.trim() === ''}
          className="h-7 rounded-md border border-bambu-dark-tertiary bg-bambu-dark-secondary px-2 text-[11px] font-medium text-white transition-colors hover:bg-bambu-dark-tertiary disabled:cursor-not-allowed disabled:opacity-50"
        >
          Set
        </button>
      </form>
    </div>
  );
}
export function AmsNameHoverCard({
  ams,
  printerId,
  label,
  amsLabels,
  canEdit,
  onSaved,
  children,
}: {
  ams: import('../api/client').AMSUnit;
  printerId: number;
  label: string;           // auto-generated label, e.g. "AMS-A"
  amsLabels?: Record<number, string>;
  canEdit: boolean;
  onSaved: () => void;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState<'top' | 'bottom'>('top');
  const [editValue, setEditValue] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isInputFocused, setIsInputFocused] = useState(false);
  const triggerRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLDivElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isVisible) {
      setEditValue(amsLabels?.[ams.id] ?? '');
      setSaveError(null);
      requestAnimationFrame(() => {
        if (triggerRef.current && cardRef.current) {
          const rect = triggerRef.current.getBoundingClientRect();
          const spaceAbove = rect.top - 56;
          const spaceBelow = window.innerHeight - rect.bottom;
          setPosition(spaceAbove < cardRef.current.offsetHeight + 12 && spaceBelow > spaceAbove ? 'bottom' : 'top');
        }
      });
    }
  }, [isVisible, amsLabels, ams.id]);

  const handleMouseEnter = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setIsVisible(true), 80);
  };
  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    if (!isInputFocused) {
      timeoutRef.current = setTimeout(() => setIsVisible(false), 200);
    }
  };
  useEffect(() => () => { if (timeoutRef.current) clearTimeout(timeoutRef.current); }, []);

  const handleSave = async () => {
    if (!canEdit) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      const trimmed = editValue.trim();
      if (trimmed) {
        await api.saveAmsLabel(printerId, ams.id, trimmed, ams.serial_number);
      } else {
        await api.deleteAmsLabel(printerId, ams.id, ams.serial_number);
      }
      onSaved();
      setIsVisible(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  const handleClear = async () => {
    if (!canEdit) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      await api.deleteAmsLabel(printerId, ams.id, ams.serial_number);
      onSaved();
      setIsVisible(false);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div
      ref={triggerRef}
      className="relative inline-block"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}

      {isVisible && (
        <div
          ref={cardRef}
          className={`
            absolute left-0 z-50
            ${position === 'top' ? 'bottom-full mb-2' : 'top-full mt-2'}
            animate-in fade-in-0 zoom-in-95 duration-150
          `}
          style={{ maxWidth: 'calc(100vw - 24px)' }}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          <div className="w-52 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg shadow-xl overflow-hidden backdrop-blur-sm p-2.5 space-y-2">
            {/* AMS auto-label */}
            <div className="text-[length:var(--pc-t10,10px)] uppercase tracking-wider text-bambu-gray font-medium">{label}</div>

            {/* Serial number */}
            <div className="flex items-center justify-between gap-2">
              <span className="text-[length:var(--pc-t10,10px)] tracking-wide text-bambu-gray font-medium shrink-0">
                {t('printers.amsPopup.serialNumber')}
              </span>
              <span className="text-[length:var(--pc-t10,10px)] text-white font-mono truncate">{ams.serial_number || '—'}</span>
            </div>

            {/* Firmware version */}
            <div className="flex items-center justify-between gap-2">
              <span className="text-[length:var(--pc-t10,10px)] tracking-wide text-bambu-gray font-medium shrink-0">
                {t('printers.amsPopup.firmwareVersion')}
              </span>
              <span className="text-[length:var(--pc-t10,10px)] text-white font-mono truncate">{ams.sw_ver || '—'}</span>
            </div>

            {/* Friendly name editor */}
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray font-medium shrink-0">
                  {t('printers.amsPopup.friendlyName')}
                </span>
                <div className="flex-1 h-[2px] bg-bambu-dark-tertiary/50" />
              </div>
              <input
                type="text"
                value={editValue}
                onChange={(e) => canEdit && setEditValue(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSave()}
                onFocus={() => setIsInputFocused(true)}
                onBlur={() => {
                  setIsInputFocused(false);
                  if (timeoutRef.current) clearTimeout(timeoutRef.current);
                    timeoutRef.current = setTimeout(() => setIsVisible(false), 200);
                }}
                placeholder={canEdit ? t('printers.amsPopup.friendlyNamePlaceholder') : (amsLabels?.[ams.id] || '—')}
                disabled={!canEdit}
                title={!canEdit ? t('printers.amsPopup.noEditPermission') : undefined}
                className="w-full bg-bambu-dark border border-bambu-dark-tertiary rounded px-2 py-1 text-xs text-white placeholder-bambu-gray/60 focus:outline-none focus:border-bambu-green disabled:opacity-50 disabled:cursor-not-allowed"
                maxLength={100}
              />
              {canEdit && (
                <div className="space-y-1">
                  {saveError && (
                    <p className="text-[length:var(--pc-t10,10px)] text-red-700 dark:text-red-400 break-words">{saveError}</p>
                  )}
                  <div className="flex gap-1 justify-end">
                    <button
                      onClick={handleSave}
                      disabled={isSaving}
                      className="px-2 py-0.5 text-[length:var(--pc-t10,10px)] bg-bambu-green text-white rounded hover:bg-bambu-green/80 disabled:opacity-50"
                    >
                      {t('printers.amsPopup.save')}
                    </button>
                    {amsLabels?.[ams.id] && (
                      <button
                        onClick={handleClear}
                        disabled={isSaving}
                        className="px-2 py-0.5 text-[length:var(--pc-t10,10px)] bg-bambu-dark-tertiary text-bambu-gray rounded hover:bg-bambu-dark-tertiary/70 disabled:opacity-50"
                      >
                        {t('printers.amsPopup.clear')}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// AMS drying presets from BambuStudio filament profiles (idle mode temps)
// Format: { n3f temp, n3s temp, n3f hours, n3s hours }
export function ScheduledDryingBanner({ printerId, dryingActive, timeFormat }: { printerId: number; dryingActive: boolean; timeFormat: 'system' | '12h' | '24h' }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  // One fleet-wide query shared by every card, not one per card: the list is
  // nearly always empty and a 20-printer fleet would otherwise make 20
  // requests every 30s. React Query dedupes on the key.
  const { data: scheduled = [] } = useQuery({
    queryKey: SCHEDULED_DRYINGS_KEY,
    queryFn: () => api.listScheduledDryings(),
    refetchInterval: 30_000,
  });
  // The live AMS status reports a starting cycle well before the next poll;
  // refetch so a just-dispatched schedule doesn't linger as pending.
  useEffect(() => {
    if (dryingActive) {
      queryClient.invalidateQueries({ queryKey: SCHEDULED_DRYINGS_KEY });
    }
  }, [dryingActive, queryClient]);
  const cancelMutation = useMutation({
    mutationFn: (id: number) => api.cancelScheduledDrying(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SCHEDULED_DRYINGS_KEY }),
    onError: (error: Error) => showToast(error.message || t('printers.drying.scheduleFailed'), 'error'),
  });
  // Failed rows are shown too: dispatch is the only place a run can fail (too
  // old firmware on a printer that was offline at schedule time), and without
  // this the run just vanishes with only the backend log saying why.
  const rows = scheduled.filter(s => s.printer_id === printerId && (s.status === 'pending' || s.status === 'failed'));
  if (rows.length === 0) return null;
  return (
    <div className="mt-2 space-y-1">
      {rows.map(s => {
        const failed = s.status === 'failed';
        const reasonKey = waitingReasonKey(s.waiting_reason);
        const failedKey = failedReasonKey(s.error_code);
        return (
          <div
            key={s.id}
            data-testid={failed ? 'scheduled-drying-failed' : 'scheduled-drying-pending'}
            className={`flex items-center justify-between px-2 py-1 rounded-lg text-[length:var(--pc-t11,11px)] ${
              failed ? 'bg-red-500/10 border border-red-500/30' : 'bg-amber-500/10 border border-amber-500/30'
            }`}
          >
            <span className={failed ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}>
              {failed ? (
                t('printers.drying.scheduleFailedReason', {
                  reason: failedKey ? t(failedKey) : s.error_message || t('printers.drying.scheduleFailedUnknown'),
                })
              ) : (
                <>
                  {s.start_after
                    ? t('printers.drying.scheduledFor', { time: formatDateTime(s.start_after, timeFormat) })
                    : t('printers.drying.scheduledAsap')}
                  {reasonKey && <span className="ml-1 opacity-80">{t(reasonKey)}</span>}
                </>
              )}
            </span>
            <button
              onClick={() => cancelMutation.mutate(s.id)}
              disabled={cancelMutation.isPending}
              title={failed ? t('printers.drying.dismissFailed') : t('printers.drying.cancelScheduled')}
              className="text-bambu-gray hover:text-red-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <X className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)]" />
            </button>
          </div>
        );
      })}
    </div>
  );
}

/**
 * Movement control popover for the printer card (XY, Z, Extruder jogs and homing).
 * Extracted from PrinterCard.tsx for modularity and file size budget compliance.
 */

import { useTranslation } from 'react-i18next';
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Home,
  Layers,
  Move,
} from 'lucide-react';
import type { Permission } from '../api/client';
import type { Printer } from '../api/types';
import { isBedSlinger } from '../utils/bedSlinger';

export interface PrinterMovementPopoverProps {
  printer: Printer;
  isPrinting: boolean;
  hasPermission: (permission: Permission) => boolean;
  iconControlClass: string;
  bedJogStep: number;
  setBedJogStep: (step: number) => void;
  showBedJogMenu: string | null;
  setShowBedJogMenu: (id: string | null) => void;
  homeAxesMutation: { mutate: (axis: 'all' | 'z') => void; isPending: boolean };
  bedJogMutation: { mutate: (args: { distance: number }) => void; isPending: boolean };
  xyJogMutation: { mutate: (args: { x: number; y: number }) => void; isPending: boolean };
  extruderJogMutation: { mutate: (distance: number) => void; isPending: boolean };
}

export function PrinterMovementPopover({
  printer,
  isPrinting,
  hasPermission,
  iconControlClass,
  bedJogStep,
  setBedJogStep,
  showBedJogMenu,
  setShowBedJogMenu,
  homeAxesMutation,
  bedJogMutation,
  xyJogMutation,
  extruderJogMutation,
}: PrinterMovementPopoverProps) {
  const { t } = useTranslation();
  const canControl = hasPermission('printers:control');
  const disabled = isPrinting || !canControl;
  const jogButtonClass =
    'flex h-8 w-8 items-center justify-center rounded bg-indigo-100 dark:bg-indigo-500/15 text-indigo-700 dark:text-indigo-300 transition-colors hover:bg-indigo-200 dark:hover:bg-indigo-500/30 disabled:cursor-not-allowed disabled:opacity-50';

  // Which part the Z axis moves (#1334). The endpoint takes a signed
  // nozzle-bed gap that means the same thing on every printer, so the
  // arrows are ours to interpret: on a bed-slinger "up" lifts the
  // toolhead and opens the gap, on a bed-on-Z printer it raises the
  // plate toward the nozzle and closes it.
  const zMovesToolhead = isBedSlinger(printer.model);

  const requestZJog = (arrow: 'up' | 'down') => {
    const opensGap = zMovesToolhead ? arrow === 'up' : arrow === 'down';
    // No not-homed gate here, and no endstop bypass to gate either:
    // since #2579 the jog is a bare move that never touches M211. That
    // does not make it clamped — the firmware ignores soft endstops on
    // MQTT G-code entirely, which is what the banner above warns about.
    bedJogMutation.mutate({ distance: opensGap ? bedJogStep : -bedJogStep });
  };

  const requestXyJog = (x: number, y: number) => {
    xyJogMutation.mutate({ x, y });
  };

  const requestExtruderJog = (distance: number) => {
    extruderJogMutation.mutate(distance);
  };

  return (
    <div className="relative">
      <button
        onClick={() => setShowBedJogMenu(showBedJogMenu === printer.id ? null : printer.id)}
        disabled={disabled}
        className={`${iconControlClass} ${
          disabled
            ? 'bg-bambu-dark text-bambu-gray/50 cursor-not-allowed'
            : 'bg-indigo-50 dark:bg-indigo-500/10 text-indigo-700 dark:text-indigo-400 hover:bg-indigo-500/20'
        }`}
        title={
          !canControl
            ? t('printers.permission.noControl')
            : isPrinting
              ? t('printers.bedJog.disabledWhilePrinting')
              : t('printers.bedJog.title')
        }
      >
        <Move className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
      </button>
      {showBedJogMenu === printer.id && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setShowBedJogMenu(null)} />
          <div className="absolute bottom-full left-0 mb-1 z-50 flex w-[216px] flex-col overflow-hidden rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary shadow-2xl">
            <div className="shrink-0 px-3 py-2.5 text-center text-sm font-medium text-white">
              {t('printers.bedJog.title')}
            </div>
            <div className="h-px bg-bambu-dark-tertiary" />
            {/* #2579: Bambu firmware does not enforce soft endstops on
                G-code sent over MQTT, so manual moves can drive past the
                travel limits and cause a collision. Not fixable from our
                side — warn prominently. */}
            <div className="flex items-start gap-1.5 bg-yellow-500/10 px-3 py-2 text-[length:var(--pc-t11,11px)] leading-snug text-yellow-700 dark:text-yellow-400">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{t('printers.bedJog.limitWarning')}</span>
            </div>
            <div className="h-px bg-bambu-dark-tertiary" />
            <div className="flex justify-center px-3 py-2.5">
              <div className="flex items-center justify-center gap-3">
                <div className="grid grid-cols-3 gap-1">
                  <div />
                  <button
                    onClick={() => requestXyJog(0, bedJogStep)}
                    disabled={xyJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label="Move Y forward"
                  >
                    <ArrowUp className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                  <div />
                  <button
                    onClick={() => requestXyJog(-bedJogStep, 0)}
                    disabled={xyJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label="Move X left"
                  >
                    <ArrowLeft className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                  <button
                    onClick={() => {
                      setShowBedJogMenu(null);
                      homeAxesMutation.mutate('all');
                    }}
                    disabled={homeAxesMutation.isPending}
                    className={jogButtonClass}
                    aria-label={t('printers.bedJog.homeZ')}
                  >
                    <Home className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                  <button
                    onClick={() => requestXyJog(bedJogStep, 0)}
                    disabled={xyJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label="Move X right"
                  >
                    <ArrowRight className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                  <div />
                  <button
                    onClick={() => requestXyJog(0, -bedJogStep)}
                    disabled={xyJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label="Move Y back"
                  >
                    <ArrowDown className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                  <div />
                </div>
                <div className="flex flex-col items-center gap-1">
                  <button
                    onClick={() => requestZJog('up')}
                    disabled={bedJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label={t(zMovesToolhead ? 'printers.bedJog.toolheadUp' : 'printers.bedJog.up')}
                  >
                    <ArrowUp className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                  <div className="flex h-8 w-8 items-center justify-center text-bambu-gray/80">
                    <Layers className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </div>
                  <button
                    onClick={() => requestZJog('down')}
                    disabled={bedJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label={t(zMovesToolhead ? 'printers.bedJog.toolheadDown' : 'printers.bedJog.down')}
                  >
                    <ArrowDown className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                </div>
                <div className="flex flex-col items-center gap-1">
                  <button
                    onClick={() => requestExtruderJog(-bedJogStep)}
                    disabled={extruderJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label="Retract filament"
                  >
                    <ArrowUp className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                  <div className="flex h-8 w-8 items-center justify-center text-bambu-gray/80">
                    <span className="text-sm font-semibold leading-none">E</span>
                  </div>
                  <button
                    onClick={() => requestExtruderJog(bedJogStep)}
                    disabled={extruderJogMutation.isPending}
                    className={jogButtonClass}
                    aria-label="Extrude filament"
                  >
                    <ArrowDown className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)]" />
                  </button>
                </div>
              </div>
            </div>
            <div className="h-px bg-bambu-dark-tertiary" />
            <div className="px-3 pt-2.5 pb-3">
              <div className="mb-1 text-[length:var(--pc-t9,9px)] uppercase tracking-wider text-bambu-gray/70">
                {t('printers.bedJog.step')}
              </div>
              <div className="flex gap-1">
                {[1, 10, 50].map((step) => (
                  <button
                    key={step}
                    onClick={() => setBedJogStep(step)}
                    className={`flex-1 px-1 py-1 rounded text-[length:var(--pc-t10,10px)] transition-colors ${
                      bedJogStep === step
                        ? 'bg-bambu-green/20 text-bambu-green'
                        : 'bg-bambu-dark text-bambu-gray hover:bg-bambu-dark-tertiary'
                    }`}
                  >
                    {step}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

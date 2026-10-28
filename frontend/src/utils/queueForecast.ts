import type { PrintQueueItem, Printer } from '../api/client';
import { compareQueueOrder } from './queueOrder';
import { parseUTCDate } from './date';
import { isBusyOnlyWaitingReason } from './waitingReason';

/**
 * Prognose der Warteschlange: wann welcher Drucker frei wird und wann jeder Auftrag voraussichtlich fertig ist.
 *
 * Reihenfolge wie im Planer (Priorität, dann Position oder „kürzeste zuerst"). Aufträge für einen festen Drucker reihen
 * sich dahinter ein; Aufträge für „irgendein Drucker dieses Modells" gehen an den passenden Drucker, der zuerst frei
 * wird (bei Gleichstand der mit der kleineren Nummer). Aufträge zum manuellen Start und solche, die auf den Benutzer
 * warten, laufen nicht von allein und zählen nicht mit. Aufträge ohne Druckzeit werden nicht mitgerechnet und gezählt.
 * Das ist eine Schätzung, kein Versprechen: Fehlschläge, Plattenwechsel und Aufwärmzeiten sind nicht enthalten.
 */

const HOUR_MS = 60 * 60 * 1000;
export const FORECAST_WINDOW_HOURS = 24;

export interface PrinterStatusLite {
  progress?: number;
  remaining_time?: number; // Minuten
  state?: string;
}

export interface ForecastItem {
  printerId: number | null;
  start: number;
  end: number;
}

export interface PrinterForecast {
  printer: Printer;
  /** printing: läuft gerade; idle: frei; offline: kein Status bekannt */
  state: 'printing' | 'idle' | 'offline';
  /** Ende des aktuellen Drucks, falls einer läuft */
  currentEnd: number | null;
  /** Zeitpunkt, ab dem der Drucker nach allen vorhergesagten Aufträgen frei ist */
  freeAt: number;
  queuedCount: number;
  queuedSeconds: number;
  /** Anteil der nächsten 24 Stunden, den der Drucker belegt ist (0 bis 1) */
  busyRatio: number;
}

export interface QueueForecast {
  items: Record<number, ForecastItem>;
  printers: PrinterForecast[];
  /** Wann der letzte vorhergesagte Auftrag fertig ist; null ohne vorhergesagte Aufträge */
  finishAt: number | null;
  totalSeconds: number;
  pendingCount: number;
  /** Aufträge ohne Druckzeit, die nicht mitgerechnet sind */
  unknownCount: number;
  /** Aufträge ohne passenden Drucker oder ohne Ziel, die nicht mitgerechnet sind */
  unplacedCount: number;
}

const modelKey = (value: string | null | undefined) => (value ?? '').toLowerCase().replace(/[^a-z0-9]/g, '');

function candidateModels(item: PrintQueueItem): string[] {
  const models = item.variants && item.variants.length > 0 ? item.variants.map((v) => v.target_model) : [item.target_model];
  return models.map(modelKey).filter(Boolean);
}

export function buildForecast(input: {
  items: PrintQueueItem[];
  printers: Printer[];
  statuses: Record<number, PrinterStatusLite>;
  sjfEnabled: boolean;
  now: number;
}): QueueForecast {
  const { items, statuses, sjfEnabled, now } = input;
  const printers = input.printers.filter((p) => p.is_active).sort((a, b) => a.id - b.id);
  const freeAt = new Map<number, number>();
  const currentEnd = new Map<number, number>();
  const queued = new Map<number, { count: number; seconds: number }>();
  const known = new Set<number>();

  for (const printer of printers) {
    const status = statuses[printer.id];
    known.add(printer.id);
    freeAt.set(printer.id, now);
    queued.set(printer.id, { count: 0, seconds: 0 });
    if (status?.remaining_time != null && status.remaining_time > 0 && status.state !== 'IDLE') {
      const end = now + status.remaining_time * 60 * 1000;
      currentEnd.set(printer.id, end);
      freeAt.set(printer.id, end);
    }
  }

  // Läuft ein Auftrag, dessen Drucker keine Restzeit meldet, zählt die Druckzeit abzüglich Fortschritt.
  for (const item of items) {
    if (item.status !== 'printing' || item.printer_id == null || !known.has(item.printer_id)) continue;
    if (currentEnd.has(item.printer_id)) continue;
    const progress = statuses[item.printer_id]?.progress ?? 0;
    const remainingMs = item.print_time_seconds ? item.print_time_seconds * Math.max(0, 1 - progress / 100) * 1000 : HOUR_MS;
    const end = now + remainingMs;
    currentEnd.set(item.printer_id, end);
    freeAt.set(item.printer_id, end);
  }

  const result: Record<number, ForecastItem> = {};
  let totalSeconds = 0;
  let unknownCount = 0;
  let unplacedCount = 0;
  let finishAt: number | null = null;

  const pending = items
    .filter((item) => item.status === 'pending')
    .filter((item) => !item.manual_start && !(item.waiting_reason && !isBusyOnlyWaitingReason(item.waiting_reason)))
    .sort((a, b) => compareQueueOrder(a, b, sjfEnabled));

  for (const item of pending) {
    const seconds = item.print_time_seconds ?? 0;
    if (seconds <= 0) {
      unknownCount += 1;
      continue;
    }
    let targets: Printer[];
    if (item.printer_id != null) {
      targets = printers.filter((p) => p.id === item.printer_id);
    } else {
      const models = candidateModels(item);
      targets = models.length
        ? printers.filter((p) => models.includes(modelKey(p.model)) && (!item.target_location || p.location === item.target_location))
        : [];
    }
    if (targets.length === 0) {
      unplacedCount += 1;
      continue;
    }
    const earliest = targets.reduce((best, p) => ((freeAt.get(p.id) ?? now) < (freeAt.get(best.id) ?? now) ? p : best));
    const scheduled = parseUTCDate(item.scheduled_time)?.getTime() ?? 0;
    const start = Math.max(freeAt.get(earliest.id) ?? now, scheduled > now ? scheduled : now);
    const end = start + seconds * 1000;
    result[item.id] = { printerId: earliest.id, start, end };
    freeAt.set(earliest.id, end);
    const load = queued.get(earliest.id) ?? { count: 0, seconds: 0 };
    queued.set(earliest.id, { count: load.count + 1, seconds: load.seconds + seconds });
    totalSeconds += seconds;
    finishAt = finishAt == null ? end : Math.max(finishAt, end);
  }

  const windowMs = FORECAST_WINDOW_HOURS * HOUR_MS;
  const forecasts: PrinterForecast[] = printers.map((printer) => {
    const free = freeAt.get(printer.id) ?? now;
    const status = statuses[printer.id];
    const load = queued.get(printer.id) ?? { count: 0, seconds: 0 };
    const isPrinting = currentEnd.has(printer.id);
    return {
      printer,
      state: isPrinting ? 'printing' : status ? 'idle' : 'offline',
      currentEnd: currentEnd.get(printer.id) ?? null,
      freeAt: free,
      queuedCount: load.count,
      queuedSeconds: load.seconds,
      busyRatio: Math.min(1, Math.max(0, (free - now) / windowMs)),
    };
  });

  return { items: result, printers: forecasts, finishAt, totalSeconds, pendingCount: pending.length, unknownCount, unplacedCount };
}

/** Warnstufe zum Liefertermin: bereits vorbei, oder die Prognose liegt dahinter. */
export function dueWarningFor(
  dueAt: string | null | undefined,
  forecastEnd: number | null | undefined,
  now: number,
): 'overdue' | 'too_late' | null {
  const due = parseUTCDate(dueAt)?.getTime();
  if (due == null) return null;
  if (due < now) return 'overdue';
  if (forecastEnd != null && forecastEnd > due) return 'too_late';
  return null;
}

/** „14:30" für heute, sonst mit Wochentag (bis 6 Tage) oder Datum. */
export function formatForecastTime(ms: number, now: number): string {
  const date = new Date(ms);
  const time = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  const startOfDay = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
  const days = Math.round((startOfDay(date) - startOfDay(new Date(now))) / (24 * HOUR_MS));
  if (days <= 0) return time;
  if (days < 7) return `${date.toLocaleDateString(undefined, { weekday: 'short' })} ${time}`;
  return `${date.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' })} ${time}`;
}

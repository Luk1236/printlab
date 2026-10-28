import { describe, it, expect } from 'vitest';
import { buildForecast, dueWarningFor } from '../../utils/queueForecast';
import type { PrintQueueItem, Printer } from '../../api/client';

const NOW = Date.parse('2026-10-28T12:00:00Z');
const MIN = 60 * 1000;
const HOUR = 60 * MIN;

const printer = (id: number, model = 'X1C', over: Partial<Printer> = {}): Printer =>
  ({ id, name: `P${id}`, model, location: null, is_active: true, ...over }) as Printer;

let seq = 0;
const job = (over: Partial<PrintQueueItem>): PrintQueueItem =>
  ({
    id: ++seq, status: 'pending', printer_id: null, target_model: null, target_location: null, waiting_reason: null,
    manual_start: false, position: seq, priority: 1, print_time_seconds: 3600, scheduled_time: null, variants: [], ...over,
  }) as PrintQueueItem;

const run = (items: PrintQueueItem[], printers: Printer[], statuses = {}, sjfEnabled = false) =>
  buildForecast({ items, printers, statuses, sjfEnabled, now: NOW });

describe('buildForecast', () => {
  it('chains jobs pinned to one printer behind the running print', () => {
    const a = job({ printer_id: 1 });
    const b = job({ printer_id: 1, print_time_seconds: 1800 });
    const f = run([a, b], [printer(1)], { 1: { remaining_time: 30, state: 'RUNNING' } });
    expect(f.items[a.id]).toEqual({ printerId: 1, start: NOW + 30 * MIN, end: NOW + 90 * MIN });
    expect(f.items[b.id].start).toBe(NOW + 90 * MIN);
    expect(f.finishAt).toBe(NOW + 120 * MIN);
    expect(f.printers[0]).toMatchObject({ state: 'printing', queuedCount: 2, queuedSeconds: 5400, currentEnd: NOW + 30 * MIN });
  });

  it('spreads model-based jobs over matching printers by earliest free time', () => {
    const jobs = [job({ target_model: 'X1C' }), job({ target_model: 'X1C' }), job({ target_model: 'X1C' })];
    const f = run(jobs, [printer(1), printer(2), printer(3, 'P1S')], { 1: { remaining_time: 120, state: 'RUNNING' }, 2: { state: 'IDLE' } });
    expect(jobs.map((j) => f.items[j.id].printerId)).toEqual([2, 2, 1]);
    expect(f.items[jobs[2].id].end).toBe(NOW + 180 * MIN);
    expect(f.printers.find((p) => p.printer.id === 3)?.queuedCount).toBe(0);
  });

  it('respects the location filter and cross-model variants', () => {
    const inCellar = job({ target_model: 'X1C', target_location: 'Keller' });
    const cross = job({ target_model: 'A1', variants: [{ target_model: 'P1S' } as never] });
    const f = run([inCellar, cross], [printer(1, 'X1C', { location: 'Werkstatt' }), printer(2, 'X1C', { location: 'Keller' }), printer(3, 'P1S')]);
    expect(f.items[inCellar.id].printerId).toBe(2);
    expect(f.items[cross.id].printerId).toBe(3);
  });

  it('orders by priority before the position', () => {
    const normal = job({ printer_id: 1, position: 0 });
    const urgent = job({ printer_id: 1, position: 5, priority: 2 });
    const f = run([normal, urgent], [printer(1)]);
    expect(f.items[urgent.id].start).toBe(NOW);
    expect(f.items[normal.id].start).toBe(NOW + HOUR);
  });

  it('does not count staged, blocked, unknown-length or unplaceable jobs', () => {
    const staged = job({ printer_id: 1, manual_start: true });
    const blocked = job({ printer_id: 1, waiting_reason: 'Waiting for filament: P1 (needs PETG)' });
    const busy = job({ printer_id: 1, waiting_reason: 'Busy: P1' });
    const unknown = job({ printer_id: 1, print_time_seconds: null });
    const nowhere = job({ target_model: 'H2D' });
    const loose = job({});
    const f = run([staged, blocked, busy, unknown, nowhere, loose], [printer(1)]);
    expect(Object.keys(f.items)).toEqual([String(busy.id)]);
    expect(f).toMatchObject({ unknownCount: 1, unplacedCount: 2, totalSeconds: 3600, pendingCount: 4 });
  });

  it('starts a scheduled job no earlier than its time', () => {
    const later = job({ printer_id: 1, scheduled_time: new Date(NOW + 5 * HOUR).toISOString() });
    expect(run([later], [printer(1)]).items[later.id].start).toBe(NOW + 5 * HOUR);
  });

  it('uses progress when a printing job has no remaining time and ignores inactive printers', () => {
    const running = job({ status: 'printing', printer_id: 1, print_time_seconds: 7200 });
    const next = job({ printer_id: 1 });
    const f = run([running, next], [printer(1), printer(2, 'X1C', { is_active: false })], { 1: { progress: 50, state: 'RUNNING' } });
    expect(f.items[next.id].start).toBe(NOW + HOUR);
    expect(f.printers).toHaveLength(1);
  });

  it('marks printers without status as offline and caps the 24 h load at 100 %', () => {
    const long = job({ printer_id: 1, print_time_seconds: 40 * 3600 });
    const f = run([long], [printer(1), printer(2)], { 2: { state: 'IDLE' } });
    expect(f.printers.map((p) => p.state)).toEqual(['offline', 'idle']);
    expect(f.printers[0].busyRatio).toBe(1);
    expect(f.printers[1].busyRatio).toBe(0);
  });

  it('is empty without jobs', () => {
    const f = run([], [printer(1)]);
    expect(f).toMatchObject({ finishAt: null, totalSeconds: 0, pendingCount: 0, items: {} });
  });
});

describe('dueWarningFor', () => {
  const iso = (ms: number) => new Date(ms).toISOString();
  it('warns when overdue or when the forecast ends after the due date', () => {
    expect(dueWarningFor(iso(NOW - HOUR), NOW, NOW)).toBe('overdue');
    expect(dueWarningFor(iso(NOW + HOUR), NOW + 2 * HOUR, NOW)).toBe('too_late');
    expect(dueWarningFor(iso(NOW + 3 * HOUR), NOW + 2 * HOUR, NOW)).toBeNull();
  });
  it('gives no warning without a date or without a forecast', () => {
    expect(dueWarningFor(null, NOW, NOW)).toBeNull();
    expect(dueWarningFor(iso(NOW + HOUR), null, NOW)).toBeNull();
  });
});

import type { ArchiveStats } from '../api/client';

export interface StatsLabels {
  title: string;
  period: string;
  prints: string;
  successful: string;
  failed: string;
  time: string;
  filament: string;
  filamentCost: string;
  energy: string;
  energyCost: string;
}

const escapeHtml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Druckfertige Statistik (z. B. Monatsbericht): Kennzahlen des gewählten Zeitraums als HTML ohne Skripte. */
export function buildStatsDocument(
  stats: ArchiveStats,
  labels: StatsLabels,
  periodText: string,
  currency: string,
  date: Date
): string {
  const money = (value: number) => `${currency} ${(value || 0).toFixed(2)}`;
  const rows: Array<[string, string]> = [
    [labels.prints, String(stats.total_prints ?? 0)],
    [labels.successful, String(stats.successful_prints ?? 0)],
    [labels.failed, String(stats.failed_prints ?? 0)],
    [labels.time, `${(stats.total_print_time_hours ?? 0).toFixed(1)} h`],
    [labels.filament, `${(stats.total_filament_grams ?? 0).toFixed(0)} g`],
    [labels.filamentCost, money(stats.total_cost)],
    [labels.energy, `${(stats.total_energy_kwh ?? 0).toFixed(3)} kWh`],
    [labels.energyCost, money(stats.total_energy_cost)],
  ];
  const body = rows
    .map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td class="n">${escapeHtml(value)}</td></tr>`)
    .join('');
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(labels.title)}</title>
<style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:40px;color:#111}
h1{font-size:22px;margin:0 0 4px}.d{color:#555;margin:0 0 24px;font-size:13px}
table{border-collapse:collapse;width:100%;max-width:520px}td{padding:8px 4px;border-bottom:1px solid #ddd}
td.n{text-align:right;font-variant-numeric:tabular-nums}
</style></head><body><h1>${escapeHtml(labels.title)}</h1>
<p class="d">${escapeHtml(labels.period)}: ${escapeHtml(periodText)} · ${escapeHtml(date.toLocaleDateString())}</p>
<table>${body}</table></body></html>`;
}

import type { QuoteResponse } from '../api/client';

export interface QuoteLabels {
  title: string;
  material: string;
  energy: string;
  labor: string;
  subtotal: string;
  markup: string;
  total: string;
}

const escapeHtml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Druckfertiges Angebotsdokument (reines HTML ohne Skripte; Werte und Beschriftungen werden maskiert). */
export function buildQuoteDocument(quote: QuoteResponse, labels: QuoteLabels, date: Date): string {
  const money = (value: number) =>
    new Intl.NumberFormat(undefined, { style: 'currency', currency: quote.currency || 'EUR' }).format(value || 0);
  const rows: Array<[string, number]> = [
    [labels.material, quote.material],
    [labels.energy, quote.energy],
    [labels.labor, quote.labor],
    [labels.subtotal, quote.subtotal],
    [labels.markup, quote.markup],
  ];
  const body = rows
    .map(([label, value]) => `<tr><td>${escapeHtml(label)}</td><td class="n">${escapeHtml(money(value))}</td></tr>`)
    .join('');
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(labels.title)}</title>
<style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:40px;color:#111}
h1{font-size:22px;margin:0 0 4px}.d{color:#555;margin:0 0 24px;font-size:13px}
table{border-collapse:collapse;width:100%;max-width:520px}td{padding:8px 4px;border-bottom:1px solid #ddd}
td.n{text-align:right;font-variant-numeric:tabular-nums}tr.t td{font-weight:700;font-size:18px;border-bottom:2px solid #111}
</style></head><body><h1>${escapeHtml(labels.title)}</h1><p class="d">${escapeHtml(date.toLocaleDateString())}</p>
<table>${body}<tr class="t"><td>${escapeHtml(labels.total)}</td><td class="n">${escapeHtml(money(quote.total))}</td></tr></table>
</body></html>`;
}

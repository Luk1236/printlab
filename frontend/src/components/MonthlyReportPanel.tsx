import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Download, FileBarChart, Loader2 } from 'lucide-react';

import { api } from '../api/client';
import { Button } from './Button';
import { useToast } from '../contexts/ToastContext';

function money(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

/** Letzter abgeschlossener Monat als Voreinstellung. */
function defaultMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function downloadBlob({ blob, filename }: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-bambu-dark-tertiary rounded-lg p-2">
      <div className="text-[10px] uppercase tracking-wide text-bambu-gray">{label}</div>
      <div className="text-sm font-semibold text-white">{value}</div>
    </div>
  );
}

/**
 * Monats-Report: Umsatz (Rechnungen, Angebote), Fertigung (Drucke, Material,
 * Energie) und Gewinn der Nachkalkulation für einen Monat — Zahlensammlung im
 * Rechner-Kartebereich, PDF als Download.
 */
export function MonthlyReportPanel() {
  const { t, i18n } = useTranslation();
  const { showToast } = useToast();
  const [selected, setSelected] = useState(defaultMonth);
  const [year, month] = useMemo(() => {
    const [y, m] = selected.split('-').map(Number);
    return [y || new Date().getFullYear(), Math.min(12, Math.max(1, m || new Date().getMonth() + 1))];
  }, [selected]);

  const { data: report, isLoading } = useQuery({
    queryKey: ['monthly-report', year, month],
    queryFn: () => api.getMonthlyReport(year, month),
  });

  const pdf = useMutation({
    mutationFn: () => api.downloadMonthlyReportPdf(year, month, i18n.language.startsWith('de') ? 'de' : 'en'),
    onSuccess: downloadBlob,
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const production = report?.production;
  const profit = report?.profit;
  const isEmpty =
    report &&
    Object.keys(report.invoices || {}).length === 0 &&
    Object.keys(report.quotes || {}).length === 0 &&
    (production?.prints ?? 0) === 0;

  return (
    <div className="border border-bambu-dark-tertiary rounded-lg p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
          <FileBarChart className="w-4 h-4" />
          {t('monthlyReport.title')} {String(month).padStart(2, '0')}/{year}
        </h3>
        <div className="flex items-center gap-2">
          <input
            type="month"
            aria-label={t('monthlyReport.title')}
            value={selected}
            onChange={(event) => setSelected(event.target.value || defaultMonth())}
            className="bg-bambu-dark-tertiary text-xs text-white rounded px-2 py-1"
          />
          <Button size="sm" variant="ghost" onClick={() => pdf.mutate()} disabled={pdf.isPending}>
            {pdf.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Download className="w-4 h-4" />}
            {t('monthlyReport.downloadPdf')}
          </Button>
        </div>
      </div>
      <p className="text-xs text-bambu-gray">{t('monthlyReport.hint')}</p>
      {isLoading ? (
        <div className="flex items-center gap-2 text-sm text-bambu-gray">
          <Loader2 className="w-4 h-4 animate-spin" />
        </div>
      ) : !report ? (
        <div className="text-sm text-bambu-gray">{t('monthlyReport.noData')}</div>
      ) : (
        <div className="space-y-3">
          {Object.keys(report.invoices || {}).length > 0 && (
            <div>
              <div className="text-xs font-semibold text-bambu-gray mb-1">{t('monthlyReport.invoices')}</div>
              <ul className="text-sm space-y-1">
                {Object.entries(report.invoices).map(([currency, bucket]) => (
                  <li key={currency} className="text-white">
                    {t('monthlyReport.invoices')}: {bucket.count} · {money(bucket.total, currency)}
                    {bucket.overdue_count > 0 && (
                      <span className="text-red-400 ml-2">
                        {t('monthlyReport.invoices')} {t('monthlyReport.overdue')}: {money(bucket.overdue, currency)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {Object.keys(report.quotes || {}).length > 0 && (
            <div className="text-sm text-white">
              {t('monthlyReport.quotes')}:{' '}
              {Object.entries(report.quotes)
                .map(([currency, total]) => money(total, currency))
                .join(' · ')}
            </div>
          )}
          {production && (production.prints > 0 || production.failed > 0) && (
            <div>
              <div className="text-xs font-semibold text-bambu-gray mb-1">{t('monthlyReport.production')}</div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                <Tile label={t('monthlyReport.prints')} value={String(production.prints)} />
                <Tile label={t('monthlyReport.failed')} value={String(production.failed)} />
                <Tile label={t('monthlyReport.hours')} value={`${(production.minutes / 60).toFixed(1)} h`} />
                <Tile label={t('monthlyReport.grams')} value={`${production.grams} g`} />
                <Tile label={t('monthlyReport.material')} value={money(production.material_cost || 0, i18n.language.startsWith('de') ? 'EUR' : 'EUR')} />
                <Tile label={t('monthlyReport.energy')} value={money(production.energy_cost || 0, i18n.language.startsWith('de') ? 'EUR' : 'EUR')} />
              </div>
              {production.by_printer.length > 0 && (
                <div className="mt-2 text-xs text-bambu-gray">
                  {production.by_printer.map((line) => (
                    <span key={line.name} className="mr-3">
                      {line.name}: {line.prints} · {(line.minutes / 60).toFixed(1)} h
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
          {profit && profit.quotes > 0 && (
            <div>
              <div className="text-xs font-semibold text-bambu-gray mb-1">
                {t('monthlyReport.profit')} ({profit.quotes})
              </div>
              <ul className="text-sm space-y-1">
                {Object.entries(profit.per_currency).map(([currency, bucket]) => (
                  <li key={currency} className="text-white">
                    {money(bucket.revenue, currency)} − {money(bucket.actual_cost, currency)} ={' '}
                    <span className={bucket.profit < 0 ? 'text-red-400' : 'text-green-400'}>
                      {money(bucket.profit, currency)}
                    </span>
                  </li>
                ))}
              </ul>
              {profit.estimated_quotes > 0 && (
                <div className="text-[10px] text-bambu-gray">{t('monthlyReport.estimatedHint')}</div>
              )}
            </div>
          )}
          {isEmpty && <div className="text-sm text-bambu-gray">{t('monthlyReport.noData')}</div>}
        </div>
      )}
    </div>
  );
}
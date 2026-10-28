import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { ChevronDown, ChevronUp, Gauge } from 'lucide-react';

import type { PrintQueueItem, Printer } from '../api/client';
import { QUEUE_FORECAST_KEY } from '../hooks/useQueueForecast';
import { formatDuration } from '../utils/date';
import { buildForecast, formatForecastTime } from '../utils/queueForecast';
import type { PrinterStatusLite } from '../utils/queueForecast';

/**
 * Auslastung der Drucker und voraussichtliche Fertigzeit der Warteschlange (Schätzung aus Restzeit, Druckzeiten und
 * Planer-Reihenfolge). Legt die Prognose zusätzlich im Cache ab, damit jede Warteschlangen-Zeile „fertig um …" zeigen
 * und den Liefertermin gegen die echte Prognose prüfen kann.
 */
export function QueueForecastPanel({
  items,
  printers,
  statuses,
  sjfEnabled,
}: {
  items: PrintQueueItem[];
  printers: Printer[];
  statuses: Record<number, PrinterStatusLite>;
  sjfEnabled: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(true);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const forecast = useMemo(() => buildForecast({ items, printers, statuses, sjfEnabled, now }), [items, printers, statuses, sjfEnabled, now]);
  useEffect(() => {
    queryClient.setQueryData(QUEUE_FORECAST_KEY, forecast);
  }, [queryClient, forecast]);

  const active = items.some((item) => item.status === 'pending' || item.status === 'printing');
  if (!active) return null;

  return (
    <div className="mb-4 rounded-xl border border-bambu-dark-tertiary bg-bambu-dark-secondary p-3 space-y-3" data-testid="queue-forecast">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-medium text-white">
          <Gauge className="w-4 h-4 text-bambu-green" />
          {t('queue.forecast.title')}
        </h3>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          className="text-bambu-gray hover:text-white"
          aria-label={t('queue.forecast.title')}
          aria-expanded={open}
        >
          {open ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
      </div>
      <p className="text-xs text-bambu-gray-light" data-testid="forecast-summary">
        {forecast.finishAt != null
          ? `${t('queue.forecast.finishAll', { time: formatForecastTime(forecast.finishAt, now) })} · ${t('queue.forecast.totalLoad', {
              count: forecast.pendingCount - forecast.unknownCount - forecast.unplacedCount,
              duration: formatDuration(forecast.totalSeconds),
            })}`
          : t('queue.forecast.nothing')}
      </p>
      {open && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
            {forecast.printers.map((entry) => (
              <div key={entry.printer.id} className="rounded-lg border border-bambu-dark-tertiary p-2 text-xs space-y-1" data-testid={`forecast-printer-${entry.printer.id}`}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-white truncate">{entry.printer.name}</span>
                  <span
                    className={
                      entry.state === 'printing' ? 'text-blue-600 dark:text-blue-400' : entry.state === 'idle' ? 'text-bambu-green' : 'text-bambu-gray'
                    }
                  >
                    {entry.state === 'printing' && entry.currentEnd != null
                      ? t('queue.forecast.state.printing', { duration: formatDuration(Math.max(0, (entry.currentEnd - now) / 1000)) })
                      : t(`queue.forecast.state.${entry.state}`)}
                  </span>
                </div>
                <div className="h-1.5 rounded bg-bambu-dark-tertiary overflow-hidden" aria-hidden="true">
                  <div
                    className={`h-full ${entry.busyRatio >= 1 ? 'bg-amber-500' : 'bg-bambu-green'}`}
                    style={{ width: `${Math.round(entry.busyRatio * 100)}%` }}
                  />
                </div>
                <div className="text-bambu-gray">
                  {t('queue.forecast.load', { percent: Math.round(entry.busyRatio * 100) })}
                  {entry.queuedCount > 0 && ` · ${t('queue.forecast.queued', { count: entry.queuedCount, duration: formatDuration(entry.queuedSeconds) })}`}
                </div>
                {entry.freeAt > now + 60000 && <div className="text-bambu-gray">{t('queue.forecast.freeAt', { time: formatForecastTime(entry.freeAt, now) })}</div>}
              </div>
            ))}
          </div>
          {forecast.unknownCount > 0 && <p className="text-[11px] text-amber-700 dark:text-amber-400">{t('queue.forecast.unknown', { count: forecast.unknownCount })}</p>}
          {forecast.unplacedCount > 0 && <p className="text-[11px] text-amber-700 dark:text-amber-400">{t('queue.forecast.unplaced', { count: forecast.unplacedCount })}</p>}
          <p className="text-[11px] text-bambu-gray">{t('queue.forecast.note')}</p>
        </>
      )}
    </div>
  );
}

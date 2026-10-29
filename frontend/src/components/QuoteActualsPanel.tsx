import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import { Button } from './Button';
import { useToast } from '../contexts/ToastContext';

function fmt(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value || 0);
  } catch {
    return `${(value || 0).toFixed(2)} ${currency}`;
  }
}

/**
 * Nachkalkulation: Druckjobs aus dem Archiv mit einem Angebot verknüpfen und die Ist-Kosten (Material, Energie) gegen den
 * Angebotspreis stellen. Die Arbeitszeit bleibt wie im Angebot; zusätzliche Positionen zählen nur zum Erlös.
 */
export function QuoteActualsPanel({ quoteId }: { quoteId: string }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState('');
  const [targetPrinter, setTargetPrinter] = useState('');
  const [priority, setPriority] = useState(1);

  const { data } = useQuery({ queryKey: ['quoteActuals', quoteId], queryFn: () => api.getQuoteActuals(quoteId) });
  const { data: archives } = useQuery({ queryKey: ['archivesRecent'], queryFn: () => api.getArchives(undefined, undefined, 100) });
  const { data: printers } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters });

  const link = useMutation({
    mutationFn: (ids: number[]) => api.linkQuoteArchives(quoteId, ids),
    onSuccess: () => {
      setSelected('');
      queryClient.invalidateQueries({ queryKey: ['quoteActuals', quoteId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const enqueue = useMutation({
    mutationFn: () =>
      api.queueQuotePrints(quoteId, {
        printer_id: targetPrinter ? Number(targetPrinter) : null,
        priority,
      }),
    onSuccess: (result) => {
      if (result.errors.length > 0) {
        showToast(t('quote.enqueuedWithErrors', { queued: result.queued.length, errors: result.errors.length }), 'error');
      } else {
        showToast(t('quote.enqueued', { count: result.queued.length }));
      }
      queryClient.invalidateQueries({ queryKey: ['queue'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  if (!data) return null;
  const linkedIds = data.lines.map((line) => line.archive_id).concat(data.missing_ids);
  const choices = (archives ?? []).filter((a) => !linkedIds.includes(a.id));
  const over = data.deviation > 0;

  return (
    <div className="ml-4 mt-1 mb-2 border-l border-bambu-dark-tertiary pl-3 space-y-2 text-xs" data-testid={`quote-actuals-${quoteId}`}>
      <p className="text-bambu-gray">{t('quote.actualsHint')}</p>
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={selected}
          onChange={(event) => setSelected(event.target.value)}
          aria-label={t('quote.selectPrint')}
          className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-xs max-w-xs"
        >
          <option value="">{t('quote.selectPrint')}</option>
          {choices.map((a) => (
            <option key={a.id} value={a.id}>
              #{a.id} {a.print_name || a.filename}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          disabled={!selected || link.isPending}
          onClick={() => link.mutate([...linkedIds, Number(selected)])}
        >
          {t('quote.linkPrint')}
        </Button>
      </div>
      {data.lines.length === 0 ? (
        <p className="text-bambu-gray">{t('quote.noPrints')}</p>
      ) : (
        <ul className="space-y-0.5">
          {data.lines.map((line) => (
            <li key={line.archive_id} className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-bambu-gray">#{line.archive_id}</span>
              <span className="text-white truncate">{line.filename}</span>
              <span className="text-bambu-gray">
                {line.grams} g · {line.minutes} min
              </span>
              <span className="ml-auto text-bambu-gray-light">
                {fmt(line.material + line.energy, data.currency)}
                {line.estimated ? ` (${t('quote.estimated')})` : ''}
              </span>
              <Button
                size="sm"
                variant="ghost"
                aria-label={`${t('quote.unlinkPrint')} #${line.archive_id}`}
                disabled={link.isPending}
                onClick={() => link.mutate(linkedIds.filter((id) => id !== line.archive_id))}
              >
                ✕
              </Button>
            </li>
          ))}
        </ul>
      )}
      {data.linked > 0 && (
        <div className="space-y-0.5 border-t border-bambu-dark-tertiary pt-1" data-testid="quote-actuals-summary">
          <div className="flex justify-between">
            <span className="text-bambu-gray">{t('quote.actualCost')}</span>
            <span className="text-white">{fmt(data.actual_cost, data.currency)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-bambu-gray">{t('quote.quotedCost')}</span>
            <span className="text-bambu-gray-light">{fmt(data.quoted_cost, data.currency)}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-bambu-gray">{t('quote.deviation')}</span>
            <span className={over ? 'text-red-700 dark:text-red-400' : 'text-bambu-green'}>
              {data.deviation > 0 ? '+' : ''}
              {fmt(data.deviation, data.currency)}
            </span>
          </div>
          <div className="flex justify-between font-medium">
            <span className="text-bambu-gray">{t('quote.profit')}</span>
            <span className="text-white">{fmt(data.profit, data.currency)}</span>
          </div>
        </div>
      )}
      {data.missing_ids.length > 0 && <p className="text-amber-700 dark:text-amber-400">{t('quote.missingPrints', { ids: data.missing_ids.join(', ') })}</p>}
      {data.linked > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-t border-bambu-dark-tertiary pt-1" data-testid="quote-actuals-enqueue">
          <select
            value={targetPrinter}
            onChange={(event) => setTargetPrinter(event.target.value)}
            aria-label={t('quote.enqueueTarget')}
            className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-xs max-w-xs"
          >
            <option value="">{t('quote.assignLater')}</option>
            {(printers ?? []).map((printer) => (
              <option key={printer.id} value={printer.id}>
                {printer.name}
              </option>
            ))}
          </select>
          <select
            value={priority}
            onChange={(event) => setPriority(Number(event.target.value))}
            aria-label={t('quote.enqueuePriority')}
            className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-xs"
          >
            <option value={2}>{t('queue.priorityUrgent')}</option>
            <option value={1}>{t('queue.priorityNormal')}</option>
            <option value={0}>{t('queue.priorityLow')}</option>
          </select>
          <Button size="sm" disabled={enqueue.isPending} onClick={() => enqueue.mutate()} aria-label={t('quote.enqueueJobs')}>
            {t('quote.enqueueJobs')}
          </Button>
        </div>
      )}
    </div>
  );
}

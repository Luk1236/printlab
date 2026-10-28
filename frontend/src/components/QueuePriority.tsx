import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowUp } from 'lucide-react';

import { useQueueForecast } from '../hooks/useQueueForecast';
import { dueWarningFor, formatForecastTime } from '../utils/queueForecast';
import { PRIORITY_KEYS, PRIORITY_LEVELS, PRIORITY_NORMAL, queuePriorityPayload } from '../utils/queuePriority';

/** Filter „Alle Prioritäten / Eilig / Normal / Niedrig" für die Warteschlange; leer = alle. */
export function QueuePriorityFilter({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useTranslation();
  return (
    <select
      className="px-2 sm:px-3 py-2 text-sm sm:text-base bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none min-w-0 flex-1 sm:flex-none"
      value={value}
      aria-label={t('queue.priority.label')}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="">{t('queue.priority.filterAll')}</option>
      {PRIORITY_LEVELS.map((level) => (
        <option key={level} value={String(level)}>
          {t(`queue.priority.${PRIORITY_KEYS[level]}`)}
        </option>
      ))}
    </select>
  );
}

/** Plaketten an einem Auftrag: Priorität (nur wenn nicht „normal") und die Warnung zum Liefertermin. */
export function QueueItemFlags({
  item,
}: {
  item: { id?: number; priority?: number; due_warning?: 'overdue' | 'too_late' | null; due_at?: string | null; status: string };
}) {
  const { t } = useTranslation();
  const forecast = useQueueForecast();
  const priority = item.priority ?? PRIORITY_NORMAL;
  if (item.status !== 'pending' && item.status !== 'printing') return null;
  // Mit Prognose gilt sie für den Termin (Wartezeit vor dem Start eingerechnet), sonst die Warnung des Servers.
  const predicted = item.id != null && item.status === 'pending' ? forecast?.items[item.id] : undefined;
  const warning = predicted ? dueWarningFor(item.due_at, predicted.end, Date.now()) : (item.due_warning ?? null);
  if (priority === PRIORITY_NORMAL && !warning && !predicted) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] sm:text-xs" data-testid="queue-item-flags">
      {priority !== PRIORITY_NORMAL && (
        <span
          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 ${
            priority > PRIORITY_NORMAL ? 'bg-red-500/15 text-red-700 dark:text-red-400' : 'bg-bambu-dark-tertiary text-bambu-gray'
          }`}
        >
          {priority > PRIORITY_NORMAL && <ArrowUp className="w-3 h-3" />}
          {t(`queue.priority.${PRIORITY_KEYS[priority] ?? 'normal'}`)}
        </span>
      )}
      {predicted && (
        <span className="inline-flex items-center gap-1 text-bambu-gray" data-testid="queue-item-forecast">
          {t('queue.forecast.doneAround', { time: formatForecastTime(predicted.end, Date.now()) })}
        </span>
      )}
      {warning && (
        <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 bg-amber-500/15 text-amber-700 dark:text-amber-400">
          <AlertTriangle className="w-3 h-3" />
          {t(warning === 'overdue' ? 'queue.due.overdue' : 'queue.due.tooLate')}
        </span>
      )}
    </div>
  );
}

/** Was die Sammel-Änderung an Priorität und Termin ändern soll; fehlende Schlüssel bleiben unverändert, `due_at: null` entfernt den Termin. */
export type BulkPriorityPatch = { priority?: number; due_at?: string | null };

type DueMode = 'unchanged' | 'set' | 'clear';

/** Felder „Priorität" und „Liefertermin" für die Sammel-Änderung; meldet nur, was wirklich geändert werden soll. */
export function BulkPriorityFields({ onChange }: { onChange: (patch: BulkPriorityPatch) => void }) {
  const { t } = useTranslation();
  const [priority, setPriority] = useState('');
  const [dueMode, setDueMode] = useState<DueMode>('unchanged');
  const [dueAt, setDueAt] = useState('');
  const input = 'w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:outline-none focus:border-bambu-green';

  const emit = (next: { priority: string; dueMode: DueMode; dueAt: string }) => {
    const patch: BulkPriorityPatch = {};
    if (next.priority !== '') patch.priority = Number(next.priority);
    if (next.dueMode === 'clear') patch.due_at = null;
    if (next.dueMode === 'set') {
      const due = queuePriorityPayload({ priority: PRIORITY_NORMAL, dueAt: next.dueAt }).due_at;
      if (due) patch.due_at = due;
    }
    onChange(patch);
  };

  return (
    <div className="space-y-3" data-testid="bulk-priority-fields">
      <div>
        <label htmlFor="bulkPriority" className="block text-sm font-medium text-white mb-2">
          {t('queue.priority.label')}
        </label>
        <select
          id="bulkPriority"
          value={priority}
          onChange={(event) => {
            setPriority(event.target.value);
            emit({ priority: event.target.value, dueMode, dueAt });
          }}
          className={input}
        >
          <option value="">{t('queue.bulkEdit.noChange')}</option>
          {PRIORITY_LEVELS.map((level) => (
            <option key={level} value={String(level)}>
              {t(`queue.priority.${PRIORITY_KEYS[level]}`)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="bulkDue" className="block text-sm font-medium text-white mb-2">
          {t('queue.due.label')}
        </label>
        <select
          id="bulkDue"
          value={dueMode}
          onChange={(event) => {
            const mode = event.target.value as DueMode;
            setDueMode(mode);
            emit({ priority, dueMode: mode, dueAt });
          }}
          className={input}
        >
          <option value="unchanged">{t('queue.bulkEdit.noChange')}</option>
          <option value="set">{t('queue.bulkEdit.dueSet')}</option>
          <option value="clear">{t('queue.bulkEdit.dueClear')}</option>
        </select>
        {dueMode === 'set' && (
          <input
            type="datetime-local"
            aria-label={t('queue.due.label')}
            value={dueAt}
            onChange={(event) => {
              setDueAt(event.target.value);
              emit({ priority, dueMode, dueAt: event.target.value });
            }}
            className={`${input} mt-2`}
          />
        )}
      </div>
    </div>
  );
}

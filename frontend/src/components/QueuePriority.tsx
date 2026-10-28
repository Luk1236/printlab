import { useTranslation } from 'react-i18next';
import { AlertTriangle, ArrowUp } from 'lucide-react';

import { PRIORITY_KEYS, PRIORITY_LEVELS, PRIORITY_NORMAL } from '../utils/queuePriority';

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
  item: { priority?: number; due_warning?: 'overdue' | 'too_late' | null; due_at?: string | null; status: string };
}) {
  const { t } = useTranslation();
  const priority = item.priority ?? PRIORITY_NORMAL;
  if (item.status !== 'pending' && item.status !== 'printing') return null;
  if (priority === PRIORITY_NORMAL && !item.due_warning) return null;
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
      {item.due_warning && (
        <span className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 bg-amber-500/15 text-amber-700 dark:text-amber-400">
          <AlertTriangle className="w-3 h-3" />
          {t(item.due_warning === 'overdue' ? 'queue.due.overdue' : 'queue.due.tooLate')}
        </span>
      )}
    </div>
  );
}

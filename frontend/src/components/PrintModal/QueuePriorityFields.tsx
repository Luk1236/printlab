import { useTranslation } from 'react-i18next';

import { PRIORITY_KEYS, PRIORITY_LEVELS } from '../../utils/queuePriority';
import type { ScheduleOptions } from './types';

/** Priorität und optionaler Liefertermin beim Einreihen; der Termin warnt nur, er ändert die Reihenfolge nicht. */
export function QueuePriorityFields({
  options,
  onChange,
}: {
  options: ScheduleOptions;
  onChange: (options: ScheduleOptions) => void;
}) {
  const { t } = useTranslation();
  const input =
    'w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:outline-none focus:border-bambu-green';
  return (
    <div className="space-y-3" data-testid="queue-priority-fields">
      <div>
        <label htmlFor="queuePriority" className="block text-xs text-bambu-gray mb-1">
          {t('queue.priority.label')}
        </label>
        <select
          id="queuePriority"
          value={options.priority}
          onChange={(event) => onChange({ ...options, priority: Number(event.target.value) })}
          className={input}
        >
          {PRIORITY_LEVELS.map((level) => (
            <option key={level} value={level}>
              {t(`queue.priority.${PRIORITY_KEYS[level]}`)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="queueDueAt" className="block text-xs text-bambu-gray mb-1">
          {t('queue.due.label')}
        </label>
        <input
          id="queueDueAt"
          type="datetime-local"
          value={options.dueAt}
          onChange={(event) => onChange({ ...options, dueAt: event.target.value })}
          className={input}
        />
        <p className="mt-1 text-[11px] text-bambu-gray">{t('queue.due.hint')}</p>
      </div>
    </div>
  );
}

/** Auftrags-Priorität der Warteschlange: 2 eilig, 1 normal, 0 niedrig (sortiert vor der Position, siehe backend/app/services/queue_priority.py). */
export const PRIORITY_URGENT = 2;
export const PRIORITY_NORMAL = 1;
export const PRIORITY_LOW = 0;
export const PRIORITY_LEVELS = [PRIORITY_URGENT, PRIORITY_NORMAL, PRIORITY_LOW] as const;

export const PRIORITY_KEYS: Record<number, 'urgent' | 'normal' | 'low'> = {
  [PRIORITY_URGENT]: 'urgent',
  [PRIORITY_NORMAL]: 'normal',
  [PRIORITY_LOW]: 'low',
};

/** Priorität und Liefertermin aus den Einreih-Optionen für die Schnittstelle (Termin leer = kein Termin). */
export function queuePriorityPayload(options: { priority: number; dueAt: string }) {
  const due = options.dueAt ? new Date(options.dueAt) : null;
  return {
    priority: options.priority,
    due_at: due && !isNaN(due.getTime()) ? due.toISOString() : null,
  };
}

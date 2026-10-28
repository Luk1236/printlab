import type { SetupStatus } from '../api/client';

const LEVEL_RANK: Record<string, number> = { required: 0, recommended: 1, optional: 2 };

/** Offene Punkte der Inbetriebnahme, nach Wichtigkeit sortiert (Pflicht, empfohlen, optional). */
export function openSteps(status: SetupStatus) {
  return status.items
    .map((item, order) => ({ item, order }))
    .filter(({ item }) => item.done === false)
    .sort((a, b) => (LEVEL_RANK[a.item.level] ?? 3) - (LEVEL_RANK[b.item.level] ?? 3) || a.order - b.order)
    .map(({ item }) => item);
}

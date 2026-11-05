import {
  ListOrdered,
  ArrowUp,
  ArrowDown,
  ChevronRight,
  ChevronDown,
  Package,
  PackageOpen,
  CheckCircle,
  XCircle,
  SkipForward,
  Ban,
} from 'lucide-react';
import type { PrintQueueItem } from '../api/types';
import { type TimeFormat, formatRelativeTime } from '../utils/date';
import { Button } from './Button';
import { Card } from './Card';
import { CompactHistoryRow } from './CompactHistoryRow';

export const HISTORY_PAGE_SIZE = 50;

export type HistoryRow =
  | { kind: 'item'; item: PrintQueueItem }
  | { kind: 'batch'; batchId: number; batchName: string; items: PrintQueueItem[] };

export interface HistorySectionProps {
  items: PrintQueueItem[];
  collapsed: boolean;
  visibleCount: number;
  onShowMore: () => void;
  sortBy: 'date' | 'name' | 'printer';
  sortAsc: boolean;
  onSortByChange: (v: 'date' | 'name' | 'printer') => void;
  onSortAscToggle: () => void;
  onRemove: (item: PrintQueueItem) => void;
  onRequeue: (item: PrintQueueItem) => void;
  timeFormat: TimeFormat;
  batchCollapsed: Record<number, boolean>;
  toggleBatchCollapsed: (id: number) => void;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  hasPermission: (p: any) => boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  canModify: (resource: any, action: any, createdById?: number | null) => boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function HistorySection({
  items,
  visibleCount,
  onShowMore,
  sortBy,
  sortAsc,
  onSortByChange,
  onSortAscToggle,
  onRemove,
  onRequeue,
  timeFormat,
  batchCollapsed,
  toggleBatchCollapsed,
  hasPermission,
  canModify,
  t,
}: HistorySectionProps) {
  if (items.length === 0) {
    return (
      <Card className="p-12 text-center border-dashed">
        <ListOrdered className="w-16 h-16 text-bambu-gray mx-auto mb-4 opacity-50" />
        <h3 className="text-xl font-medium text-white mb-2">{t('queue.history.emptyTitle')}</h3>
        <p className="text-bambu-gray max-w-md mx-auto">{t('queue.history.emptyDescription')}</p>
      </Card>
    );
  }

  // Group siblings sharing a batch_id into a single collapsible row.
  // First-seen order is preserved for batches; items keep their sorted
  // position from the parent's sort selector.
  const rows: HistoryRow[] = [];
  const seenBatches = new Set<number>();
  for (const item of items.slice(0, visibleCount)) {
    if (item.batch_id != null) {
      if (seenBatches.has(item.batch_id)) continue;
      seenBatches.add(item.batch_id);
      const siblings = items.filter((s) => s.batch_id === item.batch_id);
      rows.push({
        kind: 'batch',
        batchId: item.batch_id,
        batchName: item.batch_name || t('queue.batch.defaultName'),
        items: siblings,
      });
    } else {
      rows.push({ kind: 'item', item });
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3 sm:mb-4">
        <h2 className="text-base sm:text-lg font-semibold text-white flex items-center gap-2">
          {t('queue.sections.history')}
          <span className="text-xs sm:text-sm font-normal text-bambu-gray">
            ({t('queue.itemCount', { count: items.length })})
          </span>
        </h2>
        <div className="flex items-center gap-2">
          <select
            className="px-2 sm:px-3 py-1.5 text-xs sm:text-sm bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
            value={sortBy}
            onChange={(e) => onSortByChange(e.target.value as 'date' | 'name' | 'printer')}
          >
            <option value="date">{t('queue.sort.byDate')}</option>
            <option value="name">{t('queue.sort.byName')}</option>
            <option value="printer">{t('queue.sort.byPrinter')}</option>
          </select>
          <Button
            variant="ghost"
            size="sm"
            onClick={onSortAscToggle}
            title={sortAsc ? t('queue.sort.ascendingOldest') : t('queue.sort.descendingNewest')}
            className="px-2"
          >
            {sortAsc ? <ArrowUp className="w-4 h-4" /> : <ArrowDown className="w-4 h-4" />}
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
        {rows.map((row) => {
          if (row.kind === 'item') {
            return (
              <CompactHistoryRow
                key={row.item.id}
                item={row.item}
                onRemove={() => onRemove(row.item)}
                onRequeue={() => onRequeue(row.item)}
                timeFormat={timeFormat}
                hasPermission={hasPermission}
                canModify={canModify}
                t={t}
              />
            );
          }
          // Batch group — spans the full grid width so it visually anchors
          // its children below it. The children themselves render in the
          // same responsive grid pattern inside the expanded body.
          const collapsed = batchCollapsed[row.batchId] ?? true;
          const completed = row.items.filter((i) => i.status === 'completed').length;
          const failed = row.items.filter((i) => i.status === 'failed').length;
          const skipped = row.items.filter((i) => i.status === 'skipped').length;
          const cancelled = row.items.filter((i) => i.status === 'cancelled').length;
          const latest = row.items
            .map((i) => i.completed_at || i.created_at)
            .filter((v): v is string => !!v)
            .sort()
            .at(-1);
          return (
            <div
              key={`batch-${row.batchId}`}
              className="md:col-span-2 xl:col-span-3 bg-bambu-dark-secondary rounded-lg border border-bambu-dark-tertiary border-l-[3px] border-l-cyan-400"
            >
              <button
                onClick={() => toggleBatchCollapsed(row.batchId)}
                className="w-full flex items-center gap-2 sm:gap-3 px-3 py-2 hover:bg-bambu-dark/30 transition-colors text-left"
                title={collapsed ? t('queue.batch.expand') : t('queue.batch.collapse')}
              >
                {collapsed ? (
                  <ChevronRight className="w-4 h-4 text-bambu-gray shrink-0" />
                ) : (
                  <ChevronDown className="w-4 h-4 text-bambu-gray shrink-0" />
                )}
                {collapsed ? (
                  <Package className="w-5 h-5 text-cyan-700 dark:text-cyan-300 shrink-0" />
                ) : (
                  <PackageOpen className="w-5 h-5 text-cyan-700 dark:text-cyan-300 shrink-0" />
                )}
                <span className="text-sm text-white font-medium truncate min-w-0 flex-1">
                  {row.batchName}
                </span>
                <div className="flex items-center gap-2 text-xs text-bambu-gray shrink-0">
                  {completed > 0 && (
                    <span className="flex items-center gap-1 text-emerald-700 dark:text-emerald-400">
                      <CheckCircle className="w-3 h-3" />
                      {completed}
                    </span>
                  )}
                  {failed > 0 && (
                    <span className="flex items-center gap-1 text-red-700 dark:text-red-400">
                      <XCircle className="w-3 h-3" />
                      {failed}
                    </span>
                  )}
                  {skipped > 0 && (
                    <span className="flex items-center gap-1 text-orange-700 dark:text-orange-400">
                      <SkipForward className="w-3 h-3" />
                      {skipped}
                    </span>
                  )}
                  {cancelled > 0 && (
                    <span className="flex items-center gap-1 text-gray-400">
                      <Ban className="w-3 h-3" />
                      {cancelled}
                    </span>
                  )}
                  <span title={latest ?? undefined}>
                    {latest ? formatRelativeTime(latest, timeFormat, t) : null}
                  </span>
                </div>
              </button>
              {!collapsed && (
                <div className="border-t border-bambu-dark-tertiary bg-black/20 p-2 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2">
                  {row.items.map((child) => (
                    <CompactHistoryRow
                      key={child.id}
                      item={child}
                      onRemove={() => onRemove(child)}
                      onRequeue={() => onRequeue(child)}
                      timeFormat={timeFormat}
                      hasPermission={hasPermission}
                      canModify={canModify}
                      t={t}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      {items.length > visibleCount && (
        <div className="mt-4 flex flex-col items-center gap-2">
          <Button variant="secondary" size="sm" onClick={onShowMore}>
            {t('queue.history.showMore')}
          </Button>
          <span className="text-xs text-bambu-gray">
            {t('queue.history.showingCount', {
              shown: Math.min(visibleCount, items.length),
              total: items.length,
            })}
          </span>
        </div>
      )}
    </div>
  );
}

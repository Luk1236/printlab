import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  Cpu,
  Fan,
  Gauge,
  Loader2,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Thermometer,
  Wrench,
  Zap,
} from 'lucide-react';

import { api } from '../api/client';
import type {
  CountermeasureLogEntry,
  CountermeasuresConfig,
  CountermeasurePrinter,
  ErrorCategory,
  ErrorPattern,
  ErrorPatternAction,
} from '../api/forkApi';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';
import { ConfirmModal } from '../components/ConfirmModal';
import { ErrorPatternIllustration } from '../components/error/ErrorPatternIllustration';
import { Toggle } from '../components/Toggle';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';

const RULE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  chamber_hot: Thermometer,
  chamber_cold: Thermometer,
};

function asList(values: string[] | undefined): string[] {
  return Array.isArray(values) ? values : [];
}

function patternMatches(pattern: ErrorPattern, needle: string): boolean {
  if (!needle) return true;
  const haystack = [
    pattern.title,
    pattern.title_en,
    pattern.summary,
    pattern.summary_en,
    ...asList(pattern.causes),
    ...asList(pattern.slicer),
    ...asList(pattern.automation),
  ]
    .join(' ')
    .toLowerCase();
  return haystack.includes(needle);
}

function List({ title, icon, items }: { title: string; icon: React.ReactNode; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-bambu-gray flex items-center gap-1.5 mb-1">
        {icon}
        {title}
      </h4>
      <ul className="space-y-1">
        {items.map((item) => (
          <li key={item} className="text-sm text-bambu-gray-light leading-snug flex gap-2">
            <span className="text-bambu-gray mt-0.5" aria-hidden="true">
              –
            </span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PatternCard({
  pattern,
  categories,
  expanded,
  onToggle,
  actions,
  canControl,
  onApply,
}: {
  pattern: ErrorPattern;
  categories: ErrorCategory[];
  expanded: boolean;
  onToggle: () => void;
  actions: ErrorPatternAction[];
  canControl: boolean;
  onApply: (action: ErrorPatternAction) => void;
}) {
  const { t, i18n } = useTranslation();
  const german = i18n.language.startsWith('de');
  const category = categories.find((entry) => entry.id === pattern.category);
  return (
    <div className="border border-bambu-dark-tertiary rounded-lg bg-bambu-dark-secondary/60" data-testid={`pattern-${pattern.id}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="w-full flex items-start gap-3 p-4 text-left hover:bg-bambu-dark-tertiary/30 rounded-lg transition-colors"
      >
        <span className="w-24 h-16 shrink-0 rounded-lg bg-gradient-to-br from-bambu-dark-tertiary to-bambu-dark p-1.5" aria-hidden="true">
          <ErrorPatternIllustration patternId={pattern.id} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-white">{german ? pattern.title : pattern.title_en}</span>
          <span className="block text-xs text-bambu-gray mt-1 leading-snug">
            {german ? pattern.summary : pattern.summary_en}
          </span>
          {category && (
            <span className="inline-block mt-2 text-[10px] uppercase tracking-wide text-bambu-gray border border-bambu-dark-tertiary rounded-full px-2 py-0.5">
              {german ? category.title : category.title_en}
            </span>
          )}
        </span>
        <ChevronDown
          className={`w-4 h-4 shrink-0 mt-1 text-bambu-gray transition-transform ${expanded ? 'rotate-180' : ''}`}
          aria-hidden="true"
        />
      </button>
      {expanded && (
        <div className="px-4 pb-4 space-y-3 border-t border-bambu-dark-tertiary/60 pt-3">
          <List title={t('errorHelp.causes')} icon={<AlertTriangle className="w-3.5 h-3.5" />} items={asList(pattern.causes)} />
          <List title={t('errorHelp.slicer')} icon={<SlidersHorizontal className="w-3.5 h-3.5" />} items={asList(pattern.slicer)} />
          <List title={t('errorHelp.automation')} icon={<Cpu className="w-3.5 h-3.5" />} items={asList(pattern.automation)} />
          {actions.length > 0 && (
            <div className="pt-1">
              <h4 className="text-xs font-semibold uppercase tracking-wide text-bambu-gray mb-1.5 flex items-center gap-1.5">
                <Zap className="w-3.5 h-3.5" />
                {t('errorHelp.liveAction')}
              </h4>
              <div className="flex flex-wrap gap-2">
                {actions.map((action) => (
                  <Button
                    key={action.id}
                    size="sm"
                    variant="secondary"
                    disabled={!canControl}
                    title={action.command}
                    onClick={() => onApply(action)}
                  >
                    <Gauge className="w-3.5 h-3.5" />
                    {german ? action.title : action.title_en}
                  </Button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ErrorHelpPage() {
  const { t, i18n } = useTranslation();
  const { hasPermission } = useAuth();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<string>('all');
  const [expanded, setExpanded] = useState<string | null>('heat_creep');
  const [printerId, setPrinterId] = useState<number | null>(null);
  const [pending, setPending] = useState<{ action: ErrorPatternAction; printer: CountermeasurePrinter } | null>(null);

  const canControl = hasPermission('printers:control');
  const canConfigure = hasPermission('settings:update');
  const german = i18n.language.startsWith('de');
  const needle = search.trim().toLowerCase();

  const catalog = useQuery({ queryKey: ['error-help'], queryFn: () => api.getErrorHelp(), staleTime: 5 * 60_000 });
  const countermeasures = useQuery({
    queryKey: ['countermeasures'],
    queryFn: () => api.getCountermeasures(),
    refetchInterval: 15_000,
  });
  const log = useQuery({
    queryKey: ['countermeasure-log'],
    queryFn: () => api.getCountermeasureLog(30),
    refetchInterval: 30_000,
  });

  const save = useMutation({
    mutationFn: (update: Partial<CountermeasuresConfig>) => api.saveCountermeasures(update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['countermeasures'] });
      queryClient.invalidateQueries({ queryKey: ['countermeasure-log'] });
      showToast(t('errorHelp.settingsSaved'));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const apply = useMutation({
    mutationFn: ({ printer, action }: { printer: CountermeasurePrinter; action: ErrorPatternAction }) =>
      api.runCountermeasure(printer.id, action.id),
    onSuccess: (result) => {
      showToast(t('errorHelp.sent', { command: result.command }));
      queryClient.invalidateQueries({ queryKey: ['countermeasure-log'] });
      setPending(null);
    },
    onError: (error: Error) => {
      showToast(error.message, 'error');
      setPending(null);
    },
  });

  const data = catalog.data;
  const printers = countermeasures.data?.printers ?? [];
  const config = countermeasures.data?.config;
  const activePrinter = printers.find((printer) => printer.id === printerId) ?? printers[0] ?? null;
  const availableActions = activePrinter?.available_actions ?? [];

  const filtered = useMemo(() => {
    const patterns = data?.patterns ?? [];
    return patterns.filter(
      (pattern) => (category === 'all' || pattern.category === category) && patternMatches(pattern, needle)
    );
  }, [data?.patterns, category, needle]);

  const actionById = useMemo(() => {
    const map = new Map<string, ErrorPatternAction>();
    for (const action of data?.manual_actions ?? []) map.set(action.id, action);
    return map;
  }, [data?.manual_actions]);

  const patchPrinter = (printer: CountermeasurePrinter, change: { enabled?: boolean; rule?: string; value?: boolean }) => {
    if (!config) return;
    const current = config.printers[String(printer.id)] ?? { enabled: printer.enabled, rules: printer.rules };
    const nextRules = { ...current.rules };
    if (change.rule !== undefined) nextRules[change.rule] = Boolean(change.value);
    const next = {
      ...config.printers,
      [String(printer.id)]: {
        enabled: change.enabled !== undefined ? change.enabled : current.enabled,
        rules: nextRules,
      },
    };
    save.mutate({ printers: next });
  };

  const logEntries: CountermeasureLogEntry[] = log.data ?? [];

  return (
    <div className="p-4 md:p-6 space-y-5 max-w-6xl mx-auto" data-testid="error-help-page">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-white flex items-center gap-2">
          <BookOpen className="w-6 h-6 text-bambu-green" />
          {t('errorHelp.title')}
        </h1>
        <p className="text-sm text-bambu-gray max-w-3xl">{t('errorHelp.hint')}</p>
      </header>

      <Card>
        <CardContent className="space-y-3">
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            <label className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray" aria-hidden="true" />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t('errorHelp.search')}
                aria-label={t('errorHelp.search')}
                className="w-full pl-9 pr-3 py-2 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary text-sm text-white placeholder:text-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green"
              />
            </label>
            <div className="flex flex-wrap gap-1.5" role="group" aria-label={t('errorHelp.categories')}>
              <button
                type="button"
                onClick={() => setCategory('all')}
                className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${
                  category === 'all'
                    ? 'bg-bambu-green text-white border-bambu-green'
                    : 'border-bambu-dark-tertiary text-bambu-gray-light hover:bg-bambu-dark-tertiary'
                }`}
              >
                {t('errorHelp.allCategories')}
              </button>
              {(data?.categories ?? []).map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  onClick={() => setCategory(entry.id)}
                  title={german ? entry.hint : entry.hint_en}
                  className={`px-3 py-1.5 rounded-full text-xs border transition-colors ${
                    category === entry.id
                      ? 'bg-bambu-green text-white border-bambu-green'
                      : 'border-bambu-dark-tertiary text-bambu-gray-light hover:bg-bambu-dark-tertiary'
                  }`}
                >
                  {german ? entry.title : entry.title_en}
                </button>
              ))}
            </div>
          </div>

          {catalog.isLoading && (
            <p className="text-xs text-bambu-gray flex items-center gap-2" role="status">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('common.loading')}
            </p>
          )}
          {!catalog.isLoading && filtered.length === 0 && <p className="text-sm text-bambu-gray">{t('errorHelp.noResults')}</p>}
          <div className="space-y-2">
            {filtered.map((pattern) => {
              const actions = asList(pattern.actions)
                .map((id) => actionById.get(id))
                .filter((action): action is ErrorPatternAction => Boolean(action))
                .filter((action) => availableActions.some((entry) => entry.id === action.id));
              return (
                <PatternCard
                  key={pattern.id}
                  pattern={pattern}
                  categories={data?.categories ?? []}
                  expanded={expanded === pattern.id}
                  onToggle={() => setExpanded(expanded === pattern.id ? null : pattern.id)}
                  actions={actions}
                  canControl={canControl && Boolean(activePrinter?.running)}
                  onApply={(action) => {
                    if (activePrinter) setPending({ action, printer: activePrinter });
                  }}
                />
              );
            })}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                <Fan className="w-5 h-5 text-bambu-green" />
                {t('errorHelp.liveTitle')}
              </h2>
              <p className="text-xs text-bambu-gray mt-1 max-w-3xl">{t('errorHelp.liveHint')}</p>
            </div>
            {printers.length > 0 && (
              <select
                value={activePrinter?.id ?? ''}
                onChange={(event) => setPrinterId(Number(event.target.value))}
                aria-label={t('errorHelp.perPrinter')}
                className="rounded-lg bg-bambu-dark border border-bambu-dark-tertiary text-sm text-white px-3 py-2"
              >
                {printers.map((printer) => (
                  <option key={printer.id} value={printer.id}>
                    {printer.name}
                    {printer.running ? ` · ${t('errorHelp.running')}` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {!activePrinter && <p className="text-sm text-bambu-gray">{t('errorHelp.noPrinter')}</p>}
          {activePrinter && (
            <>
              <p className="text-xs text-bambu-gray">
                {activePrinter.running
                  ? t('errorHelp.printerState', {
                      layer: activePrinter.layer,
                      material: activePrinter.material ? activePrinter.material.toUpperCase() : t('errorHelp.noMaterial'),
                      chamber:
                        activePrinter.chamber_c === null ? '–' : `${activePrinter.chamber_c.toFixed(1)} °C`,
                    })
                  : t('errorHelp.printingOnly')}
              </p>
              <div className="flex flex-wrap gap-2">
                {availableActions.length === 0 && <span className="text-xs text-bambu-gray">{t('errorHelp.noActions')}</span>}
                {availableActions.map(({ id }) => {
                  const action = actionById.get(id);
                  if (!action) return null;
                  return (
                    <Button
                      key={id}
                      size="sm"
                      variant="secondary"
                      disabled={!canControl}
                      onClick={() => activePrinter && setPending({ action, printer: activePrinter })}
                    >
                      <Zap className="w-3.5 h-3.5" />
                      {german ? action.title : action.title_en}
                    </Button>
                  );
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-bambu-green" />
              {t('errorHelp.automTitle')}
            </h2>
            <p className="text-xs text-bambu-gray mt-1 max-w-3xl">{t('errorHelp.automHint')}</p>
          </div>

          {config && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
                <label className="flex items-center gap-2 text-sm text-white">
                  <Toggle checked={config.enabled} onChange={(value) => save.mutate({ enabled: value })} disabled={!canConfigure} />
                  {t('errorHelp.master')}
                </label>
                <label className="flex items-center gap-2 text-sm text-white">
                  <Toggle checked={config.dry_run} onChange={(value) => save.mutate({ dry_run: value })} disabled={!canConfigure} />
                  {t('errorHelp.dryRun')}
                </label>
              </div>

              {printers.length === 0 && <p className="text-sm text-bambu-gray">{t('errorHelp.noPrinter')}</p>}
              <div className="space-y-2">
                {printers.map((printer) => (
                  <div
                    key={printer.id}
                    className="flex flex-col md:flex-row md:items-center gap-3 rounded-lg border border-bambu-dark-tertiary p-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-white font-medium flex items-center gap-2">
                        {printer.name}
                        {printer.running && (
                          <span className="text-[10px] uppercase tracking-wide text-bambu-green border border-bambu-green/40 rounded-full px-2 py-0.5">
                            {t('errorHelp.running')}
                          </span>
                        )}
                      </p>
                      <p className="text-xs text-bambu-gray">
                        {printer.model || '–'}
                        {!printer.chamber_supported && ` · ${t('errorHelp.notSupported')}`}
                      </p>
                    </div>
                    <label className="flex items-center gap-2 text-xs text-bambu-gray-light">
                      <Toggle
                        checked={printer.enabled}
                        disabled={!canConfigure || !printer.chamber_supported}
                        onChange={(value) => patchPrinter(printer, { enabled: value })}
                      />
                      {t('errorHelp.perPrinter')}
                    </label>
                    {Object.entries(countermeasures.data?.rules ?? {}).map(([ruleId, rule]) => {
                      const Icon = RULE_ICONS[ruleId] ?? Wrench;
                      return (
                        <label key={ruleId} className="flex items-center gap-2 text-xs text-bambu-gray-light">
                          <Toggle
                            checked={Boolean(printer.rules[ruleId])}
                            disabled={!canConfigure || !printer.enabled || !printer.chamber_supported}
                            onChange={(value) => patchPrinter(printer, { rule: ruleId, value })}
                          />
                          <Icon className="w-3.5 h-3.5" aria-hidden="true" />
                          <span title={rule.title_en}>{german ? rule.title : rule.title_en}</span>
                        </label>
                      );
                    })}
                  </div>
                ))}
              </div>
              <p className="text-xs text-bambu-gray">
                {t('errorHelp.safety', {
                  max: config.max_per_print,
                  cooldown: config.cooldown_seconds,
                })}
              </p>

              <div className="flex flex-wrap items-end gap-4 pt-1">
                <span className="text-xs font-semibold uppercase tracking-wide text-bambu-gray self-center">
                  {t('errorHelp.thresholds')}
                </span>
                <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                  {t('errorHelp.hotThreshold')}
                  <span className="flex items-center gap-1">
                    <input
                      key={`hot-${config.thresholds.hot_c}`}
                      type="number"
                      min={20}
                      max={70}
                      step={1}
                      defaultValue={config.thresholds.hot_c}
                      disabled={!canConfigure}
                      onBlur={(event) => {
                        const value = Number(event.target.value);
                        if (Number.isFinite(value) && value >= 20 && value <= 70 && value !== config.thresholds.hot_c) {
                          save.mutate({ thresholds: { ...config.thresholds, hot_c: value } });
                        }
                      }}
                      className="w-20 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                    />
                    °C
                  </span>
                </label>
                <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                  {t('errorHelp.coldThreshold')}
                  <span className="flex items-center gap-1">
                    <input
                      key={`cold-${config.thresholds.cold_c}`}
                      type="number"
                      min={20}
                      max={80}
                      step={1}
                      defaultValue={config.thresholds.cold_c}
                      disabled={!canConfigure}
                      onBlur={(event) => {
                        const value = Number(event.target.value);
                        if (Number.isFinite(value) && value >= 20 && value <= 80 && value !== config.thresholds.cold_c) {
                          save.mutate({ thresholds: { ...config.thresholds, cold_c: value } });
                        }
                      }}
                      className="w-20 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                    />
                    °C
                  </span>
                </label>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3">
          <h2 className="text-lg font-semibold text-white">{t('errorHelp.logTitle')}</h2>
          {logEntries.length === 0 && <p className="text-sm text-bambu-gray">{t('errorHelp.logEmpty')}</p>}
          <ul className="space-y-2">
            {logEntries.map((entry, index) => {
              const dry = Boolean(entry.details && (entry.details as { dry_run?: boolean }).dry_run);
              return (
                <li
                  key={`${entry.ts}-${index}`}
                  className="flex flex-col md:flex-row md:items-start gap-2 text-xs border-b border-bambu-dark-tertiary/60 pb-2 last:border-0"
                  data-testid="countermeasure-log-entry"
                >
                  <span className="text-bambu-gray tabular-nums shrink-0">
                    {new Date(entry.ts).toLocaleString(i18n.language)}
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${
                      entry.ok ? 'text-bambu-green border border-bambu-green/40' : 'text-red-600 dark:text-red-400 border border-red-500/40'
                    }`}
                  >
                    {entry.ok ? (dry ? t('errorHelp.dryTag') : t('errorHelp.applied')) : t('errorHelp.failed')}
                  </span>
                  <span className="text-bambu-gray-light min-w-0">{entry.message}</span>
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-3">
          <h2 className="text-lg font-semibold text-white">{t('errorHelp.referenceTitle')}</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-bambu-gray uppercase tracking-wide">
                  <th className="py-2 pr-4 font-semibold">{t('errorHelp.action')}</th>
                  <th className="py-2 pr-4 font-semibold">{t('errorHelp.command')}</th>
                  <th className="py-2 font-semibold">{t('errorHelp.effect')}</th>
                </tr>
              </thead>
              <tbody>
                {(data?.manual_actions ?? []).map((action) => (
                  <tr key={action.id} className="border-t border-bambu-dark-tertiary/60 align-top">
                    <td className="py-2 pr-4 text-white whitespace-nowrap">{german ? action.title : action.title_en}</td>
                    <td className="py-2 pr-4 font-mono text-bambu-gray-light whitespace-nowrap">{action.command}</td>
                    <td className="py-2 text-bambu-gray">{german ? action.effect : action.effect_en}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {pending && (
        <ConfirmModal
          title={t('errorHelp.confirmTitle')}
          message={t('errorHelp.confirmText', {
            action: german ? pending.action.title : pending.action.title_en,
            printer: pending.printer.name,
            command: pending.action.command,
          })}
          confirmText={t('errorHelp.apply')}
          variant="warning"
          isLoading={apply.isPending}
          onConfirm={() => apply.mutate({ printer: pending.printer, action: pending.action })}
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  );
}

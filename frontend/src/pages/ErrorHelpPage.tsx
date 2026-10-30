import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  BookOpen,
  ChevronDown,
  Cpu,
  Download,
  Fan,
  Gauge,
  Images,
  Loader2,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Thermometer,
  ThumbsDown,
  ThumbsUp,
  Wrench,
  X,
  Zap,
} from 'lucide-react';

import { api } from '../api/client';
import type {
  AiScanFinding,
  AiScanResult,
  AiWatchConfig,
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
  detections = 0,
  lastFinding = null,
  onHistory,
}: {
  pattern: ErrorPattern;
  categories: ErrorCategory[];
  expanded: boolean;
  onToggle: () => void;
  actions: ErrorPatternAction[];
  canControl: boolean;
  onApply: (action: ErrorPatternAction) => void;
  detections?: number;
  lastFinding?: AiScanFinding | null;
  onHistory?: () => void;
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
          {detections > 0 && (
            <span
              className="inline-flex items-center gap-1 mt-2 ml-1.5 text-[10px] uppercase tracking-wide text-bambu-green border border-bambu-green/40 rounded-full px-2 py-0.5"
              title={t('errorHelp.aiDetectedCount', { count: detections })}
            >
              <Cpu className="w-3 h-3" aria-hidden="true" />
              {t('errorHelp.aiDetectedCount', { count: detections })}
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
          <div className="rounded-lg bg-gradient-to-br from-bambu-dark-tertiary/70 to-bambu-dark p-3">
            <ErrorPatternIllustration patternId={pattern.id} className="w-full max-h-48" />
          </div>
          <List title={t('errorHelp.causes')} icon={<AlertTriangle className="w-3.5 h-3.5" />} items={asList(pattern.causes)} />
          <List title={t('errorHelp.slicer')} icon={<SlidersHorizontal className="w-3.5 h-3.5" />} items={asList(pattern.slicer)} />
          <List title={t('errorHelp.automation')} icon={<Cpu className="w-3.5 h-3.5" />} items={asList(pattern.automation)} />
          {lastFinding && (
            <div className="rounded-lg border border-bambu-green/30 bg-bambu-green/5 px-3 py-2 text-xs text-bambu-gray-light">
              <span className="text-bambu-green font-medium">{t('errorHelp.aiLast')}</span>{' '}
              {new Date(lastFinding.ts).toLocaleString(i18n.language)} ·{' '}
              {Math.round(lastFinding.confidence * 100)} %{lastFinding.reason ? ` · ${lastFinding.reason}` : ''}
            </div>
          )}
          {detections > 0 && onHistory && (
            <Button size="sm" variant="ghost" onClick={onHistory}>
              <Cpu className="w-3.5 h-3.5" />
              {t('errorHelp.aiHistory')}
            </Button>
          )}
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

function FindingRow({
  finding,
  title,
  canRate,
  onFeedback,
}: {
  finding: AiScanFinding;
  title: string;
  canRate: boolean;
  onFeedback: (verdict: 'correct' | 'wrong') => void;
}) {
  const { t, i18n } = useTranslation();
  return (
    <li className="flex flex-col md:flex-row md:items-baseline gap-1 md:gap-2 text-xs border-b border-bambu-dark-tertiary/50 pb-1 last:border-0">
      <span className="text-bambu-gray tabular-nums shrink-0">{new Date(finding.ts).toLocaleString(i18n.language)}</span>
      <span className="text-white shrink-0">{title}</span>
      <span className="text-bambu-gray shrink-0">{Math.round(finding.confidence * 100)} %</span>
      <span className="text-bambu-gray-light min-w-0 flex-1">{finding.reason}</span>
      {finding.id && (
        <span className="flex items-center gap-1 shrink-0">
          <button
            type="button"
            disabled={!canRate}
            onClick={() => onFeedback('correct')}
            aria-label={t('errorHelp.aiMarkCorrect')}
            title={t('errorHelp.aiMarkCorrect')}
            className={`p-1 rounded transition-colors disabled:opacity-40 ${
              finding.verdict === 'correct' ? 'text-bambu-green' : 'text-bambu-gray hover:text-bambu-green'
            }`}
          >
            <ThumbsUp className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            disabled={!canRate}
            onClick={() => onFeedback('wrong')}
            aria-label={t('errorHelp.aiMarkWrong')}
            title={t('errorHelp.aiMarkWrong')}
            className={`p-1 rounded transition-colors disabled:opacity-40 ${
              finding.verdict === 'wrong' ? 'text-red-500' : 'text-bambu-gray hover:text-red-500'
            }`}
          >
            <ThumbsDown className="w-3.5 h-3.5" />
          </button>
        </span>
      )}
    </li>
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
  const [aiFile, setAiFile] = useState<File | null>(null);
  const [aiResult, setAiResult] = useState<AiScanResult | null>(null);
  const [failureImageName, setFailureImageName] = useState('');
  const [failureFilter, setFailureFilter] = useState('');
  const [historyPattern, setHistoryPattern] = useState<string | null>(null);

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
  const aiScan = useQuery({
    queryKey: ['ai-scan'],
    queryFn: () => api.getAiScan(),
    refetchInterval: (query) => (query.state.data?.batch?.running ? 5_000 : 60_000),
  });
  const aiHistory = useQuery({
    queryKey: ['ai-scan-history', historyPattern],
    queryFn: () => api.getAiFindings(50, historyPattern ?? undefined),
    enabled: historyPattern !== null,
  });
  const aiWatch = useQuery({
    queryKey: ['ai-watch'],
    queryFn: () => api.getAiWatch(),
    refetchInterval: 30_000,
  });
  const failureImages = useQuery({
    queryKey: ['failure-images'],
    queryFn: () => api.listFailureImages(),
    enabled: hasPermission('camera:view'),
  });
  // Die Sammlung kann bis zu 500 Bilder umfassen; ohne Filter ist die Auswahl unbrauchbar.
  const failureFilterTerm = failureFilter.trim().toLowerCase();
  const filteredFailureImages = (failureImages.data ?? []).filter(
    (image) =>
      !failureFilterTerm ||
      `${image.name} ${image.event} ${image.timestamp}`.toLowerCase().includes(failureFilterTerm),
  );

  const aiSave = useMutation({
    mutationFn: (update: {
      vision_model?: string;
      error_scan_enabled?: boolean;
      error_scan_min_confidence?: number;
      error_scan_notify?: boolean;
    }) => api.saveAiScan(update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-scan'] });
      showToast(t('errorHelp.settingsSaved'));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const aiUpload = useMutation({
    mutationFn: (file: File) => api.scanAiErrorImage(file),
    onSuccess: (data) => {
      setAiResult(data.result);
      queryClient.invalidateQueries({ queryKey: ['ai-scan'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const aiFailureImage = useMutation({
    mutationFn: (name: string) => api.scanFailureImage(name),
    onSuccess: (data) => {
      setAiResult(data.result);
      queryClient.invalidateQueries({ queryKey: ['ai-scan'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const aiFeedback = useMutation({
    mutationFn: ({ id, verdict }: { id: string; verdict: 'correct' | 'wrong' }) => api.sendAiFeedback(id, verdict),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-scan'] });
      queryClient.invalidateQueries({ queryKey: ['ai-scan-history'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const aiExport = useMutation({
    mutationFn: () => api.exportFailureImages(),
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      showToast(t('errorHelp.aiExportDone'));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const aiBatch = useMutation({
    mutationFn: () => api.scanAiCollection(10),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-scan'] });
      queryClient.invalidateQueries({ queryKey: ['ai-watch'] });
      showToast(t('errorHelp.aiBatchStarted'));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const watchSave = useMutation({
    mutationFn: (update: Partial<AiWatchConfig>) => api.saveAiWatch(update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-watch'] });
      showToast(t('errorHelp.settingsSaved'));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const watchCheck = useMutation({
    mutationFn: () => api.checkAiWatch(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['ai-watch'] });
      queryClient.invalidateQueries({ queryKey: ['ai-scan'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
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

  const lastFindingByPattern = useMemo(() => {
    const map = new Map<string, AiScanFinding>();
    for (const finding of aiScan.data?.findings ?? []) {
      if (!map.has(finding.pattern_id)) map.set(finding.pattern_id, finding);
    }
    return map;
  }, [aiScan.data?.findings]);

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
                  detections={aiScan.data?.counts[pattern.id] ?? 0}
                  lastFinding={lastFindingByPattern.get(pattern.id) ?? null}
                  onHistory={() => {
                    setHistoryPattern(pattern.id);
                    requestAnimationFrame(() => document.getElementById('ai-scan-card')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
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

      <Card id="ai-scan-card">
        <CardContent className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Cpu className="w-5 h-5 text-bambu-green" />
              {t('errorHelp.aiTitle')}
            </h2>
            <p className="text-xs text-bambu-gray mt-1 max-w-3xl">{t('errorHelp.aiHint')}</p>
          </div>

          {aiScan.isLoading && (
            <p className="text-xs text-bambu-gray flex items-center gap-2" role="status">
              <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('common.loading')}
            </p>
          )}

          {aiScan.data && (
            <>
              <p
                className={`text-xs ${
                  aiScan.data.server.reachable && aiScan.data.vision_present
                    ? 'text-bambu-green'
                    : 'text-amber-700 dark:text-amber-400'
                }`}
              >
                {!aiScan.data.server.reachable
                  ? t('errorHelp.aiServerDown', { error: aiScan.data.server.error || '–' })
                  : aiScan.data.vision_present
                    ? t('errorHelp.aiServerOk', { model: aiScan.data.vision_model })
                    : t('errorHelp.aiModelMissing', { model: aiScan.data.vision_model })}
              </p>
              {aiScan.data.server.reachable && aiScan.data.server.models.length > 0 && (
                <p className="text-[11px] text-bambu-gray">
                  {t('assistant.serverModels', { list: aiScan.data.server.models.join(', ') })}
                </p>
              )}

              <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
                <label className="flex items-center gap-2 text-sm text-white">
                  <Toggle
                    checked={aiScan.data.config.error_scan_enabled}
                    onChange={(value) => aiSave.mutate({ error_scan_enabled: value })}
                    disabled={!canConfigure}
                  />
                  {t('errorHelp.aiEnable')}
                </label>
                <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                  {t('errorHelp.aiThreshold')}
                  <input
                    key={`ai-threshold-${aiScan.data.config.error_scan_min_confidence}`}
                    type="number"
                    min={0}
                    max={100}
                    step={5}
                    defaultValue={aiScan.data.config.error_scan_min_confidence}
                    disabled={!canConfigure}
                    onBlur={(event) => {
                      const value = Number(event.target.value);
                      if (Number.isFinite(value) && value >= 0 && value <= 100) {
                        aiSave.mutate({ error_scan_min_confidence: value });
                      }
                    }}
                    className="w-20 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                  />
                </label>
                <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                  {t('errorHelp.aiModel')}
                  <select
                    key={`ai-model-${aiScan.data.config.vision_model}`}
                    value={aiScan.data.config.vision_model}
                    disabled={!canConfigure}
                    onChange={(event) => aiSave.mutate({ vision_model: event.target.value })}
                    className="w-56 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                  >
                    <option value="">{t('errorHelp.aiModelAssistant', { model: aiScan.data.config.model })}</option>
                    {aiScan.data.server.models.map((model) => (
                      <option key={model} value={model}>
                        {model}
                      </option>
                    ))}
                    {aiScan.data.config.vision_model &&
                      !aiScan.data.server.models.includes(aiScan.data.config.vision_model) && (
                        <option value={aiScan.data.config.vision_model}>
                          {aiScan.data.config.vision_model}
                        </option>
                      )}
                  </select>
                  <span className="text-[10px] text-bambu-gray">{t('errorHelp.aiModelHint')}</span>
                </label>
                <label className="flex items-center gap-2 text-sm text-white">
                  <Toggle
                    checked={aiScan.data.config.error_scan_notify}
                    onChange={(value) => aiSave.mutate({ error_scan_notify: value })}
                    disabled={!canConfigure}
                  />
                  <span className="flex flex-col">
                    {t('errorHelp.aiNotify')}
                    <span className="text-[10px] font-normal text-bambu-gray">{t('errorHelp.aiNotifyHint')}</span>
                  </span>
                </label>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <label className="text-xs text-bambu-gray-light flex items-center gap-2">
                  <span>{t('errorHelp.aiUploadLabel')}</span>
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp"
                    onChange={(event) => setAiFile(event.target.files?.[0] ?? null)}
                    className="text-xs text-bambu-gray"
                  />
                </label>
                <Button
                  size="sm"
                  disabled={!aiFile || aiUpload.isPending || !canControl}
                  onClick={() => aiFile && aiUpload.mutate(aiFile)}
                >
                  {aiUpload.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
                  {aiUpload.isPending ? t('errorHelp.aiScanning') : t('errorHelp.aiAnalyze')}
                </Button>
                {failureImages.data && failureImages.data.length > 0 && (
                  <span className="flex flex-wrap items-center gap-2">
                    <input
                      type="search"
                      value={failureFilter}
                      onChange={(event) => setFailureFilter(event.target.value)}
                      placeholder={t('errorHelp.aiFailureSearch')}
                      className="w-32 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1.5 text-xs text-white"
                      aria-label={t('errorHelp.aiFailureSearch')}
                    />
                    <select
                      value={failureImageName}
                      onChange={(event) => setFailureImageName(event.target.value)}
                      className="max-w-[16rem] rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1.5 text-xs text-white"
                      aria-label={t('errorHelp.aiFailureImage')}
                    >
                      <option value="">{t('errorHelp.aiFailureImage')}</option>
                      {filteredFailureImages.slice(0, 50).map((image) => (
                        <option key={image.name} value={image.name}>
                          {image.event} · {image.timestamp.replace('T', ' ').slice(0, 16)}
                        </option>
                      ))}
                    </select>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!failureImageName || aiFailureImage.isPending || !canControl}
                      onClick={() => aiFailureImage.mutate(failureImageName)}
                    >
                      {aiFailureImage.isPending ? (
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Search className="w-3.5 h-3.5" />
                      )}
                      {t('errorHelp.aiScanFailure')}
                    </Button>
                  </span>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={!canControl || aiBatch.isPending || Boolean(aiScan.data.batch?.running)}
                  onClick={() => aiBatch.mutate()}
                >
                  {aiBatch.isPending || aiScan.data.batch?.running ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Images className="w-3.5 h-3.5" />
                  )}
                  {t('errorHelp.aiBatch')}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={aiExport.isPending || !failureImages.data?.length}
                  onClick={() => aiExport.mutate()}
                  title={t('errorHelp.aiExportHint')}
                >
                  {aiExport.isPending ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <Download className="w-3.5 h-3.5" />
                  )}
                  {t('errorHelp.aiExport')}
                </Button>
                {aiScan.data.batch && (aiScan.data.batch.running || aiScan.data.batch.total > 0) && (
                  <span className="text-xs text-bambu-gray" role="status">
                    {aiScan.data.batch.running
                      ? t('errorHelp.aiBatchProgress', {
                          done: aiScan.data.batch.done,
                          total: aiScan.data.batch.total,
                          matched: aiScan.data.batch.matched,
                        })
                      : t('errorHelp.aiBatchDone', {
                          done: aiScan.data.batch.done,
                          total: aiScan.data.batch.total,
                          matched: aiScan.data.batch.matched,
                          errors: aiScan.data.batch.errors,
                        })}
                  </span>
                )}
              </div>

              {aiResult && (
                <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary/60 p-3 space-y-1">
                  <p className="text-sm font-semibold text-white">
                    {aiResult.pattern_id
                      ? (() => {
                          const hit = data?.patterns.find((entry) => entry.id === aiResult.pattern_id);
                          return hit ? (german ? hit.title : hit.title_en) : aiResult.pattern_id;
                        })()
                      : t('errorHelp.aiNoDefect')}
                  </p>
                  {aiResult.pattern_id && (
                    <p className="text-xs text-bambu-gray">
                      {t('errorHelp.aiConfidence', { value: Math.round(aiResult.confidence * 100) })}
                      {aiResult.duration_ms ? ` · ${(aiResult.duration_ms / 1000).toFixed(0)} s` : ''}
                    </p>
                  )}
                  {aiResult.reason && <p className="text-xs text-bambu-gray-light">{aiResult.reason}</p>}
                </div>
              )}

              <div>
                <div className="flex flex-wrap items-center justify-between gap-2 mb-1">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-bambu-gray">{t('errorHelp.aiFindings')}</h3>
                  {aiScan.data.feedback && (aiScan.data.feedback.correct > 0 || aiScan.data.feedback.wrong > 0) && (
                    <span className="text-[11px] text-bambu-gray">
                      {t('errorHelp.aiFeedbackSummary', {
                        correct: aiScan.data.feedback.correct,
                        wrong: aiScan.data.feedback.wrong,
                      })}
                    </span>
                  )}
                </div>
                {aiScan.data.feedback_by_pattern && Object.keys(aiScan.data.feedback_by_pattern).length > 0 && (
                  <p className="text-[11px] text-bambu-gray mb-1">
                    {t('errorHelp.aiAccuracy')}{' '}
                    {Object.entries(aiScan.data.feedback_by_pattern)
                      .sort((a, b) => b[1].total - a[1].total)
                      .slice(0, 3)
                      .map(([id, row]) => {
                        const hit = data?.patterns.find((entry) => entry.id === id);
                        const title = hit ? (german ? hit.title : hit.title_en) : id;
                        return `${title} ${row.accuracy}% (${row.total})`;
                      })
                      .join(' · ')}
                  </p>
                )}
                {(aiScan.data.findings ?? []).length === 0 ? (
                  <p className="text-xs text-bambu-gray">{t('errorHelp.aiNoFindings')}</p>
                ) : (
                  <ul className="space-y-1">
                    {aiScan.data.findings.slice(0, 8).map((finding) => {
                      const hit = data?.patterns.find((entry) => entry.id === finding.pattern_id);
                      return (
                        <FindingRow
                          key={finding.id || `${finding.ts}-${finding.pattern_id}`}
                          finding={finding}
                          title={hit ? (german ? hit.title : hit.title_en) : finding.pattern_id}
                          canRate={canControl}
                          onFeedback={(verdict) => aiFeedback.mutate({ id: finding.id, verdict })}
                        />
                      );
                    })}
                  </ul>
                )}
              </div>

              <div className="border-t border-bambu-dark-tertiary/60 pt-4 space-y-3">
                <div>
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-bambu-green" />
                    {t('errorHelp.aiWatchTitle')}
                  </h3>
                  <p className="text-xs text-bambu-gray mt-1">{t('errorHelp.aiWatchHint')}</p>
                </div>
                {aiWatch.data && (
                  <>
                    <div className="flex flex-wrap items-end gap-x-5 gap-y-3">
                      <label className="flex items-center gap-2 text-sm text-white">
                        <Toggle
                          checked={aiWatch.data.config.enabled}
                          onChange={(value) => watchSave.mutate({ enabled: value })}
                          disabled={!canConfigure}
                        />
                        {t('errorHelp.aiWatchEnable')}
                      </label>
                      <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                        {t('errorHelp.aiWatchInterval')}
                        <input
                          key={`watch-interval-${aiWatch.data.config.interval_seconds}`}
                          type="number"
                          min={2}
                          max={1440}
                          defaultValue={Math.round(aiWatch.data.config.interval_seconds / 60)}
                          disabled={!canConfigure}
                          onBlur={(event) => {
                            const minutes = Number(event.target.value);
                            if (Number.isFinite(minutes) && minutes >= 2) {
                              watchSave.mutate({ interval_seconds: minutes * 60 });
                            }
                          }}
                          className="w-20 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                        />
                      </label>
                      <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                        {t('errorHelp.aiWatchConsecutive')}
                        <input
                          key={`watch-count-${aiWatch.data.config.min_consecutive}`}
                          type="number"
                          min={1}
                          max={10}
                          defaultValue={aiWatch.data.config.min_consecutive}
                          disabled={!canConfigure}
                          onBlur={(event) => {
                            const value = Number(event.target.value);
                            if (Number.isFinite(value) && value >= 1 && value <= 10) {
                              watchSave.mutate({ min_consecutive: value });
                            }
                          }}
                          className="w-16 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                        />
                      </label>
                      <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                        {t('errorHelp.aiWatchCooldown')}
                        <input
                          key={`watch-cooldown-${aiWatch.data.config.cooldown_minutes}`}
                          type="number"
                          min={0}
                          max={1440}
                          defaultValue={aiWatch.data.config.cooldown_minutes}
                          disabled={!canConfigure}
                          onBlur={(event) => {
                            const value = Number(event.target.value);
                            if (Number.isFinite(value) && value >= 0) {
                              watchSave.mutate({ cooldown_minutes: value });
                            }
                          }}
                          className="w-20 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                        />
                      </label>
                      <label className="text-xs text-bambu-gray-light flex flex-col gap-1">
                        {t('errorHelp.aiWatchAction')}
                        <select
                          value={aiWatch.data.config.action}
                          disabled={!canConfigure}
                          onChange={(event) =>
                            watchSave.mutate({ action: event.target.value as AiWatchConfig['action'] })
                          }
                          className="rounded-lg bg-bambu-dark border border-bambu-dark-tertiary px-2 py-1 text-sm text-white"
                        >
                          <option value="notify">{t('errorHelp.aiWatchNotify')}</option>
                          <option value="pause">{t('errorHelp.aiWatchPause')}</option>
                        </select>
                      </label>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!canControl || watchCheck.isPending}
                        onClick={() => watchCheck.mutate()}
                      >
                        {watchCheck.isPending ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Search className="w-3.5 h-3.5" />
                        )}
                        {watchCheck.isPending ? t('errorHelp.aiWatchChecking') : t('errorHelp.aiWatchCheckNow')}
                      </Button>
                      <span className="text-[11px] text-bambu-gray">
                        {aiWatch.data.state.last_run
                          ? t('errorHelp.aiWatchLast', {
                              time: new Date(aiWatch.data.state.last_run).toLocaleString(i18n.language),
                            })
                          : t('errorHelp.aiWatchNever')}
                        {aiWatch.data.state.last_error ? ` · ${aiWatch.data.state.last_error}` : ''}
                      </span>
                    </div>
                    {aiWatch.data.printers.length > 0 && (
                      <ul className="space-y-1">
                        {aiWatch.data.printers.map((printer) => (
                          <li key={printer.id} className="text-[11px] text-bambu-gray flex flex-wrap gap-2">
                            <span className="text-white">{printer.name}</span>
                            {printer.last_checked && (
                              <span>{new Date(printer.last_checked).toLocaleTimeString(i18n.language)}</span>
                            )}
                            {printer.pattern ? (
                              <span className="text-bambu-gray-light">
                                {(() => {
                                  const hit = data?.patterns.find((entry) => entry.id === printer.pattern);
                                  return hit ? (german ? hit.title : hit.title_en) : printer.pattern;
                                })()}
                                {printer.last_confidence != null
                                  ? ` · ${Math.round(printer.last_confidence * 100)} % · ${printer.count ?? 0}×`
                                  : ''}
                              </span>
                            ) : (
                              <span>{t('errorHelp.aiWatchNothing')}</span>
                            )}
                            {printer.last_error && <span className="text-amber-700 dark:text-amber-400">{printer.last_error}</span>}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {historyPattern && (
        <Card>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <h2 className="text-lg font-semibold text-white">
                {t('errorHelp.aiHistoryTitle', {
                  pattern: (() => {
                    const hit = data?.patterns.find((entry) => entry.id === historyPattern);
                    return hit ? (german ? hit.title : hit.title_en) : historyPattern;
                  })(),
                })}
              </h2>
              <Button size="sm" variant="ghost" onClick={() => setHistoryPattern(null)} aria-label={t('common.close')}>
                <X className="w-4 h-4" />
              </Button>
            </div>
            {aiHistory.isLoading && (
              <p className="text-xs text-bambu-gray flex items-center gap-2" role="status">
                <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('common.loading')}
              </p>
            )}
            {aiHistory.data && aiHistory.data.findings.length === 0 && (
              <p className="text-xs text-bambu-gray">{t('errorHelp.aiHistoryEmpty')}</p>
            )}
            {aiHistory.data && aiHistory.data.findings.length > 0 && (
              <ul className="space-y-1">
                {aiHistory.data.findings.map((finding) => (
                  <FindingRow
                    key={finding.id || `${finding.ts}-${finding.pattern_id}`}
                    finding={finding}
                    title={(() => {
                      const hit = data?.patterns.find((entry) => entry.id === finding.pattern_id);
                      return hit ? (german ? hit.title : hit.title_en) : finding.pattern_id;
                    })()}
                    canRate={canControl}
                    onFeedback={(verdict) => aiFeedback.mutate({ id: finding.id, verdict })}
                  />
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

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

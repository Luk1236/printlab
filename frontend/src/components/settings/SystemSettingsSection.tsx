import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocation } from 'react-router-dom';
import {
  Activity,
  HeartPulse,
  RefreshCw,
  FileText,
  Stethoscope,
  Download,
  Server,
  HardDrive,
  Cpu,
  Loader2,
  CheckCircle2,
  XCircle,
  Database,
  Archive,
  Clock,
  Printer,
  MemoryStick,
  Palette,
  Plug,
  FolderKanban,
  FolderOpen,
  Bug,
  LayoutGrid,
} from 'lucide-react';

import { api, supportApi, type Printer as PrinterModel } from '../../api/client';
import { Card, CardHeader, CardContent } from '../Card';
import { Button } from '../Button';
import { SystemHealthPanel } from '../SystemHealthPanel';
import { LogViewer } from '../LogViewer';
import { ConnectionDiagnosticModal } from '../ConnectionDiagnostic';
import { useToast } from '../../contexts/ToastContext';
import { formatDateTime, type TimeFormat } from '../../utils/date';

export type SystemSubTab = 'overview' | 'diagnostics' | 'logs' | 'all';

const ANCHOR_SUBTAB_MAP: Record<string, SystemSubTab> = {
  'system-resources': 'overview',
  'system-storage': 'overview',
  'system-database': 'overview',
  'system-printers': 'overview',
  'system-health': 'diagnostics',
  'system-diagnostic': 'diagnostics',
  'system-support': 'logs',
  'system-logs': 'logs',
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function StatCard({
  icon: Icon,
  label,
  value,
  subValue,
  color = 'text-bambu-green',
}: {
  icon: React.ElementType;
  label: string;
  value: string | number;
  subValue?: string;
  color?: string;
}) {
  return (
    <div className="flex items-start gap-3 p-4 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary">
      <div className={`p-2 rounded-lg bg-bambu-dark-secondary ${color}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-xs text-bambu-gray font-medium">{label}</p>
        <p className="text-base font-semibold text-white truncate mt-0.5">{value}</p>
        {subValue && <p className="text-xs text-bambu-gray mt-0.5">{subValue}</p>}
      </div>
    </div>
  );
}

function ProgressBar({ percent, color = 'bg-bambu-green' }: { percent: number; color?: string }) {
  return (
    <div className="w-full h-2 bg-bambu-dark rounded-full overflow-hidden">
      <div
        className={`h-full ${color} transition-all duration-300`}
        style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
      />
    </div>
  );
}

export interface SystemSettingsSectionProps {
  printers?: PrinterModel[];
}

export function SystemSettingsSection({ printers: propPrinters }: SystemSettingsSectionProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();

  const [activeSubTab, setActiveSubTab] = useState<SystemSubTab>('overview');
  const [diagnosticPrinter, setDiagnosticPrinter] = useState<PrinterModel | null>(null);
  const [downloadingBundle, setDownloadingBundle] = useState(false);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const [debugToggling, setDebugToggling] = useState(false);

  const {
    data: systemInfo,
    isLoading: infoLoading,
    refetch: refetchInfo,
    isFetching: infoFetching,
  } = useQuery({
    queryKey: ['systemInfo'],
    queryFn: api.getSystemInfo,
    refetchInterval: 30000,
  });

  const {
    data: systemHealth,
    refetch: refetchHealth,
    isFetching: healthFetching,
  } = useQuery({
    queryKey: ['systemHealth'],
    queryFn: api.getSystemHealth,
    staleTime: 60 * 1000,
  });

  const { data: debugLoggingState } = useQuery({
    queryKey: ['debugLogging'],
    queryFn: supportApi.getDebugLoggingState,
    staleTime: 10 * 1000,
    refetchInterval: 10 * 1000,
  });

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  });

  const { data: libraryStats } = useQuery({
    queryKey: ['library-stats'],
    queryFn: api.getLibraryStats,
  });

  const { data: allPrinters } = useQuery({
    queryKey: ['printers'],
    queryFn: api.getPrinters,
  });

  const printersList = propPrinters ?? allPrinters ?? [];
  const timeFormat: TimeFormat = settings?.time_format || 'system';

  // Handle anchor jump
  useEffect(() => {
    const anchor = location.hash.replace('#', '');
    if (!anchor) return;
    const targetSubTab = ANCHOR_SUBTAB_MAP[anchor];
    if (targetSubTab && activeSubTab !== targetSubTab && activeSubTab !== 'all') {
      setActiveSubTab(targetSubTab);
    }
    const timer = window.setTimeout(() => {
      const el = document.getElementById(anchor);
      if (el) {
        el.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
        el.classList.add('ring-2', 'ring-bambu-green');
        window.setTimeout(() => el.classList.remove('ring-2', 'ring-bambu-green'), 1500);
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, [location.hash]);

  const handleToggleDebugLogging = async () => {
    setDebugToggling(true);
    try {
      const newState = await supportApi.setDebugLogging(!debugLoggingState?.enabled);
      queryClient.setQueryData(['debugLogging'], newState);
      showToast(
        newState.enabled
          ? t('support.debugLoggingEnabledToast', 'Debug-Logging aktiviert')
          : t('support.debugLoggingDisabledToast', 'Debug-Logging deaktiviert'),
        'info'
      );
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Fehler beim Umschalten des Debug-Loggings', 'error');
    } finally {
      setDebugToggling(false);
    }
  };

  const handleDownloadBundle = async () => {
    setBundleError(null);
    setDownloadingBundle(true);
    try {
      await supportApi.downloadSupportBundle();
      showToast(t('system.supportBundleSuccess', 'Support-Paket heruntergeladen'), 'success');
    } catch (err) {
      const msg = err instanceof Error ? err.message : t('system.supportBundleFailed', 'Download fehlgeschlagen');
      setBundleError(msg);
      showToast(msg, 'error');
    } finally {
      setDownloadingBundle(false);
    }
  };

  const isRefreshing = infoFetching || healthFetching;

  const handleRefreshAll = () => {
    refetchInfo();
    refetchHealth();
  };

  const diskColor =
    (systemInfo?.storage.disk_percent_used ?? 0) > 90
      ? 'bg-red-500'
      : (systemInfo?.storage.disk_percent_used ?? 0) > 75
      ? 'bg-yellow-500'
      : 'bg-bambu-green';

  const memoryColor =
    (systemInfo?.memory.percent_used ?? 0) > 90
      ? 'bg-red-500'
      : (systemInfo?.memory.percent_used ?? 0) > 75
      ? 'bg-yellow-500'
      : 'bg-bambu-green';

  return (
    <div className="space-y-6">
      {/* Intro Header Card */}
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-bambu-green/10 text-bambu-green shrink-0">
                <Activity className="w-6 h-6" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-white">
                  {t('nav.systemStatus', 'Systemzustand & Diagnose')}
                </h2>
                <p className="text-sm text-bambu-gray">
                  {t(
                    'system.overviewDescription',
                    'Gesamtzustand der PrintLab-Dienste, Hardwareressourcen, Verbindungstests und Protokolle'
                  )}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={handleRefreshAll}
                disabled={isRefreshing}
                className="gap-1.5"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isRefreshing ? 'animate-spin' : ''}`} />
                <span>{t('common.refresh', 'Aktualisieren')}</span>
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Sub-tab Navigation */}
      <div
        className="flex items-center gap-1.5 p-1 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary overflow-x-auto"
        role="tablist"
        aria-label="Systemzustand Unterbereiche"
      >
        <button
          role="tab"
          aria-selected={activeSubTab === 'overview'}
          onClick={() => setActiveSubTab('overview')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'overview'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <HardDrive className="w-4 h-4" />
          <span>{t('system.subtabResources', 'Hardware & Ressourcen')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'diagnostics'}
          onClick={() => setActiveSubTab('diagnostics')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'diagnostics'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <HeartPulse className="w-4 h-4" />
          <span>{t('systemHealth.sectionTitle', 'Systemgesundheit & Tests')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'logs'}
          onClick={() => setActiveSubTab('logs')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'logs'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <FileText className="w-4 h-4" />
          <span>{t('system.subtabLogs', 'Support & Protokolle')}</span>
          {debugLoggingState?.enabled && (
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
          )}
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'all'}
          onClick={() => setActiveSubTab('all')}
          className={`px-3 py-2 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 shrink-0 ml-auto ${
            activeSubTab === 'all'
              ? 'bg-bambu-dark-tertiary text-white'
              : 'text-bambu-gray hover:text-white'
          }`}
          title={t('setupGuide.tabAllTitle', 'Alle Bereiche untereinander anzeigen')}
        >
          <LayoutGrid className="w-3.5 h-3.5" />
          <span>{t('setupGuide.tabAll', 'Alle Bereiche')}</span>
        </button>
      </div>

      {infoLoading && !systemInfo ? (
        <div className="flex items-center justify-center h-48 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary">
          <Loader2 className="w-8 h-8 text-bambu-green animate-spin" />
        </div>
      ) : null}

      {/* 1. Hardware, Ressourcen & Datenbank */}
      {(activeSubTab === 'overview' || activeSubTab === 'all') && systemInfo && (
        <div className="space-y-6">
          {/* Basisdaten & Uptime */}
          <Card id="system-resources">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Server className="w-5 h-5 text-bambu-green" />
                <h3 className="font-semibold text-white">{t('system.application', 'System & Anwendung')}</h3>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <StatCard
                  icon={Server}
                  label={t('system.version', 'Version')}
                  value={`v${systemInfo.app.version}`}
                />
                <StatCard
                  icon={Clock}
                  label={t('system.uptime', 'System Uptime')}
                  value={systemInfo.system.uptime_formatted}
                />
                <StatCard
                  icon={Server}
                  label={t('system.hostname', 'Hostname')}
                  value={systemInfo.system.hostname}
                />
                <StatCard
                  icon={Cpu}
                  label={t('system.platform', 'Plattform / OS')}
                  value={systemInfo.system.platform}
                  subValue={systemInfo.system.platform_release}
                />
              </div>
            </CardContent>
          </Card>

          {/* CPU & Arbeitsspeicher */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* CPU */}
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <Cpu className="w-5 h-5 text-bambu-green" />
                  <h3 className="font-semibold text-white">{t('system.cpu', 'Prozessor (CPU)')}</h3>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <StatCard
                    icon={Cpu}
                    label={t('system.cores', 'Kerne')}
                    value={systemInfo.cpu.count}
                    subValue={`${systemInfo.cpu.count_logical} logisch`}
                  />
                  <StatCard
                    icon={Cpu}
                    label={t('system.usage', 'Auslastung')}
                    value={`${systemInfo.cpu.percent}%`}
                  />
                </div>
                <div>
                  <div className="flex justify-between text-xs text-bambu-gray mb-1">
                    <span>{t('system.cpuLoad', 'Gesamtauslastung')}</span>
                    <span className="text-white font-medium">{systemInfo.cpu.percent}%</span>
                  </div>
                  <ProgressBar percent={systemInfo.cpu.percent} />
                </div>
              </CardContent>
            </Card>

            {/* RAM */}
            <Card>
              <CardHeader>
                <div className="flex items-center gap-2">
                  <MemoryStick className="w-5 h-5 text-bambu-green" />
                  <h3 className="font-semibold text-white">{t('system.memory', 'Arbeitsspeicher (RAM)')}</h3>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div>
                  <div className="flex justify-between text-xs text-bambu-gray mb-1">
                    <span>{t('system.memoryUsage', 'Belegter Speicher')}</span>
                    <span className="text-white font-medium">
                      {systemInfo.memory.used_formatted} / {systemInfo.memory.total_formatted} (
                      {systemInfo.memory.percent_used.toFixed(1)}%)
                    </span>
                  </div>
                  <ProgressBar percent={systemInfo.memory.percent_used} color={memoryColor} />
                  <p className="text-xs text-bambu-gray mt-1">
                    {systemInfo.memory.available_formatted} {t('system.available', 'verfügbar')}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Speicherplatz (Disk & DB) */}
          <Card id="system-storage">
            <CardHeader>
              <div className="flex items-center gap-2">
                <HardDrive className="w-5 h-5 text-bambu-green" />
                <h3 className="font-semibold text-white">{t('system.storage', 'Speicherbelegung')}</h3>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <div className="flex justify-between text-xs text-bambu-gray mb-1">
                  <span>{t('system.diskUsage', 'Festplattenbelegung')}</span>
                  <span className="text-white font-medium">
                    {systemInfo.storage.disk_used_formatted} / {systemInfo.storage.disk_total_formatted}
                  </span>
                </div>
                <ProgressBar percent={systemInfo.storage.disk_percent_used} color={diskColor} />
                <p className="text-xs text-bambu-gray mt-1">
                  {systemInfo.storage.disk_free_formatted} {t('system.free', 'frei')} (
                  {(100 - systemInfo.storage.disk_percent_used).toFixed(1)}%)
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
                <StatCard
                  icon={Archive}
                  label={t('system.archiveStorage', 'Druckarchiv')}
                  value={systemInfo.storage.archive_size_formatted}
                />
                <StatCard
                  icon={Database}
                  label={t('system.databaseSize', 'Datenbankgröße')}
                  value={systemInfo.storage.database_size_formatted}
                />
                {libraryStats ? (
                  <StatCard
                    icon={FolderOpen}
                    label={t('system.fileManagerStorage', 'Dateimanager')}
                    value={formatBytes(libraryStats.total_size_bytes)}
                    subValue={`${libraryStats.total_files} Dateien`}
                  />
                ) : null}
              </div>
            </CardContent>
          </Card>

          {/* Datenbank-Details */}
          <Card id="system-database">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Database className="w-5 h-5 text-bambu-green" />
                <h3 className="font-semibold text-white">{t('system.database', 'Datenbank & Statistik')}</h3>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <StatCard
                  icon={Database}
                  label={t('system.dbEngine', 'Datenbank-Engine')}
                  value={systemInfo.database.engine || 'SQLite'}
                />
                <StatCard
                  icon={Database}
                  label={t('system.dbVersion', 'Version')}
                  value={systemInfo.database.version || 'unknown'}
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <StatCard
                  icon={Archive}
                  label={t('system.totalArchives', 'Einträge')}
                  value={systemInfo.database.archives}
                />
                <StatCard
                  icon={CheckCircle2}
                  label={t('system.completed', 'Abgeschlossen')}
                  value={systemInfo.database.archives_completed}
                  color="text-green-500"
                />
                <StatCard
                  icon={XCircle}
                  label={t('system.failed', 'Fehlgeschlagen')}
                  value={systemInfo.database.archives_failed}
                  color="text-red-500"
                />
                <StatCard
                  icon={Loader2}
                  label={t('system.printing', 'Aktiv')}
                  value={systemInfo.database.archives_printing}
                  color="text-yellow-500"
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <StatCard
                  icon={Printer}
                  label={t('system.printers', 'Drucker')}
                  value={systemInfo.database.printers}
                />
                <StatCard
                  icon={Palette}
                  label={t('system.filaments', 'Filamente')}
                  value={systemInfo.database.filaments}
                />
                <StatCard
                  icon={FolderKanban}
                  label={t('system.projects', 'Projekte')}
                  value={systemInfo.database.projects}
                />
                <StatCard
                  icon={Plug}
                  label={t('system.smartPlugs', 'Smart Plugs')}
                  value={systemInfo.database.smart_plugs}
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
                <StatCard
                  icon={Clock}
                  label={t('system.totalPrintTime', 'Gesamte Druckzeit')}
                  value={systemInfo.database.total_print_time_formatted}
                />
                <StatCard
                  icon={Archive}
                  label={t('system.totalFilament', 'Verbrauchtes Filament')}
                  value={`${systemInfo.database.total_filament_kg} kg`}
                  subValue={`${systemInfo.database.total_filament_grams.toLocaleString()} g`}
                />
              </div>
            </CardContent>
          </Card>

          {/* Verbundene Drucker */}
          <Card id="system-printers">
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Printer className="w-5 h-5 text-bambu-green" />
                  <h3 className="font-semibold text-white">{t('system.connectedPrinters', 'Verbundene Drucker')}</h3>
                </div>
                <span className="text-xs text-bambu-gray">
                  {systemInfo.printers.connected} / {systemInfo.printers.total} {t('common.online', 'verbunden')}
                </span>
              </div>
            </CardHeader>
            <CardContent>
              {systemInfo.printers.connected_list.length > 0 ? (
                <div className="divide-y divide-bambu-dark-tertiary">
                  {systemInfo.printers.connected_list.map((p) => (
                    <div key={p.id} className="py-2.5 flex items-center justify-between first:pt-0 last:pb-0">
                      <div className="flex items-center gap-2.5">
                        <span className="w-2 h-2 rounded-full bg-bambu-green shrink-0" />
                        <span className="text-sm font-medium text-white">{p.name}</span>
                        <span className="text-xs text-bambu-gray">{p.model}</span>
                      </div>
                      <span className="text-xs font-mono px-2 py-0.5 rounded bg-bambu-green/10 text-bambu-green">
                        {p.state}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-bambu-gray">{t('system.noPrintersConnected', 'Keine Drucker verbunden')}</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* 2. Systemprüfung & Verbindungsdiagnose */}
      {(activeSubTab === 'diagnostics' || activeSubTab === 'all') && (
        <div className="space-y-6">
          {/* Live System Health */}
          <Card id="system-health">
            <CardHeader>
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                <div className="flex items-center gap-2">
                  <HeartPulse className="w-5 h-5 text-bambu-green" />
                  <div>
                    <h3 className="font-semibold text-white">{t('systemHealth.sectionTitle', 'Systemgesundheit')}</h3>
                    <p className="text-xs text-bambu-gray">
                      {t('systemHealth.sectionDescription', 'Echtzeit-Prüfung aller internen Dienste und Datenbanken')}
                    </p>
                  </div>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => refetchHealth()}
                  disabled={healthFetching}
                  className="gap-1.5 shrink-0"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${healthFetching ? 'animate-spin' : ''}`} />
                  <span>{t('systemHealth.rescan', 'Erneut prüfen')}</span>
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {systemHealth ? (
                <SystemHealthPanel result={systemHealth} />
              ) : (
                <div className="flex items-center justify-center p-8">
                  <Loader2 className="w-6 h-6 text-bambu-green animate-spin" />
                </div>
              )}
            </CardContent>
          </Card>

          {/* Verbindungsdiagnose für Drucker */}
          <Card id="system-diagnostic">
            <CardHeader>
              <div className="flex items-center gap-2">
                <Stethoscope className="w-5 h-5 text-bambu-green" />
                <div>
                  <h3 className="font-semibold text-white">
                    {t('diagnostic.sectionTitle', 'Drucker-Verbindungsdiagnose')}
                  </h3>
                  <p className="text-xs text-bambu-gray">
                    {t(
                      'diagnostic.sectionDescription',
                      'Prüft Port-Erreichbarkeit, LAN-Entwicklermodus, Docker-Netzwerk und Zugangsdaten.'
                    )}
                  </p>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {printersList.length > 0 ? (
                <div className="space-y-2">
                  {printersList.map((printer) => (
                    <div
                      key={printer.id}
                      className="flex items-center justify-between p-3 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary"
                    >
                      <div className="min-w-0">
                        <span className="font-medium text-white">{printer.name}</span>
                        <span className="text-xs text-bambu-gray ml-2">{printer.ip_address}</span>
                      </div>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => setDiagnosticPrinter(printer)}
                        className="gap-1.5 shrink-0"
                      >
                        <Stethoscope className="w-4 h-4 text-bambu-green" />
                        <span>{t('diagnostic.runButton', 'Diagnose starten')}</span>
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-bambu-gray">{t('diagnostic.noPrinters', 'Keine Drucker eingerichtet.')}</p>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* 3. Support & Protokolle */}
      {(activeSubTab === 'logs' || activeSubTab === 'all') && (
        <div className="space-y-6">
          {/* Debug Logging & Support Bundle */}
          <Card id="system-support">
            <CardHeader>
              <div className="flex items-center gap-2">
                <FileText className="w-5 h-5 text-bambu-green" />
                <div>
                  <h3 className="font-semibold text-white">{t('support.title', 'Support & Fehlerbehebung')}</h3>
                  <p className="text-xs text-bambu-gray">
                    {t(
                      'support.description',
                      'Aktivieren Sie das Debug-Logging und laden Sie ein Support-Paket für Fehlerberichte herunter.'
                    )}
                  </p>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Debug Toggle */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-4 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary">
                <div className="flex items-center gap-3">
                  <div
                    className={`p-2.5 rounded-xl ${
                      debugLoggingState?.enabled
                        ? 'bg-amber-500/20 text-amber-500'
                        : 'bg-bambu-dark-secondary text-bambu-gray'
                    }`}
                  >
                    <Bug className="w-5 h-5" />
                  </div>
                  <div>
                    <p className="font-medium text-white">{t('support.debugLogging', 'Debug-Logging')}</p>
                    <p className="text-xs text-bambu-gray">
                      {debugLoggingState?.enabled
                        ? t('support.debugLoggingEnabled', 'Erfasst detaillierte Protokolle')
                        : t('support.debugLoggingDisabled', 'Normaler Protokolliergrad')}
                      {debugLoggingState?.enabled && debugLoggingState.duration_seconds !== null && (
                        <span className="text-amber-500 font-mono ml-2">
                          ({Math.floor(debugLoggingState.duration_seconds / 60)}m {debugLoggingState.duration_seconds % 60}s)
                        </span>
                      )}
                    </p>
                  </div>
                </div>
                <Button
                  onClick={handleToggleDebugLogging}
                  disabled={debugToggling}
                  variant={debugLoggingState?.enabled ? 'danger' : 'primary'}
                  size="sm"
                  className="gap-1.5 shrink-0"
                >
                  {debugToggling && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>
                    {debugLoggingState?.enabled
                      ? t('support.disableDebug', 'Deaktivieren')
                      : t('support.enableDebug', 'Aktivieren')}
                  </span>
                </Button>
              </div>

              {/* Support Bundle Download */}
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 p-4 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-bambu-green/10 text-bambu-green">
                    <Download className="w-5 h-5" />
                  </div>
                  <div>
                    <p className="font-medium text-white">{t('support.supportBundle', 'Support-Paket (ZIP)')}</p>
                    <p className="text-xs text-bambu-gray">
                      {t('support.supportBundleDescription', 'Systeminformationen und bereinigte Protokolle herunterladen')}
                    </p>
                  </div>
                </div>
                <Button
                  onClick={handleDownloadBundle}
                  disabled={downloadingBundle}
                  variant="secondary"
                  size="sm"
                  className="gap-1.5 shrink-0"
                >
                  {downloadingBundle && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  <span>
                    {downloadingBundle
                      ? t('support.bundleGenerating', 'Wird erstellt...')
                      : t('common.download', 'Herunterladen')}
                  </span>
                </Button>
              </div>

              {bundleError && (
                <div className="p-3 bg-red-500/20 border border-red-500/30 rounded-xl text-red-400 text-xs">
                  {bundleError}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Integrierter LogViewer */}
          <Card id="system-logs">
            <CardHeader>
              <div className="flex items-center gap-2">
                <FileText className="w-5 h-5 text-bambu-green" />
                <h3 className="font-semibold text-white">{t('support.liveLogs', 'Live-Protokoll')}</h3>
              </div>
            </CardHeader>
            <CardContent>
              <LogViewer />
            </CardContent>
          </Card>
        </div>
      )}

      {/* Connection Diagnostic Modal */}
      {diagnosticPrinter && (
        <ConnectionDiagnosticModal
          printerId={diagnosticPrinter.id}
          printerName={diagnosticPrinter.name}
          onClose={() => setDiagnosticPrinter(null)}
        />
      )}
    </div>
  );
}

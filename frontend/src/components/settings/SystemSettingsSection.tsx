import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Activity,
  HeartPulse,
  RefreshCw,
  FileText,
  Stethoscope,
  Download,
  ExternalLink,
  Server,
  HardDrive,
  Cpu,
  Loader2,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import { api, supportApi, type Printer as PrinterModel } from '../../api/client';
import { Card, CardHeader, CardContent } from '../Card';
import { Button } from '../Button';
import { SystemHealthPanel } from '../SystemHealthPanel';
import { LogViewer } from '../LogViewer';
import { ConnectionDiagnosticModal } from '../ConnectionDiagnostic';
import { useToast } from '../../contexts/ToastContext';

export interface SystemSettingsSectionProps {
  printers?: PrinterModel[];
}

export function SystemSettingsSection({ printers = [] }: SystemSettingsSectionProps) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [showLogs, setShowLogs] = useState(false);
  const [diagnosticPrinter, setDiagnosticPrinter] = useState<PrinterModel | null>(null);
  const [downloadingBundle, setDownloadingBundle] = useState(false);

  const {
    data: systemHealth,
    refetch: refetchHealth,
    isFetching: healthFetching,
  } = useQuery({
    queryKey: ['systemHealth'],
    queryFn: api.getSystemHealth,
    staleTime: 60 * 1000,
  });

  const handleDownloadBundle = async () => {
    setDownloadingBundle(true);
    try {
      await supportApi.downloadSupportBundle();
      showToast(t('system.supportBundleSuccess', 'Support-Paket heruntergeladen'), 'success');
    } catch (err) {
      showToast(
        err instanceof Error ? err.message : t('system.supportBundleFailed', 'Download fehlgeschlagen'),
        'error'
      );
    } finally {
      setDownloadingBundle(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Overview & Quick Actions */}
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
                    'Gesamtzustand der PrintLab-Dienste, Hardwareressourcen und Protokolle'
                  )}
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Link to="/system">
                <Button variant="secondary" size="sm" className="gap-1.5">
                  <ExternalLink className="w-3.5 h-3.5" />
                  <span>{t('system.openFullPage', 'Vollansicht')}</span>
                </Button>
              </Link>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => refetchHealth()}
                disabled={healthFetching}
                className="gap-1.5"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${healthFetching ? 'animate-spin' : ''}`} />
                <span>{t('common.refresh', 'Aktualisieren')}</span>
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {/* Log Viewer Trigger */}
            <button
              onClick={() => setShowLogs(true)}
              className="p-3 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary hover:border-bambu-green/50 text-left transition-colors flex items-center justify-between group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-bambu-dark-tertiary text-bambu-green group-hover:scale-105 transition-transform">
                  <FileText className="w-4 h-4" />
                </div>
                <div>
                  <div className="text-sm font-medium text-white">
                    {t('system.logs', 'Server-Protokolle')}
                  </div>
                  <div className="text-xs text-bambu-gray">
                    {t('system.logsHint', 'Live-Logs & Debug-Meldungen')}
                  </div>
                </div>
              </div>
            </button>

            {/* Connection Diagnostics */}
            <button
              onClick={() => {
                if (printers.length > 0) {
                  setDiagnosticPrinter(printers[0]);
                } else {
                  showToast(t('printers.noPrinters', 'Kein Drucker konfiguriert'), 'info');
                }
              }}
              className="p-3 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary hover:border-bambu-green/50 text-left transition-colors flex items-center justify-between group"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-bambu-dark-tertiary text-blue-400 group-hover:scale-105 transition-transform">
                  <Stethoscope className="w-4 h-4" />
                </div>
                <div>
                  <div className="text-sm font-medium text-white">
                    {t('system.diagnostics', 'Verbindungsdiagnose')}
                  </div>
                  <div className="text-xs text-bambu-gray">
                    {t('system.diagnosticsHint', 'MQTT & Netzwerk-Check')}
                  </div>
                </div>
              </div>
            </button>

            {/* Support Bundle */}
            <button
              onClick={handleDownloadBundle}
              disabled={downloadingBundle}
              className="p-3 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary hover:border-bambu-green/50 text-left transition-colors flex items-center justify-between group disabled:opacity-50"
            >
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-bambu-dark-tertiary text-purple-400 group-hover:scale-105 transition-transform">
                  {downloadingBundle ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                </div>
                <div>
                  <div className="text-sm font-medium text-white">
                    {t('system.supportBundle', 'Support-Paket')}
                  </div>
                  <div className="text-xs text-bambu-gray">
                    {t('system.supportBundleHint', 'Diagnosedatei exportieren')}
                  </div>
                </div>
              </div>
            </button>
          </div>
        </CardContent>
      </Card>

      {/* System Health Panel */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <h3 className="text-base font-semibold text-white flex items-center gap-2">
              <HeartPulse className="w-5 h-5 text-bambu-green" />
              <span>{t('systemHealth.sectionTitle', 'Systemgesundheit & Status')}</span>
            </h3>
            {systemHealth && (
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  systemHealth.healthy
                    ? 'bg-green-500/20 text-green-400'
                    : 'bg-yellow-500/20 text-yellow-400'
                }`}
              >
                {systemHealth.healthy
                  ? t('systemHealth.healthy', 'Alles betriebsbereit')
                  : t('systemHealth.degraded', 'Warnungen vorhanden')}
              </span>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {systemHealth ? (
            <SystemHealthPanel result={systemHealth} />
          ) : (
            <div className="flex items-center justify-center p-8 text-bambu-gray">
              <Loader2 className="w-6 h-6 animate-spin mr-2" />
              <span>{t('common.loading', 'Laden...')}</span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Log Viewer Modal */}
      {showLogs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden shadow-2xl">
            <div className="p-4 border-b border-bambu-dark-tertiary flex items-center justify-between">
              <div className="flex items-center gap-2 text-white font-semibold">
                <FileText className="w-5 h-5 text-bambu-green" />
                <span>{t('system.serverLogs', 'Server-Protokolle')}</span>
              </div>
              <Button variant="secondary" size="sm" onClick={() => setShowLogs(false)}>
                {t('common.close', 'Schließen')}
              </Button>
            </div>
            <div className="p-4 flex-1 overflow-auto">
              <LogViewer />
            </div>
          </div>
        </div>
      )}

      {/* Connection Diagnostic Modal */}
      {diagnosticPrinter && (
        <ConnectionDiagnosticModal
          printer={diagnosticPrinter}
          onClose={() => setDiagnosticPrinter(null)}
        />
      )}
    </div>
  );
}

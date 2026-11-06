import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Check, ChevronDown, ChevronUp, HeartPulse } from 'lucide-react';

import { api } from '../api/client';
import { Card, CardContent } from './Card';
import { Button } from './Button';

function formatGb(bytes: number): string {
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return days > 0 ? `${days} d ${hours} h` : `${hours} h`;
}

/**
 * Zustand des Rechners (vor allem für den Raspberry Pi): Temperatur, Spannung, Speicher, Sicherungen,
 * Absturz-Diagnose und Hinweise.
 * Ist nichts davon messbar (zum Beispiel unter Windows), erscheint die Karte nicht.
 */
export function PiHealthCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [showLogs, setShowLogs] = useState(false);

  const { data } = useQuery({
    queryKey: ['piHealth'],
    queryFn: () => api.getPiHealth(),
    refetchInterval: 60000,
  });

  const dismissMutation = useMutation({
    mutationFn: () => api.dismissCrashReport(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['piHealth'] });
    },
  });

  if (!data) return null;
  const measurable = data.cpu_temp_c !== null || data.storage !== null || data.memory !== null || data.disk !== null;
  const hasCrash = Boolean(data.crash_report && !data.crash_report.dismissed);
  if (!measurable && data.warnings.length === 0 && !hasCrash) return null;

  const storageLabel = data.storage ? t(`piHealth.storage.${data.storage.kind}`) : '';
  const usedPercent = data.disk ? Math.round(((data.disk.total - data.disk.free) / data.disk.total) * 100) : null;

  const rows: [string, string][] = [];
  if (data.cpu_temp_c !== null) rows.push([t('piHealth.temperature'), `${data.cpu_temp_c} °C`]);
  if (data.throttled) {
    rows.push([t('piHealth.power'), data.throttled.flags.length === 0 ? t('piHealth.powerOk') : t('piHealth.powerProblem')]);
  }
  if (data.disk) {
    rows.push([t('piHealth.disk'), `${formatGb(data.disk.free)} ${t('piHealth.free')} (${usedPercent}%)`]);
  }
  if (data.storage) rows.push([t('piHealth.storageLabel'), `${storageLabel} (${data.storage.device})`]);
  if (data.memory) {
    rows.push([t('piHealth.memory'), `${formatGb(data.memory.available)} ${t('piHealth.free')} / ${formatGb(data.memory.total)}`]);
  }
  if (data.uptime_seconds !== null) rows.push([t('piHealth.uptime'), formatUptime(data.uptime_seconds)]);
  rows.push([
    t('piHealth.backup'),
    data.backup ? t('piHealth.backupAge', { days: data.backup.age_days }) : t('piHealth.backupNone'),
  ]);
  if (data.external_backup) {
    rows.push([t('piHealth.externalBackup'), data.external_backup.ok ? t('piHealth.ok') : t('piHealth.failed')]);
  }

  const crash = data.crash_report;

  return (
    <Card>
      <CardContent className="space-y-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HeartPulse className="w-5 h-5 text-bambu-green" />
          {t('piHealth.title')}
        </h2>

        {/* Prominenter Absturzbericht nach unsauberem Neustart / Crash */}
        {crash && !crash.dismissed && (
          <div className="bg-red-500/15 border border-red-500/40 rounded-xl p-3.5 space-y-2.5 text-xs text-red-200">
            <div className="flex items-start justify-between gap-2">
              <div className="flex items-center gap-2 font-semibold text-red-100 text-sm">
                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                <span>{crash.title}</span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => dismissMutation.mutate()}
                disabled={dismissMutation.isPending}
                className="shrink-0 text-xs py-1 px-2.5 h-auto bg-red-950/60 hover:bg-red-900 border-red-500/30 text-red-100"
              >
                <Check className="w-3.5 h-3.5 mr-1" />
                Meldung schließen
              </Button>
            </div>

            <p className="text-red-200/90 leading-relaxed">{crash.explanation}</p>

            {crash.recommendations.length > 0 && (
              <div className="bg-black/25 rounded-lg p-2.5 space-y-1">
                <p className="font-semibold text-red-100">Empfohlene Maßnahmen:</p>
                <ul className="list-disc list-inside space-y-0.5 text-red-200/90">
                  {crash.recommendations.map((rec, i) => (
                    <li key={i}>{rec}</li>
                  ))}
                </ul>
              </div>
            )}

            {crash.recent_logs && crash.recent_logs.length > 0 && (
              <div>
                <button
                  type="button"
                  onClick={() => setShowLogs(!showLogs)}
                  className="flex items-center gap-1 text-red-300 hover:text-red-100 underline text-[11px]"
                >
                  {showLogs ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  {showLogs ? 'Letzte Boot-Logs ausblenden' : 'Letzte Log-Zeilen vor dem Absturz anzeigen'}
                </button>
                {showLogs && (
                  <pre className="mt-1.5 p-2 bg-black/50 rounded text-[10px] font-mono overflow-x-auto text-gray-300 max-h-36">
                    {crash.recent_logs.join('\n')}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}

        {data.warnings.length === 0 && !hasCrash ? (
          <p className="text-xs text-bambu-green">{t('piHealth.allGood')}</p>
        ) : (
          <ul className="space-y-1" data-testid="pi-health-warnings">
            {data.warnings
              .filter((w) => w.code !== 'system_crashed' || !hasCrash)
              .map((warning) => (
                <li
                  key={warning.code}
                  className={`text-xs ${warning.level === 'crit' ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}`}
                >
                  {t(`piHealth.warn.${warning.code}`, { ...warning.params, defaultValue: warning.text })}
                </li>
              ))}
          </ul>
        )}

        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-3">
              <dt className="text-bambu-gray">{label}</dt>
              <dd className="text-white text-right">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

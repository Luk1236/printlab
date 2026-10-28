import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { HeartPulse } from 'lucide-react';

import { api } from '../api/client';
import { Card, CardContent } from './Card';

function formatGb(bytes: number): string {
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  return days > 0 ? `${days} d ${hours} h` : `${hours} h`;
}

/**
 * Zustand des Rechners (vor allem für den Raspberry Pi): Temperatur, Spannung, Speicher, Sicherungen und Hinweise.
 * Ist nichts davon messbar (zum Beispiel unter Windows), erscheint die Karte nicht.
 */
export function PiHealthCard() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ['piHealth'],
    queryFn: () => api.getPiHealth(),
    refetchInterval: 60000,
  });

  if (!data) return null;
  const measurable = data.cpu_temp_c !== null || data.storage !== null || data.memory !== null || data.disk !== null;
  if (!measurable && data.warnings.length === 0) return null;

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

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HeartPulse className="w-5 h-5 text-bambu-green" />
          {t('piHealth.title')}
        </h2>
        {data.warnings.length === 0 ? (
          <p className="text-xs text-bambu-green">{t('piHealth.allGood')}</p>
        ) : (
          <ul className="space-y-1" data-testid="pi-health-warnings">
            {data.warnings.map((warning) => (
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

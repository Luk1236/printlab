import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Database, ShieldCheck, Minimize2 } from 'lucide-react';

import { api } from '../api/client';
import type { DatabaseMaintenanceResult, DatabaseStatus } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(1)} ${units[unit]}`;
}

/**
 * Datenbank prüfen und komprimieren: SQLite gibt den Platz gelöschter Archive nicht von selbst zurück, und eine
 * beschädigte Seite fällt sonst erst beim nächsten Schreibvorgang auf. Beides läuft auf der lokalen Datenbank.
 */
export function DatabaseMaintenanceCard({ canControl }: { canControl: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [result, setResult] = useState<DatabaseMaintenanceResult | null>(null);

  const { data: status } = useQuery<DatabaseStatus>({
    queryKey: ['databaseStatus'],
    queryFn: api.getDatabaseStatus,
    retry: false,
  });

  const run = useMutation({
    mutationFn: (action: 'check' | 'vacuum') => api.runDatabaseMaintenance(action),
    onSuccess: (data) => {
      setResult(data);
      if (data.action === 'check') {
        showToast(data.ok ? t('databaseMaintenance.ok') : t('databaseMaintenance.problem'), data.ok ? 'success' : 'error');
      } else {
        showToast(t('databaseMaintenance.freed', { size: formatBytes(data.saved_bytes) }), 'success');
      }
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const supported = status?.supported !== false;
  const busy = run.isPending;

  return (
    <Card>
      <CardContent className="space-y-3" data-testid="database-maintenance-card">
        <div className="flex items-center gap-2">
          <Database className="w-5 h-5 text-bambu-green" />
          <h2 className="text-lg font-semibold text-white">{t('databaseMaintenance.title')}</h2>
        </div>
        <p className="text-sm text-bambu-gray">{t('databaseMaintenance.description')}</p>
        <p className="text-xs text-bambu-gray" data-testid="database-size">
          {t('databaseMaintenance.size', {
            size: status?.size_bytes != null ? formatBytes(status.size_bytes) : '—',
          })}
        </p>

        {!supported ? (
          <p className="text-xs text-bambu-gray">{t('databaseMaintenance.unsupported')}</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              data-testid="database-check"
              disabled={!canControl || busy}
              onClick={() => run.mutate('check')}
            >
              <ShieldCheck className="w-4 h-4" />
              {busy ? t('databaseMaintenance.busy') : t('databaseMaintenance.check')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              data-testid="database-vacuum"
              disabled={!canControl || busy}
              onClick={() => run.mutate('vacuum')}
            >
              <Minimize2 className="w-4 h-4" />
              {busy ? t('databaseMaintenance.busy') : t('databaseMaintenance.vacuum')}
            </Button>
          </div>
        )}

        {result && (
          <p className={`text-xs ${result.ok ? 'text-bambu-green' : 'text-red-700 dark:text-red-400'}`} role="status">
            {result.action === 'check'
              ? result.ok
                ? t('databaseMaintenance.ok')
                : t('databaseMaintenance.problem')
              : t('databaseMaintenance.freed', { size: formatBytes(result.saved_bytes) })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

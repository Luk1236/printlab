import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Loader2, MinusCircle, ShieldCheck, XCircle } from 'lucide-react';

import { api } from '../api/client';
import type { SelfTestResult } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

const ICONS = {
  ok: <CheckCircle2 className="w-4 h-4 shrink-0 text-bambu-green" aria-hidden="true" />,
  warn: <AlertTriangle className="w-4 h-4 shrink-0 text-amber-700 dark:text-amber-400" aria-hidden="true" />,
  fail: <XCircle className="w-4 h-4 shrink-0 text-red-700 dark:text-red-400" aria-hidden="true" />,
  skip: <MinusCircle className="w-4 h-4 shrink-0 text-bambu-gray" aria-hidden="true" />,
} as const;

/**
 * Systemprüfung: prüft in einem Durchlauf, ob Datenbank, Planer, Überwachung, Drucker, Prognose, Meldekanäle, Sicherungen,
 * Gerätezustand, Anmeldung, Update-Schutz und Assistent wirklich laufen. Mit zwei bewussten Proben: einer Testmeldung über
 * deine Kanäle und einer Probefrage an das Modell. Läuft nur auf Knopfdruck.
 */
export function SelfTestCard({ canRun }: { canRun: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const run = useMutation({
    mutationFn: () => api.runSelfTest(),
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const data = run.data;

  return (
    <Card>
      <CardContent className="space-y-3" data-testid="selftest-card">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-bambu-green" />
            {t('selfTest.title')}
          </h2>
          <Button size="sm" disabled={!canRun || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            {run.isPending ? t('selfTest.running') : data ? t('selfTest.again') : t('selfTest.run')}
          </Button>
        </div>
        <p className="text-xs text-bambu-gray">{t('selfTest.intro')}</p>
        {run.isPending && <p className="text-xs text-bambu-gray" role="status">{t('selfTest.wait')}</p>}
        {data && (
          <>
            <p
              className={`text-sm font-medium ${data.summary.fail > 0 ? 'text-red-700 dark:text-red-400' : data.summary.warn > 0 ? 'text-amber-700 dark:text-amber-400' : 'text-bambu-green'}`}
              data-testid="selftest-summary"
            >
              {t('selfTest.summary', { ok: data.summary.ok, warn: data.summary.warn, fail: data.summary.fail, skip: data.summary.skip })}
            </p>
            <ul className="space-y-2">
              {data.results.map((result: SelfTestResult) => (
                <li key={result.id} className="flex items-start gap-2 text-xs" data-testid={`selftest-${result.id}`}>
                  <span aria-label={t(`selfTest.status.${result.status}`)} role="img">
                    {ICONS[result.status]}
                  </span>
                  <div>
                    <p className="text-white">{result.title}</p>
                    <p className="text-bambu-gray-light">{result.detail}</p>
                    {result.fix && result.status !== 'ok' && <p className="text-bambu-gray">{result.fix}</p>}
                  </div>
                </li>
              ))}
            </ul>
            <p className="text-[11px] text-bambu-gray">{t('selfTest.checkedAt', { time: new Date(data.checked_at).toLocaleTimeString() })}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

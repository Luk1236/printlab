import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery } from '@tanstack/react-query';
import { AlertTriangle, RotateCcw, Undo2 } from 'lucide-react';

import { api } from '../api/client';
import type { FactoryResetArchive, FactoryResetPreview, FactoryResetResult } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

const inputClass =
  'mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm';

/**
 * Werkseinstellungen: setzt PrintLab auf den Auslieferungszustand zurück — Drucker, Warteschlange, Archiv,
 * Bibliothek, Material und Einstellungen. Der Server sichert vorher Datenbank und Konfiguration und verschiebt die
 * Daten in einen Reset-Ordner; gelöscht wird nichts. Deshalb steht hier zuerst eine Erklärung und erst nach der
 * getippten Bestätigung der eigentliche Knopf.
 *
 * Darunter stehen vorhandene Reset-Ordner: Ein Zurücksetzen lässt sich damit zurückholen; der aktuelle Stand wandert
 * dabei nach ``before-restore-…``, geht also ebenfalls nicht verloren.
 */
export function FactoryResetCard({ canControl }: { canControl: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [armed, setArmed] = useState(false);
  const [confirm, setConfirm] = useState('');
  const [result, setResult] = useState<FactoryResetResult | null>(null);
  const [restoreTarget, setRestoreTarget] = useState<string | null>(null);
  const [restoreConfirm, setRestoreConfirm] = useState('');

  const { data: preview } = useQuery<FactoryResetPreview>({
    queryKey: ['factoryResetPreview'],
    queryFn: api.getFactoryResetPreview,
    retry: false,
  });

  const { data: archiveData } = useQuery({
    queryKey: ['factoryResetArchives'],
    queryFn: api.getFactoryResetArchives,
    retry: false,
    enabled: preview?.supported === true,
  });
  const archives: FactoryResetArchive[] = archiveData?.archives ?? [];

  const reset = useMutation({
    mutationFn: () => api.runFactoryReset(confirm.trim()),
    onSuccess: (data) => {
      setResult(data);
      setArmed(false);
      setConfirm('');
      showToast(t('factoryReset.success'), 'success');
      // Der Reset ist vollständig; ein Neuladen holt die leere Einrichtung.
      window.setTimeout(() => window.location.reload(), 5000);
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const restore = useMutation({
    mutationFn: (name: string) => api.restoreFactoryReset(name, restoreConfirm.trim()),
    onSuccess: () => {
      setRestoreTarget(null);
      setRestoreConfirm('');
      showToast(t('factoryReset.restoreSuccess'), 'success');
      window.setTimeout(() => window.location.reload(), 5000);
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const supported = preview?.supported !== false;
  const ready = confirm.trim().toUpperCase() === 'ZURÜCKSETZEN';
  const restoreReady = restoreConfirm.trim().toUpperCase() === 'WIEDERHERSTELLEN';

  return (
    <Card>
      <CardContent className="space-y-3" data-testid="factory-reset-card">
        <div className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-red-600 dark:text-red-400" />
          <h2 className="text-lg font-semibold text-white">{t('factoryReset.title')}</h2>
        </div>

        <p className="text-sm text-bambu-gray">{t('factoryReset.description')}</p>
        <p className="text-xs text-bambu-gray">{t('factoryReset.keeps')}</p>

        {!supported && <p className="text-xs text-red-700 dark:text-red-400">{t('factoryReset.unavailable')}</p>}

        {result ? (
          <div className="space-y-2" role="status">
            <p className="text-sm text-bambu-green">{result.message}</p>
            <p className="text-xs text-bambu-gray">{t('factoryReset.restartHint')}</p>
            <Button size="sm" onClick={() => window.location.reload()}>
              {t('factoryReset.reload')}
            </Button>
          </div>
        ) : armed ? (
          <div className="space-y-2">
            <label className="block text-xs text-bambu-gray" htmlFor="factory-reset-confirm">
              {t('factoryReset.confirmLabel')}
            </label>
            <input
              id="factory-reset-confirm"
              data-testid="factory-reset-confirm"
              className={inputClass}
              value={confirm}
              onChange={(event) => setConfirm(event.target.value)}
              placeholder={t('factoryReset.confirmPlaceholder')}
              autoComplete="off"
              disabled={reset.isPending}
            />
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                variant="danger"
                data-testid="factory-reset-run"
                disabled={!ready || !canControl || reset.isPending}
                onClick={() => reset.mutate()}
              >
                <RotateCcw className="w-4 h-4" />
                {reset.isPending ? t('factoryReset.running') : t('factoryReset.submit')}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={reset.isPending}
                onClick={() => {
                  setArmed(false);
                  setConfirm('');
                }}
              >
                {t('factoryReset.cancel')}
              </Button>
            </div>
          </div>
        ) : (
          <Button
            size="sm"
            variant="secondary"
            data-testid="factory-reset-arm"
            disabled={!supported || !canControl}
            onClick={() => setArmed(true)}
          >
            <RotateCcw className="w-4 h-4" />
            {t('factoryReset.openButton')}
          </Button>
        )}

        {archives.length > 0 && (
          <div className="space-y-2 border-t border-bambu-dark-tertiary pt-3">
            <div className="flex items-center gap-2">
              <Undo2 className="w-4 h-4 text-bambu-green" />
              <h3 className="text-sm font-semibold text-white">{t('factoryReset.restoreTitle')}</h3>
            </div>
            <p className="text-xs text-bambu-gray">{t('factoryReset.restoreHint')}</p>
            <ul className="space-y-2">
              {archives.map((archive) => (
                <li key={archive.name} className="text-xs text-bambu-gray" data-testid="reset-archive">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="font-mono text-white">{archive.name}</span>
                      {archive.modified && (
                        <span className="ml-2">{new Date(archive.modified).toLocaleString()}</span>
                      )}
                    </span>
                    {restoreTarget === archive.name ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={restore.isPending}
                        onClick={() => {
                          setRestoreTarget(null);
                          setRestoreConfirm('');
                        }}
                      >
                        {t('factoryReset.cancel')}
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        variant="secondary"
                        data-testid={`restore-${archive.name}`}
                        disabled={!canControl || restore.isPending}
                        onClick={() => {
                          setRestoreTarget(archive.name);
                          setRestoreConfirm('');
                        }}
                      >
                        {t('factoryReset.restoreButton')}
                      </Button>
                    )}
                  </div>
                  {restoreTarget === archive.name && (
                    <div className="mt-2 space-y-2">
                      <label className="block text-xs text-bambu-gray" htmlFor="factory-restore-confirm">
                        {t('factoryReset.restoreConfirmLabel')}
                      </label>
                      <input
                        id="factory-restore-confirm"
                        data-testid="factory-restore-confirm"
                        className={inputClass}
                        value={restoreConfirm}
                        onChange={(event) => setRestoreConfirm(event.target.value)}
                        placeholder="WIEDERHERSTELLEN"
                        autoComplete="off"
                        disabled={restore.isPending}
                      />
                      <Button
                        size="sm"
                        variant="danger"
                        data-testid="factory-restore-run"
                        disabled={!restoreReady || !canControl || restore.isPending}
                        onClick={() => restore.mutate(archive.name)}
                      >
                        {restore.isPending ? t('factoryReset.running') : t('factoryReset.restoreButton')}
                      </Button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

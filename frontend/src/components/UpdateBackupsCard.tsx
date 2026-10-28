import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { UpdateBackup } from '../api/client';
import { Button } from './Button';
import { ConfirmModal } from './ConfirmModal';
import { useToast } from '../contexts/ToastContext';

function formatMb(bytes: number): string {
  return `${(bytes / 1e6).toFixed(1)} MB`;
}

/**
 * Sicherungen, die PrintLab vor jedem Update anlegt: Liste und Wiederherstellen. Das Wiederherstellen läuft beim
 * nächsten Start des Dienstes (bevor die App die Datenbank öffnet); der Stand davor wird ebenfalls gesichert.
 */
export function UpdateBackupsCard({ canRestore }: { canRestore: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<UpdateBackup | null>(null);

  const { data } = useQuery({ queryKey: ['updateBackups'], queryFn: () => api.getUpdateBackups() });

  const restore = useMutation({
    mutationFn: (name: string) => api.restoreUpdateBackup(name),
    onSuccess: () => {
      setSelected(null);
      showToast(t('settings.updateBackupRestoreQueued'));
      queryClient.invalidateQueries({ queryKey: ['updateBackups'] });
    },
    onError: (error: Error) => {
      setSelected(null);
      showToast(error.message, 'error');
    },
  });
  const dismiss = useMutation({
    mutationFn: () => api.dismissRestoreNotice(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['updateBackups'] }),
  });

  if (!data) return null;
  if (data.backups.length === 0 && !data.restored) return null;
  const allowed = canRestore && data.can_restore;

  return (
    <div className="mt-4 space-y-2 border-t border-bambu-dark-tertiary pt-3" data-testid="update-backups">
      <h3 className="text-sm font-medium text-white">{t('settings.updateBackupsTitle')}</h3>
      {data.restored && (
        <div className="p-2 bg-bambu-green/20 rounded text-sm text-bambu-green flex items-start justify-between gap-3">
          <span>{t('settings.updateBackupRestored', { name: data.restored.name })}</span>
          <button type="button" className="shrink-0 underline" onClick={() => dismiss.mutate()}>
            {t('settings.updateRolledBackDismiss')}
          </button>
        </div>
      )}
      {data.restore_pending && <p className="text-xs text-amber-700 dark:text-amber-400">{t('settings.updateBackupRestorePending', { name: data.restore_pending })}</p>}
      {!data.can_restore && <p className="text-xs text-bambu-gray">{t('settings.updateBackupGuardMissing')}</p>}
      <ul className="space-y-1">
        {data.backups.map((backup) => (
          <li key={backup.name} className="flex items-center gap-2 text-xs">
            <span className="text-white font-mono">{backup.name}</span>
            <span className="text-bambu-gray">{formatMb(backup.size_bytes)}</span>
            <span className="text-bambu-gray truncate">{backup.files.join(', ')}</span>
            <Button
              size="sm"
              variant="secondary"
              className="ml-auto"
              disabled={!allowed || restore.isPending || Boolean(data.restore_pending)}
              onClick={() => setSelected(backup)}
              aria-label={`${t('settings.updateBackupRestore')} ${backup.name}`}
            >
              {t('settings.updateBackupRestore')}
            </Button>
          </li>
        ))}
      </ul>
      {selected && (
        <ConfirmModal
          title={t('settings.updateBackupRestoreConfirmTitle')}
          message={t('settings.updateBackupRestoreConfirmMessage', { name: selected.name })}
          confirmText={t('settings.updateBackupRestore')}
          cancelText={t('common.cancel')}
          variant="warning"
          isLoading={restore.isPending}
          onCancel={() => setSelected(null)}
          onConfirm={() => restore.mutate(selected.name)}
        />
      )}
    </div>
  );
}

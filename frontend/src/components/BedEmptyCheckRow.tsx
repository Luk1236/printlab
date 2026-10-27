import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Camera } from 'lucide-react';

import { api } from '../api/client';
import type { BedEmptyCheckStatus } from '../api/client';
import { Button } from './Button';
import { useToast } from '../contexts/ToastContext';

/**
 * Leerbett-Prüfung: beim Druckstart warnen, falls die Kamera Material auf der
 * Platte sieht (Referenz vorher aufnehmen; nötig ist eine Einmessung).
 */
export function BedEmptyCheckRow({ printerId, canControl }: { printerId: number; canControl: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const { data: check } = useQuery<BedEmptyCheckStatus>({
    queryKey: ['bedEmptyCheck', printerId],
    queryFn: () => api.getBedEmptyCheck(printerId),
    enabled: printerId > 0,
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['bedEmptyCheck', printerId] });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => api.setBedEmptyCheck(printerId, { enabled, threshold: check?.threshold ?? 8 }),
    onSuccess: () => invalidate(),
    onError: (error: Error) => showToast(error.message),
  });
  const referenceMutation = useMutation({
    mutationFn: () => api.captureBedReference(printerId),
    onSuccess: () => {
      showToast(t('maintenance.programs.bedReferenceSaved'));
      invalidate();
    },
    onError: (error: Error) => showToast(error.message),
  });

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="flex items-center gap-2 text-xs text-bambu-gray">
        <input
          type="checkbox"
          checked={Boolean(check?.enabled)}
          onChange={(event) => toggleMutation.mutate(event.target.checked)}
          disabled={!canControl || toggleMutation.isPending}
        />
        {t('maintenance.programs.bedEmptyCheck')}
      </label>
      {check?.enabled && !check.has_reference && (
        <span className="text-xs text-amber-600 dark:text-amber-400">
          {t('maintenance.programs.bedNeedReference')}
        </span>
      )}
      <Button
        size="sm"
        variant="secondary"
        className="whitespace-nowrap"
        disabled={!canControl || referenceMutation.isPending}
        onClick={() => referenceMutation.mutate()}
        title={t('maintenance.programs.bedReferenceHint')}
      >
        <Camera className="w-4 h-4" />
        {t('maintenance.programs.bedCaptureReference')}
      </Button>
      {check?.has_reference && (
        <span className="text-xs text-bambu-green">{t('maintenance.programs.bedReferenceSaved')}</span>
      )}
    </div>
  );
}
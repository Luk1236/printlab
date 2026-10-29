import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Camera, Info, RefreshCw, Trash2 } from 'lucide-react';

import { api, withMediaToken } from '../api/client';
import { Card, CardContent, CardHeader } from './Card';
import { ConfirmModal } from './ConfirmModal';
import { useToast } from '../contexts/ToastContext';

/**
 * Fehlerbild-Sammlung: zeigt die Bilder, die bei fehlgeschlagenen Prüfungen
 * (Platte nicht frei, Erste-Schicht, Spaghetti, Bauteil-Wächter) dauerhaft
 * gespeichert werden — Rohmaterial für eine spätere KI-Fehlererkennung.
 */
export function FailureImagesCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [toDelete, setToDelete] = useState<string | null>(null);

  const { data: images, refetch } = useQuery({
    queryKey: ['failure-images'],
    queryFn: api.listFailureImages,
  });

  const remove = useMutation({
    mutationFn: (name: string) => api.deleteFailureImage(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['failure-images'] });
      setToDelete(null);
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const imageUrl = (name: string) => withMediaToken(`/api/v1/failure-images/${encodeURIComponent(name)}`);

  return (
    <Card id="card-fd-images">
      <CardHeader>
        <div className="flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
            <Camera className="w-5 h-5" />
            {t('failureImages.title')}
          </h2>
          <button onClick={() => refetch()} className="text-xs text-bambu-gray hover:text-white">
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="mb-3 flex items-center gap-2 text-bambu-gray text-xs">
          <Info className="w-4 h-4 shrink-0" />
          <span>{t('failureImages.hint')}</span>
        </div>
        {!images || images.length === 0 ? (
          <div className="flex items-center gap-2 text-bambu-gray text-sm">
            <Info className="w-4 h-4" />
            <span>{t('failureImages.empty')}</span>
          </div>
        ) : (
          <div className="grid grid-cols-3 gap-2 md:grid-cols-6">
            {images.map((image) => (
              <div key={image.name} className="group relative">
                <a href={imageUrl(image.name)} target="_blank" rel="noreferrer">
                  <img
                    src={imageUrl(image.name)}
                    alt={image.event}
                    className="aspect-video w-full rounded border border-bambu-dark-tertiary object-cover"
                  />
                </a>
                <div className="mt-1 flex items-center justify-between gap-1">
                  <span className="truncate text-[10px] text-bambu-gray" title={image.timestamp}>
                    {new Date(image.timestamp).toLocaleString()}
                  </span>
                  <button
                    onClick={() => setToDelete(image.name)}
                    className="shrink-0 text-bambu-gray opacity-0 transition group-hover:opacity-100 hover:text-red-400"
                    title={t('common.delete')}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
      {toDelete && (
        <ConfirmModal
          title={t('failureImages.confirmTitle')}
          message={t('failureImages.confirmText')}
          confirmText={t('common.delete')}
          cancelText={t('common.cancel')}
          variant="danger"
          isLoading={remove.isPending}
          onCancel={() => setToDelete(null)}
          onConfirm={() => remove.mutate(toDelete)}
        />
      )}
    </Card>
  );
}
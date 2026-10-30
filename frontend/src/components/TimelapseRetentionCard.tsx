import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Film } from 'lucide-react';

import { api } from '../api/client';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

/**
 * Zeitraffer-Aufbewahrung: Schichtbilder nach dem Druck behalten, damit sich daraus jederzeit ein MP4 rendern
 * lässt (im Archiv unter Zeitraffer). Kostet Platz — deshalb standardmäßig aus und mit Obergrenzen.
 */
export function TimelapseRetentionCard({ canEdit }: { canEdit: boolean }) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const { data: config } = useQuery({ queryKey: ['timelapseExportConfig'], queryFn: api.getTimelapseExportConfig });

  const save = useMutation({
    mutationFn: (update: Record<string, unknown>) => api.saveTimelapseExportConfig(update),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timelapseExportConfig'] }),
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  if (!config) return null;

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Film className="w-5 h-5 text-bambu-green" />
          Zeitraffer-Aufbewahrung
        </h2>
        <p className="text-xs text-bambu-gray">
          Schichtbilder nach dem Druck behalten. Aus ihnen lässt sich im Archiv jederzeit ein MP4 rendern — auch wenn
          das automatische Stechen fehlschlug oder ein anderes Tempo gewünscht ist. Die Bilder kosten Platz (je Druck
          leicht einige hundert MB); sie gelten ab dem nächsten Druck.
        </p>
        <label className="flex items-center gap-2 text-sm text-white">
          <input
            type="checkbox"
            checked={config.keep_frames}
            disabled={!canEdit}
            onChange={(event) => save.mutate({ keep_frames: event.target.checked })}
          />
          Schichtbilder aufbewahren
        </label>
        <div className="grid grid-cols-2 gap-2 max-w-md">
          <label className="text-xs text-bambu-gray">
            Aufbewahren (Tage)
            <input
              type="number"
              min={1}
              max={365}
              defaultValue={config.retention_days}
              disabled={!canEdit}
              onBlur={(event) => {
                const value = Number(event.target.value);
                if (value >= 1 && value <= 365) save.mutate({ retention_days: value });
              }}
              className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
            />
          </label>
          <label className="text-xs text-bambu-gray">
            Sitzungen je Archiv
            <input
              type="number"
              min={1}
              max={20}
              defaultValue={config.max_kept_per_archive}
              disabled={!canEdit}
              onBlur={(event) => {
                const value = Number(event.target.value);
                if (value >= 1 && value <= 20) save.mutate({ max_kept_per_archive: value });
              }}
              className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
            />
          </label>
          <label className="text-xs text-bambu-gray">
            Videos je Archiv
            <input
              type="number"
              min={1}
              max={20}
              defaultValue={config.max_exports_per_archive}
              disabled={!canEdit}
              onBlur={(event) => {
                const value = Number(event.target.value);
                if (value >= 1 && value <= 20) save.mutate({ max_exports_per_archive: value });
              }}
              className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
            />
          </label>
          <label className="text-xs text-bambu-gray">
            Standard-Bildrate
            <input
              type="number"
              min={1}
              max={60}
              defaultValue={config.fps}
              disabled={!canEdit}
              onBlur={(event) => {
                const value = Number(event.target.value);
                if (value >= 1 && value <= 60) save.mutate({ fps: value });
              }}
              className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
            />
          </label>
        </div>
      </CardContent>
    </Card>
  );
}

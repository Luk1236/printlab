import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';

import { api } from '../api/client';
import type { AutoRequeueConfig } from '../api/forkApi';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

/**
 * Automatische Umverteilung: scheitert ein Auftrag, wird er einmal auf ein anderes Gerät desselben Modells
 * eingereiht. Nur echte Fehlschläge, nie ein Abbruch durch den Benutzer; jede Umverteilung steht im Protokoll.
 */
export function AutoRequeueCard({ canEdit }: { canEdit: boolean }) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const { data: config } = useQuery<AutoRequeueConfig>({ queryKey: ['autoRequeue'], queryFn: api.getAutoRequeue });
  const { data: log } = useQuery({
    queryKey: ['autoRequeueLog'],
    queryFn: () => api.getAutoRequeueLog(10),
  });

  const save = useMutation({
    mutationFn: (update: Partial<AutoRequeueConfig>) => api.saveAutoRequeue(update),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['autoRequeue'] }),
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  if (!config) return null;

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <RefreshCw className="w-5 h-5 text-bambu-green" />
          Automatische Umverteilung
        </h2>
        <p className="text-xs text-bambu-gray">
          Scheitert ein Druck (nicht: vom Benutzer abgebrochen), wird der Auftrag einmal als neuer Eintrag auf ein
          anderes Gerät desselben Modells eingereiht. Der Fehlschlag bleibt mit seiner Meldung sichtbar.
        </p>

        <label className="flex items-center gap-2 text-sm text-white">
          <input
            type="checkbox"
            checked={config.enabled}
            disabled={!canEdit}
            onChange={(event) => save.mutate({ enabled: event.target.checked })}
          />
          Umverteilung einschalten
        </label>
        <label className="flex items-center gap-2 text-sm text-white">
          <input
            type="checkbox"
            checked={config.require_sibling}
            disabled={!canEdit}
            onChange={(event) => save.mutate({ require_sibling: event.target.checked })}
          />
          Nur wenn ein zweites Gerät desselben Modells vorhanden ist
        </label>
        <label className="text-xs text-bambu-gray block max-w-40">
          Wiederholungen je Auftrag
          <select
            value={config.max_retries}
            disabled={!canEdit}
            onChange={(event) => save.mutate({ max_retries: Number(event.target.value) })}
            className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
          >
            {[0, 1, 2, 3].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>

        {log && log.entries.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs text-bambu-gray">Zuletzt umverteilt</p>
            <ul className="space-y-1 text-xs text-bambu-gray">
              {log.entries.map((entry) => (
                <li key={`${entry.root_id}-${entry.retry_id}`} className="rounded border border-bambu-dark-tertiary px-2 py-1">
                  Auftrag {entry.root_id} → {entry.retry_id} · Ziel {entry.target || '—'}
                  {entry.reason ? ` · ${entry.reason}` : ''} · {entry.at.slice(0, 16).replace('T', ' ')}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

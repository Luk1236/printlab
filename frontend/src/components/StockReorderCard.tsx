import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShoppingCart } from 'lucide-react';

import { api } from '../api/client';
import type { ReorderProposal } from '../api/client';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

function fmtGrams(value: number): string {
  return `${Math.round(value).toLocaleString('de-DE')} g`;
}

function fmtCost(value: number | null): string {
  if (value === null) return '—';
  try {
    return new Intl.NumberFormat('de-DE', { style: 'currency', currency: 'EUR' }).format(value);
  } catch {
    return `${value.toFixed(2)} €`;
  }
}

/**
 * Nachbestellvorschlag: aus der Verbrauchsprognose (letzte Drucke, Bestand, Lieferzeit) wird, was jetzt
 * bestellt werden sollte — mit Menge in Rollen, günstigstem Lieferanten und geschätzten Kosten.
 * Das ist ein Vorschlag, keine Bestellung.
 */
export function StockReorderCard({ canEdit }: { canEdit: boolean }) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const { data, error } = useQuery({
    queryKey: ['reorderProposals'],
    queryFn: api.getReorderProposals,
    retry: false,
  });
  const { data: config } = useQuery({ queryKey: ['reorderConfig'], queryFn: api.getReorderConfig });

  const save = useMutation({
    mutationFn: (update: Record<string, unknown>) => api.saveReorderConfig(update),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['reorderConfig'] });
      queryClient.invalidateQueries({ queryKey: ['reorderProposals'] });
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const proposals: ReorderProposal[] = data?.proposals ?? [];

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <ShoppingCart className="w-5 h-5 text-bambu-green" />
          Nachbestellvorschlag
        </h2>
        <p className="text-xs text-bambu-gray">
          Aus Verbrauch, Bestand und Lieferzeit: was jetzt bestellt werden sollte. Der Vorrat soll nach der Lieferung
          noch {config?.coverage_days ?? 14} Tage reichen. Das ist ein Vorschlag — bestellt wird beim Lieferanten.
        </p>

        {config && (
          <label className="text-xs text-bambu-gray block max-w-44">
            Zielbestand nach Lieferung (Tage)
            <input
              type="number"
              min={1}
              max={180}
              defaultValue={config.coverage_days}
              disabled={!canEdit}
              onBlur={(event) => {
                const value = Number(event.target.value);
                if (value >= 1 && value <= 180 && value !== config.coverage_days) save.mutate({ coverage_days: value });
              }}
              className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
            />
          </label>
        )}

        {error && <p className="text-xs text-amber-500">{error.message}</p>}
        {!error && proposals.length === 0 && (
          <p className="text-xs text-bambu-gray">Nichts zu bestellen — alle Materialien sind über dem Nachbestellpunkt.</p>
        )}

        {proposals.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-bambu-gray">
                  <th className="py-1 pr-2">Material</th>
                  <th className="py-1 pr-2 text-right">Vorrat</th>
                  <th className="py-1 pr-2 text-right">Reicht</th>
                  <th className="py-1 pr-2 text-right">Bestellen</th>
                  <th className="py-1 pr-2">Lieferant</th>
                  <th className="py-1 text-right">Kosten</th>
                </tr>
              </thead>
              <tbody className="text-white">
                {proposals.map((entry) => (
                  <tr key={`${entry.material}-${entry.subtype}-${entry.color_name}`} className="border-t border-bambu-dark-tertiary">
                    <td className="py-1 pr-2">
                      {[entry.material, entry.subtype, entry.brand, entry.color_name].filter(Boolean).join(' · ')}
                      {entry.stock_break ? <span className="ml-1 text-amber-500">(bricht)</span> : null}
                    </td>
                    <td className="py-1 pr-2 text-right">{fmtGrams(entry.remaining_g)}</td>
                    <td className="py-1 pr-2 text-right">{entry.days_remaining ?? '—'} T</td>
                    <td className="py-1 pr-2 text-right">
                      {entry.rolls} × {fmtGrams(entry.spool_size_g)}
                    </td>
                    <td className="py-1 pr-2">{entry.supplier ?? '—'}</td>
                    <td className="py-1 text-right">{fmtCost(entry.estimated_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-[11px] text-bambu-gray">
          Grundlage: {data?.mode === 'spoolman' ? 'Spoolman-Bestand' : 'eigene Rollenverwaltung'}
          {data ? ` · ${data.checked_skus} Materialien geprüft` : ''}. Preise stammen aus den gepflegten
          Lieferanten-Angeboten; ohne Preis bleibt die Kostenspalte leer.
        </p>
      </CardContent>
    </Card>
  );
}

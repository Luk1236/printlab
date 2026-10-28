import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { InventorySpool } from '../api/client';
import { ConfirmModal } from './ConfirmModal';
import { PresetSourceBadge } from './spool-form/PresetPicker';
import { buildFilamentOptions } from './spool-form/utils';
import { useToast } from '../contexts/ToastContext';
import { buildProposals } from '../utils/presetMatch';
import type { MatchKind } from '../utils/presetMatch';

const spoolLabel = (s: InventorySpool) =>
  [s.brand, s.material, s.subtype, s.color_name ? `(${s.color_name})` : ''].filter(Boolean).join(' ');

/**
 * Ordnet Spulen ohne Slicer-Profil automatisch das passende Filament-Profil zu (Bambu Cloud, Orca Cloud, lokal, eingebaut):
 * Vorschlagsliste zum Prüfen, dann gesammelt übernehmen. Treffer nach Marke, Material und Sorte; „generisch" ist nur ein
 * Notbehelf und standardmäßig nicht angehakt.
 */
export function SpoolPresetMatchModal({ spools, onClose }: { spools: InventorySpool[]; onClose: () => void }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [includeAssigned, setIncludeAssigned] = useState(false);
  const [overrides, setOverrides] = useState<Record<number, boolean>>({});

  const { data: cloudPresets = [], isLoading } = useQuery({
    queryKey: ['preset-match-cloud'],
    staleTime: 5 * 60 * 1000,
    queryFn: async () => {
      const out: Awaited<ReturnType<typeof api.getFilamentPresets>> = [];
      try {
        const status = await api.getCloudStatus();
        if (status.is_authenticated) out.push(...(await api.getFilamentPresets()));
      } catch {
        /* Bambu Cloud nicht erreichbar → keine Cloud-Profile */
      }
      try {
        const orca = await api.orcaCloudStatus();
        if (orca.connected) out.push(...((await api.orcaCloudListProfiles()).filament as unknown as typeof out));
      } catch {
        /* Orca Cloud nicht erreichbar */
      }
      return out;
    },
  });
  const { data: local } = useQuery({ queryKey: ['preset-match-local'], staleTime: 5 * 60 * 1000, queryFn: api.getLocalPresets });
  const { data: builtin = [] } = useQuery({ queryKey: ['builtin-filaments'], staleTime: 5 * 60 * 1000, queryFn: api.getBuiltinFilaments });
  const { data: printers = [] } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters });

  const options = useMemo(
    () => buildFilamentOptions(cloudPresets, new Set(), local?.filament ?? [], builtin),
    [cloudPresets, local, builtin],
  );
  const { matches, unmatched } = useMemo(
    () => buildProposals(spools, options, printers.map((p) => p.model ?? ''), includeAssigned),
    [spools, options, printers, includeAssigned],
  );
  const byId = useMemo(() => new Map(spools.map((s) => [s.id, s])), [spools]);
  const isChecked = (spoolId: number, kind: MatchKind) => overrides[spoolId] ?? kind !== 'generic';
  const chosen = matches.filter((m) => isChecked(m.spoolId, m.kind));

  const apply = useMutation({
    mutationFn: async () => {
      const groups = new Map<string, { name: string; ids: number[] }>();
      for (const m of chosen) {
        const group = groups.get(m.option.code) ?? { name: m.option.name, ids: [] };
        group.ids.push(m.spoolId);
        groups.set(m.option.code, group);
      }
      let updated = 0;
      for (const [code, group] of groups) {
        const result = await api.bulkUpdateSpools(group.ids, { slicer_filament: code, slicer_filament_name: group.name });
        updated += result.updated;
      }
      return updated;
    },
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ['inventory-spools'] });
      showToast(t('inventory.presetMatch.applied', { count: updated }));
      onClose();
    },
    onError: () => showToast(t('inventory.presetMatch.failed'), 'error'),
  });

  const onlyBuiltin = !isLoading && cloudPresets.length === 0 && (local?.filament ?? []).length === 0;

  return (
    <ConfirmModal
      title={t('inventory.presetMatch.title')}
      message={t('inventory.presetMatch.intro')}
      confirmText={t('inventory.presetMatch.apply', { count: chosen.length })}
      cardClassName="max-w-2xl"
      confirmDisabled={chosen.length === 0}
      isLoading={apply.isPending}
      onCancel={onClose}
      onConfirm={() => apply.mutate()}
    >
      <div className="space-y-3 text-sm" data-testid="preset-match">
        <label className="flex items-center gap-2 text-xs text-bambu-gray">
          <input type="checkbox" checked={includeAssigned} onChange={(event) => setIncludeAssigned(event.target.checked)} />
          {t('inventory.presetMatch.includeAssigned')}
        </label>
        {onlyBuiltin && <p className="text-xs text-amber-700 dark:text-amber-400">{t('inventory.presetMatch.noPresets')}</p>}
        {isLoading ? (
          <p className="text-bambu-gray">{t('inventory.presetMatch.loading')}</p>
        ) : matches.length === 0 ? (
          <p className="text-bambu-gray">{t('inventory.presetMatch.nothing')}</p>
        ) : (
          <ul className="space-y-1 max-h-72 overflow-y-auto">
            {matches.map((m) => {
              const spool = byId.get(m.spoolId);
              return (
                <li key={m.spoolId} className="flex flex-wrap items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={isChecked(m.spoolId, m.kind)}
                    aria-label={spool ? spoolLabel(spool) : String(m.spoolId)}
                    onChange={(event) => setOverrides((prev) => ({ ...prev, [m.spoolId]: event.target.checked }))}
                  />
                  <span className="text-white">{spool ? spoolLabel(spool) : `#${m.spoolId}`}</span>
                  <span className="text-bambu-gray">→</span>
                  <span className="text-bambu-gray-light">{m.option.name}</span>
                  <PresetSourceBadge source={m.option.source} />
                  <span className={m.kind === 'generic' ? 'text-amber-700 dark:text-amber-400' : 'text-bambu-green'}>
                    {t(`inventory.presetMatch.kind.${m.kind}`)}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {unmatched.length > 0 && !isLoading && (
          <p className="text-xs text-bambu-gray">{t('inventory.presetMatch.unmatched', { count: unmatched.length })}</p>
        )}
      </div>
    </ConfirmModal>
  );
}

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Boxes, ClipboardList, Save } from 'lucide-react';

import { api } from '../api/client';
import type { AuditEntry, HardwareConfig, HardwareSlot, Printer } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';
import { commandToDraft, draftToCommand } from '../utils/hardwareCommand';

const SLOT_STATUSES = ['ready', 'used', 'empty', 'occupied'] as const;

const STATUS_COLOR: Record<string, string> = {
  ready: 'bg-bambu-green/20 text-bambu-green border-bambu-green/40',
  used: 'bg-amber-500/20 text-amber-600 dark:text-amber-400 border-amber-500/40',
  empty: 'bg-bambu-dark-tertiary text-bambu-gray border-bambu-gray-dark',
  occupied: 'bg-blue-500/20 text-blue-500 border-blue-500/40',
};

/**
 * Hardware & Magazin: Fächer-Verwaltung, Befehls-Konfiguration und Aktionen-Protokoll.
 * Konfigurationen liegen auf dem Server (data/hardware.json, audit_log.jsonl);
 * alle Endpunkte erlauben Änderungen auch bei offline Druckern.
 */
export function HardwareAdminCard({ canControl }: { canControl: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [printerId, setPrinterId] = useState(0);
  const [drafts, setDrafts] = useState<Record<number, string>>({});

  const { data: printers = [] } = useQuery<Printer[]>({ queryKey: ['printers'], queryFn: api.getPrinters });
  useEffect(() => {
    if (!printers.some((p) => p.id === printerId)) setPrinterId(printers[0]?.id ?? 0);
  }, [printers, printerId]);

  const { data: hardware } = useQuery<HardwareStatus>({
    queryKey: ['hardwareAdmin', printerId],
    queryFn: () => api.getHardwareStatus(printerId),
    enabled: printerId > 0,
    refetchInterval: 5000,
  });

  const { data: configs } = useQuery<AuditEntry[]>({
    queryKey: ['hardwareAudit', printerId],
    queryFn: () => api.getHardwareAuditLog(printerId, 20),
    enabled: printerId > 0,
  });

  // Hardware-Konfiguration (Befehle + Modus) als freies Formular
  const [configDraft, setConfigDraft] = useState<ConfigDraft | null>(null);
  const { data: config } = useQuery({
    queryKey: ['hardwareConfig', printerId],
    queryFn: () => api.getHardwareConfig(printerId),
    enabled: printerId > 0 && canControl,
  });
  const buildDraft = (cfg: HardwareConfig): ConfigDraft => ({
    mode: cfg.mode,
    timeout_seconds: String(cfg.timeout_seconds ?? 15),
    door_open_command: commandToDraft(cfg.door_open_command),
    door_close_command: commandToDraft(cfg.door_close_command),
    door_status_command: commandToDraft(cfg.door_status_command),
    plate_change_command: commandToDraft(cfg.plate_change_command),
    emergency_stop_command: commandToDraft(cfg.emergency_stop_command),
  });

  const slotsSave = useMutation({
    mutationFn: (slots: HardwareSlot[]) => api.setMagazineSlots(printerId, slots),
    onSuccess: (data) => {
      showToast(data.message || t('common.success'));
      setDrafts({});
      queryClient.invalidateQueries({ queryKey: ['hardwareAdmin', printerId] });
      queryClient.invalidateQueries({ queryKey: ['hardwareStatus', printerId] });
      queryClient.invalidateQueries({ queryKey: ['hardwareAudit', printerId] });
    },
    onError: (error: Error) => showToast(error.message),
  });

  const configSave = useMutation({
    mutationFn: (draft: ConfigDraft) =>
      api.setHardwareConfig(printerId, {
        mode: draft.mode,
        timeout_seconds: Number(draft.timeout_seconds) || 15,
        door_open_command: draftToCommand(draft.door_open_command),
        door_close_command: draftToCommand(draft.door_close_command),
        door_status_command: draftToCommand(draft.door_status_command),
        plate_change_command: draftToCommand(draft.plate_change_command),
        emergency_stop_command: draftToCommand(draft.emergency_stop_command),
      }),
    onSuccess: (data) => {
      showToast(data.message || t('common.success'));
      setConfigDraft(null);
      queryClient.invalidateQueries({ queryKey: ['hardwareConfig', printerId] });
      queryClient.invalidateQueries({ queryKey: ['hardwareAdmin', printerId] });
      queryClient.invalidateQueries({ queryKey: ['hardwareAudit', printerId] });
    },
    onError: (error: Error) => showToast(error.message),
  });

  const cycleStatus = (slot: HardwareSlot) => {
    const next = SLOT_STATUSES[(SLOT_STATUSES.indexOf(slot.status) + 1) % SLOT_STATUSES.length];
    slotsSave.mutate([{ id: slot.id, status: next }]);
  };

  const saveSlotLabel = (id: number, fallback: string) => {
    const value = (drafts[id] ?? '').trim();
    slotsSave.mutate([{ id, label: value || fallback }]);
  };

  if (printers.length === 0) return null;

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Boxes className="w-5 h-5 text-bambu-green" />
            {t('hardwareAdmin.title')}
          </h2>
          <select
            value={printerId}
            onChange={(event) => {
              setConfigDraft(null);
              setPrinterId(Number(event.target.value));
            }}
            className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
            aria-label={t('hardwareAdmin.printer')}
          >
            {printers.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </div>

        {/* Magazin: 6 Fächer, Klick zykliert den Status */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {(hardware?.slots ?? []).map((slot) => (
            <div key={slot.id} className="border border-bambu-dark-tertiary rounded-lg p-2 space-y-1.5">
              <div className="flex items-center justify-between gap-1">
                <span className="text-xs text-bambu-gray">
                  {slot.type === 'supply' ? t('hardwareAdmin.supply') : t('hardwareAdmin.storage')} {slot.id}
                </span>
                <button
                  type="button"
                  disabled={!canControl || slotsSave.isPending}
                  onClick={() => cycleStatus(slot)}
                  className={`px-1.5 py-0.5 text-[11px] font-medium rounded border ${STATUS_COLOR[slot.status] ?? ''}`}
                  title={slot.status}
                >
                  {t(`hardwareAdmin.status_${slot.status}`)}
                </button>
              </div>
              <input
                value={drafts[slot.id] ?? slot.label ?? ''}
                onChange={(event) => setDrafts((d) => ({ ...d, [slot.id]: event.target.value }))}
                onBlur={() => saveSlotLabel(slot.id, slot.label ?? '')}
                disabled={!canControl || slotsSave.isPending}
                className="w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded px-2 py-1 text-sm text-white"
                aria-label={t('hardwareAdmin.slotLabel', { id: slot.id })}
              />
              {slot.print && <p className="text-[11px] text-bambu-gray truncate" title={slot.print}>{slot.print}</p>}
            </div>
          ))}
        </div>
        <p className="text-xs text-bambu-gray">{t('hardwareAdmin.statusHint')}</p>

        {/* Konfiguration (nur mit Kontrolle) */}
        {canControl && configDraft && (
          <div className="border border-bambu-dark-tertiary rounded-lg p-3 space-y-2">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              <label className="text-xs text-bambu-gray">
                {t('hardwareAdmin.mode')}
                <select
                  value={configDraft.mode}
                  onChange={(event) => setConfigDraft({ ...configDraft, mode: event.target.value })}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                >
                  <option value="simulated">{t('hardwareAdmin.modeSimulated')}</option>
                  <option value="command">{t('hardwareAdmin.modeCommand')}</option>
                </select>
              </label>
              <label className="text-xs text-bambu-gray">
                {t('hardwareAdmin.timeout')} (s)
                <input
                  type="number"
                  min={1}
                  value={configDraft.timeout_seconds}
                  onChange={(event) => setConfigDraft({ ...configDraft, timeout_seconds: event.target.value })}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                />
              </label>
            </div>
            {(
              [
                ['door_open_command', 'cmdDoorOpen'],
                ['door_close_command', 'cmdDoorClose'],
                ['door_status_command', 'cmdDoorStatus'],
                ['plate_change_command', 'cmdPlateChange'],
                ['emergency_stop_command', 'cmdEmergencyStop'],
              ] as const
            ).map(([field, key]) => (
              <label key={field} className="block text-xs text-bambu-gray">
                {t(`hardwareAdmin.${key}`)}
                <input
                  value={configDraft[field]}
                  onChange={(event) => setConfigDraft({ ...configDraft, [field]: event.target.value })}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-xs font-mono"
                  spellCheck={false}
                />
              </label>
            ))}
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfigDraft(null)}>{t('common.cancel')}</Button>
              <Button size="sm" disabled={configSave.isPending} onClick={() => configSave.mutate(configDraft)}>
                <Save className="w-4 h-4" />
                {t('common.save')}
              </Button>
            </div>
          </div>
        )}
        {canControl && config && !configDraft && (
          <Button size="sm" variant="secondary" onClick={() => setConfigDraft(buildDraft(config))}>
            {t('hardwareAdmin.editConfig')}
          </Button>
        )}

        {/* Protokoll */}
        <div className="border-t border-bambu-dark-tertiary pt-3">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2 mb-2">
            <ClipboardList className="w-4 h-4 text-bambu-green" />
            {t('hardwareAdmin.auditTitle')}
          </h3>
          {(configs?.length ?? 0) === 0 ? (
            <p className="text-xs text-bambu-gray">{t('hardwareAdmin.auditEmpty')}</p>
          ) : (
            <div className="space-y-1 max-h-60 overflow-y-auto">
              {(configs ?? []).map((entry, index) => (
                <div key={index} className="flex items-center gap-2 text-xs">
                  <span className={`inline-block w-2 h-2 rounded-full ${entry.ok ? 'bg-bambu-green' : 'bg-red-500'}`} />
                  <span className="text-bambu-gray whitespace-nowrap">
                    {new Date(entry.ts).toLocaleString()}
                  </span>
                  <span className="font-medium">{t(`hardwareAdmin.action_${entry.action}`, entry.action)}</span>
                  <span className="text-bambu-gray truncate" title={entry.message}>{entry.message}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <p className="text-xs text-bambu-gray">
          {t('hardwareAdmin.configHint')}
        </p>
      </CardContent>
    </Card>
  );
}

interface ConfigDraft {
  mode: string;
  timeout_seconds: string;
  door_open_command: string;
  door_close_command: string;
  door_status_command: string;
  plate_change_command: string;
  emergency_stop_command: string;
}
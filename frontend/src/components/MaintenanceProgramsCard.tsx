import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeftRight, Check, DoorClosed, DoorOpen, Download, Droplet, ListPlus, RefreshCw, Square, Wrench } from 'lucide-react';

import { api } from '../api/client';
import type {
  FirstLayerStatus,
  HardwareStatus,
  LayerAlertStatus,
  MaintenanceProgram,
  MaintenanceProgramStatus,
  PartWatcherStatus,
  PlateCalibrationStatus,
  Printer,
} from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { BedEmptyCheckRow, SpaghettiCheckRow } from './BedEmptyCheckRow';
import { useToast } from '../contexts/ToastContext';

interface MaintenanceProgramsCardProps {
  canControl: boolean;
}

export function MaintenanceProgramsCard({ canControl }: MaintenanceProgramsCardProps) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const { data: printers = [] } = useQuery<Printer[]>({
    queryKey: ['printers'],
    queryFn: api.getPrinters,
  });
  const [printerId, setPrinterId] = useState<number>(0);

  useEffect(() => {
    if (!printers.some((printer) => printer.id === printerId)) {
      setPrinterId(printers[0]?.id ?? 0);
    }
  }, [printers, printerId]);

  const printer = useMemo(
    () => printers.find((item) => item.id === printerId) ?? null,
    [printers, printerId]
  );
  const supported = (printer?.model ?? '').toUpperCase() === 'P2S';  const { data: status } = useQuery<MaintenanceProgramStatus>({
    queryKey: ['maintenanceProgram', printerId],
    queryFn: () => api.getMaintenanceProgramStatus(printerId),
    enabled: printerId > 0,
    refetchInterval: (query) => (query.state.data?.active ? 1500 : 5000),
  });

  const startMutation = useMutation({
    mutationFn: (program: MaintenanceProgram) => api.startMaintenanceProgram(printerId, program, undefined, true),
    onSuccess: (data) => {
      showToast(data.message);
      queryClient.invalidateQueries({ queryKey: ['maintenanceProgram', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const startWithConfirm = (program: MaintenanceProgram) => {
    if (!window.confirm(t('maintenance.programs.confirmPlate'))) return;
    startMutation.mutate(program);
  };

  const { data: hardware } = useQuery<HardwareStatus>({
    queryKey: ['hardwareStatus', printerId],
    queryFn: () => api.getHardwareStatus(printerId),
    enabled: printerId > 0,
    refetchInterval: 5000,
  });

  const hardwareMutation = useMutation({
    mutationFn: (action: 'open' | 'close' | 'plate' | 'refill' | 'stop') => {
      if (action === 'open') return api.openHardwareDoor(printerId);
      if (action === 'close') return api.closeHardwareDoor(printerId);
      if (action === 'plate') return api.changeHardwarePlate(printerId);
      if (action === 'stop') return api.emergencyStopHardware(printerId);
      return api.refillHardwareMagazine(printerId);
    },
    onSuccess: (data) => {
      showToast(data.message);
      queryClient.invalidateQueries({ queryKey: ['hardwareStatus', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const printMutation = useMutation({
    mutationFn: (program: MaintenanceProgram) => api.downloadMaintenancePrint(printerId, program),
    onSuccess: (data) => showToast(data.message),
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  // Wartungsdruck direkt in die Warteschlange (3MF + Queue-Eintrag beim Server).
  const queuePrintMutation = useMutation({
    mutationFn: (program: 'oil' | 'rods') => api.queueMaintenancePrint(printerId, program),
    onSuccess: (data) => {
      showToast(data.message);
      queryClient.invalidateQueries({ queryKey: ['printQueue'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  // Auftrags-Regeln für den Bauteil-Wächter (Schwelle/Enabled pro Druck).
  const [rulesOpen, setRulesOpen] = useState(false);
  const [rulesDraft, setRulesDraft] = useState<Array<{ key_contains: string; threshold: number; enabled: boolean }>>([]);
  const rulesMutation = useMutation({
    mutationFn: () =>
      api.setPartWatcher(printerId, {
        enabled: Boolean(partWatcher?.enabled),
        threshold: partWatcher?.threshold,
        overrides: rulesDraft.filter((rule) => rule.key_contains.trim() !== ''),
      }),
    onSuccess: () => {
      showToast(t('common.success'));
      setRulesOpen(false);
      queryClient.invalidateQueries({ queryKey: ['partWatcher', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  // Automatik: Plattenwechsel nach Druckende (P2 der Monitor-Port-Roadmap).
  const autoPlateChange = hardware?.auto_plate_change ?? null;
  const autoMutation = useMutation({
    mutationFn: (enabled: boolean) => api.updateAutoPlateChange(printerId, { enabled }),
    onSuccess: () => {
      showToast(t('common.success'));
      queryClient.invalidateQueries({ queryKey: ['hardwareStatus', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  // Kamera-Einmessung (P1): vier Plattenecken klicken, Homographie speichern.
  const { data: plateCalibration } = useQuery<PlateCalibrationStatus>({
    queryKey: ['plateCalibration', printerId],
    queryFn: () => api.getPlateCalibration(printerId),
    enabled: printerId > 0,
  });
  const [calibrationOpen, setCalibrationOpen] = useState(false);
  const [calibrationPoints, setCalibrationPoints] = useState<Array<[number, number]>>([]);
  const calibrationMutation = useMutation({
    mutationFn: () => api.setPlateCalibration(printerId, calibrationPoints),
    onSuccess: () => {
      showToast(t('common.success'));
      setCalibrationOpen(false);
      setCalibrationPoints([]);
      queryClient.invalidateQueries({ queryKey: ['plateCalibration', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const calibrationClearMutation = useMutation({
    mutationFn: () => api.clearPlateCalibration(printerId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['plateCalibration', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const { data: layerAlert } = useQuery<LayerAlertStatus>({
    queryKey: ['layerAlert', printerId],
    queryFn: () => api.getLayerAlert(printerId),
    enabled: printerId > 0,
  });
  const [layerInput, setLayerInput] = useState(0);

  useEffect(() => {
    setLayerInput(layerAlert?.layer ?? 0);
  }, [layerAlert?.layer, printerId]);

  const layerMutation = useMutation({
    mutationFn: (layer: number) => api.setLayerAlert(printerId, { enabled: layer > 0, layer }),
    onSuccess: (data) => {
      showToast(t('common.success'));
      setLayerInput(data.layer);
      queryClient.invalidateQueries({ queryKey: ['layerAlert', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const { data: partWatcher } = useQuery<PartWatcherStatus>({
    queryKey: ['partWatcher', printerId],
    queryFn: () => api.getPartWatcher(printerId),
    enabled: printerId > 0,
    refetchInterval: 10000,
  });
  const partWatcherMutation = useMutation({
    mutationFn: (enabled: boolean) => api.setPartWatcher(printerId, { enabled }),
    onSuccess: () => {
      showToast(t('common.success'));
      queryClient.invalidateQueries({ queryKey: ['partWatcher', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const { data: firstLayer } = useQuery<FirstLayerStatus>({
    queryKey: ['firstLayerInspector', printerId],
    queryFn: () => api.getFirstLayerInspector(printerId),
    enabled: printerId > 0,
    refetchInterval: 10000,
  });
  const firstLayerMutation = useMutation({
    mutationFn: (enabled: boolean) => api.setFirstLayerInspector(printerId, enabled),
    onSuccess: () => {
      showToast(t('common.success'));
      queryClient.invalidateQueries({ queryKey: ['firstLayerInspector', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const stopMutation = useMutation({
    mutationFn: () => api.stopMaintenanceProgram(printerId),
    onSuccess: (data) => {
      showToast(data.message);
      queryClient.invalidateQueries({ queryKey: ['maintenanceProgram', printerId] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  if (printers.length === 0) {
    return null;
  }

  const active = Boolean(status?.active);
  const disabled = !canControl || active || !supported || startMutation.isPending;
  const hardwareDisabled = !canControl || !supported || Boolean(hardware?.busy) || hardwareMutation.isPending;
  const showProgress = Boolean(status?.program) && status?.phase !== 'idle';

  return (
    <Card>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Wrench className="w-5 h-5 text-bambu-green" />
            {t('maintenance.programs.title')}
          </h2>
          <label className="flex items-center gap-2 text-sm text-bambu-gray">
            {t('common.printer')}
            <select
              value={printerId}
              onChange={(event) => setPrinterId(Number(event.target.value))}
              className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              aria-label={t('common.printer')}
            >
              {printers.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        {!supported && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            {t('maintenance.programs.onlyP2S')}
          </p>
        )}
        {!canControl && (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            {t('maintenance.programs.noPermission')}
          </p>
        )}

        <div className="flex flex-wrap gap-3">
          <Button size="sm" disabled={disabled} onClick={() => startWithConfirm('oil')}>
            <Droplet className="w-4 h-4" />
            {t('maintenance.programs.oil')}
          </Button>
          <Button size="sm" disabled={disabled} onClick={() => startWithConfirm('rods')}>
            <Wrench className="w-4 h-4" />
            {t('maintenance.programs.rods')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!canControl || !supported || printMutation.isPending}
            onClick={() => printMutation.mutate('oil')}
            title={t('maintenance.programs.oil')}
          >
            <Download className="w-4 h-4" />
            3MF · {t('maintenance.programs.oil')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!canControl || !supported || printMutation.isPending}
            onClick={() => printMutation.mutate('rods')}
            title={t('maintenance.programs.rods')}
          >
            <Download className="w-4 h-4" />
            3MF · {t('maintenance.programs.rods')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!canControl || !supported || queuePrintMutation.isPending}
            onClick={() => {
              if (!window.confirm(t('maintenance.programs.confirmQueuePrint'))) return;
              queuePrintMutation.mutate('oil');
            }}
            title={t('maintenance.programs.confirmQueuePrint')}
          >
            <ListPlus className="w-4 h-4" />
            {t('maintenance.programs.queuePrintOil')}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!canControl || !supported || queuePrintMutation.isPending}
            onClick={() => {
              if (!window.confirm(t('maintenance.programs.confirmQueuePrint'))) return;
              queuePrintMutation.mutate('rods');
            }}
            title={t('maintenance.programs.confirmQueuePrint')}
          >
            <ListPlus className="w-4 h-4" />
            {t('maintenance.programs.queuePrintRods')}
          </Button>
        </div>

        {showProgress && status && (
          <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary p-4 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm font-medium text-white">
                {t(`maintenance.programs.${status.program}`)}
                <span className="text-bambu-gray font-normal"> · {status.percent}%</span>
              </span>
              {active && (
                <Button
                  size="sm"
                  variant="danger"
                  disabled={!canControl || stopMutation.isPending}
                  onClick={() => stopMutation.mutate()}
                >
                  <Square className="w-4 h-4" />
                  {t('maintenance.programs.stop')}
                </Button>
              )}
            </div>
            <div
              className="h-2 rounded-full bg-bambu-dark-tertiary overflow-hidden"
              role="progressbar"
              aria-label={t('maintenance.programs.title')}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={status.percent}
            >
              <div
                className="h-full bg-bambu-green transition-all"
                style={{ width: `${status.active ? status.percent : status.phase === 'done' ? 100 : 0}%` }}
              />
            </div>
            <p className="text-xs text-bambu-gray" aria-live="polite">
              {status.message}
            </p>
          </div>
        )}

        <div className="border-t border-bambu-dark-tertiary pt-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              {hardware?.door === 'open' ? (
                <DoorOpen className="w-4 h-4 text-bambu-green" />
              ) : (
                <DoorClosed className="w-4 h-4 text-bambu-green" />
              )}
              {t('maintenance.programs.hardware')}
            </h3>
            <div className="flex items-center gap-1" aria-label={t('maintenance.programs.hardware')}>
              {(hardware?.slots ?? []).map((slot) => (
                <span
                  key={slot.id}
                  title={`${slot.type} ${slot.id} · ${slot.status}${slot.print ? ` · ${slot.print}` : ''}`}
                  className={`inline-flex h-6 w-6 items-center justify-center rounded text-[10px] font-medium ${
                    slot.type === 'supply'
                      ? slot.status === 'ready'
                        ? 'bg-bambu-green/20 text-bambu-green'
                        : 'bg-bambu-dark-tertiary text-bambu-gray'
                      : slot.status === 'empty'
                        ? 'bg-bambu-dark-tertiary text-bambu-gray'
                        : 'bg-amber-500/20 text-amber-700 dark:text-amber-400'
                  }`}
                >
                  {slot.id}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={hardwareDisabled}
              onClick={() => hardwareMutation.mutate('open')}
            >
              <DoorOpen className="w-4 h-4" />
              {t('maintenance.programs.doorOpen')}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={hardwareDisabled}
              onClick={() => hardwareMutation.mutate('close')}
            >
              <DoorClosed className="w-4 h-4" />
              {t('maintenance.programs.doorClose')}
            </Button>
            <Button
              size="sm"
              disabled={hardwareDisabled}
              onClick={() => hardwareMutation.mutate('plate')}
            >
              <ArrowLeftRight className="w-4 h-4" />
              {t('maintenance.programs.plateChange')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={hardwareDisabled}
              onClick={() => hardwareMutation.mutate('refill')}
            >
              <RefreshCw className="w-4 h-4" />
              {t('maintenance.programs.refill')}
            </Button>
            <Button
              size="sm"
              variant="danger"
              disabled={!canControl}
              onClick={() => hardwareMutation.mutate('stop')}
            >
              <Square className="w-4 h-4" />
              {t('maintenance.programs.emergencyStop')}
            </Button>
          </div>
          {hardware?.error && (
            <p className="text-xs text-red-700 dark:text-red-400">{hardware.error}</p>
          )}
          <p className="text-xs text-bambu-gray">{t('maintenance.programs.hardwareSafety')}</p>
          {/* Automatik: Plattenwechsel nach Druckende */}
          <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
            <div className="min-w-0">
              <p className="text-xs font-medium text-white">
                {t('maintenance.programs.autoPlateChange')}
                {autoPlateChange?.enabled ? (
                  <span className="ml-1 text-bambu-green">({t('common.on')})</span>
                ) : (
                  <span className="ml-1 text-bambu-gray">({t('common.off')})</span>
                )}
              </p>
              {autoPlateChange?.last_run && (
                <p
                  className={`text-xs truncate ${autoPlateChange.last_run.ok ? 'text-bambu-green' : 'text-red-700 dark:text-red-400'}`}
                  title={autoPlateChange.last_run.message}
                >
                  {autoPlateChange.last_run.message}
                </p>
              )}
            </div>
            <Button
              size="sm"
              variant="secondary"
              className="whitespace-nowrap"
              disabled={autoMutation.isPending}
              onClick={() => autoMutation.mutate(!autoPlateChange?.enabled)}
            >
              {autoPlateChange?.enabled
                ? t('maintenance.programs.autoPlateChangeOff')
                : t('maintenance.programs.autoPlateChangeOn')}
            </Button>
          </div>
        </div>

        <div className="border-t border-bambu-dark-tertiary pt-4 flex flex-wrap items-end gap-3">
          <label className="text-xs text-bambu-gray">
            {t('maintenance.programs.layerAlert')}
            <input
              type="number"
              min={0}
              max={100000}
              value={layerInput}
              onChange={(event) => setLayerInput(Math.max(0, Number(event.target.value) || 0))}
              className="mt-1 block w-24 bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              aria-label={t('maintenance.programs.layerAlert')}
            />
          </label>
          <Button
            size="sm"
            variant="secondary"
            disabled={!canControl || layerMutation.isPending}
            onClick={() => layerMutation.mutate(layerInput)}
          >
            <Check className="w-4 h-4" />
            {t('common.save')}
          </Button>
          {layerAlert?.enabled && layerAlert.layer > 0 && (
            <span className="text-xs text-bambu-green">{t('common.on')}</span>
          )}
        </div>

        <div className="border-t border-bambu-dark-tertiary pt-4 flex flex-wrap items-end gap-3">
          <label className="flex items-center gap-2 text-xs text-bambu-gray">
            <input
              type="checkbox"
              checked={Boolean(partWatcher?.enabled)}
              onChange={(event) => partWatcherMutation.mutate(event.target.checked)}
              disabled={!canControl || partWatcherMutation.isPending}
            />
            {t('maintenance.programs.partWatcher')}
          </label>
          <Button
            size="sm"
            variant="secondary"
            className="whitespace-nowrap"
            onClick={() => {
              setRulesDraft((partWatcher?.overrides ?? []).map((rule) => ({ ...rule })));
              setRulesOpen(true);
            }}
          >
            {t('maintenance.programs.jobRules')}
          </Button>
          {partWatcher?.warning && (
            <span className="text-xs text-red-700 dark:text-red-400">{partWatcher.warning.message}</span>
          )}
          <label className="flex items-center gap-2 text-xs text-bambu-gray">
            <input
              type="checkbox"
              checked={Boolean(firstLayer?.enabled)}
              onChange={(event) => firstLayerMutation.mutate(event.target.checked)}
              disabled={!canControl || firstLayerMutation.isPending}
            />
            {t('maintenance.programs.firstLayerInspector')}
          </label>
          {firstLayer?.result && !firstLayer.result.ok && (
            <span className="text-xs text-red-700 dark:text-red-400">{firstLayer.result.message}</span>
          )}
          {/* Leerbett-Prüfung: nur Warnung beim Druckstart */}
          <BedEmptyCheckRow printerId={printerId} canControl={canControl} />
          <SpaghettiCheckRow printerId={printerId} canControl={canControl} />
          {/* Kamera-Einmessung */}
          <Button
            size="sm"
            variant="secondary"
            className="whitespace-nowrap"
            disabled={!canControl || printerId === 0}
            onClick={() => {
              setCalibrationPoints([]);
              setCalibrationOpen(true);
            }}
          >
            {t('maintenance.programs.calibrateCamera')}
          </Button>
          {plateCalibration?.calibrated && (
            <span className="text-xs text-bambu-green">{t('maintenance.programs.calibrationDone')}</span>
          )}
        </div>

        <p className="text-xs text-bambu-gray">{t('maintenance.programs.safety')}</p>
      </CardContent>

      {/* Bauteil-Wächter: Auftrags-Regeln (erster Treffer gewinnt). */}
      {rulesOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 overflow-y-auto">
          <div className="bg-bambu-dark-secondary rounded-xl p-5 max-w-xl w-full border border-bambu-dark-tertiary space-y-3">
            <h3 className="text-base font-semibold text-white mb-1">{t('maintenance.programs.jobRules')}</h3>
            <p className="text-xs text-bambu-gray">{t('maintenance.programs.jobRulesHint')}</p>
            {rulesDraft.map((rule, index) => (
              <div key={index} className="flex flex-wrap items-center gap-2">
                <input
                  value={rule.key_contains}
                  onChange={(event) =>
                    setRulesDraft((rules) => rules.map((r, i) => (i === index ? { ...r, key_contains: event.target.value } : r)))
                  }
                  placeholder="im Drucknamen (z. B. 'Handtuch')"
                  className="flex-1 min-w-40 bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                  aria-label={t('maintenance.programs.jobRulesFragment')}
                />
                <input
                  type="number"
                  min={0.05}
                  max={20}
                  step={0.05}
                  value={rule.threshold}
                  onChange={(event) =>
                    setRulesDraft((rules) => rules.map((r, i) => (i === index ? { ...r, threshold: Number(event.target.value) } : r)))
                  }
                  className="w-20 bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                  aria-label={t('maintenance.programs.jobRulesThreshold')}
                />
                <input
                  type="checkbox"
                  checked={rule.enabled}
                  onChange={(event) =>
                    setRulesDraft((rules) => rules.map((r, i) => (i === index ? { ...r, enabled: event.target.checked } : r)))
                  }
                  aria-label={t('common.enabled')}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setRulesDraft((rules) => rules.filter((_, i) => i !== index))}
                >
                  ✕
                </Button>
              </div>
            ))}
            <div className="flex flex-wrap justify-between gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  setRulesDraft((rules) => [...rules, { key_contains: '', threshold: partWatcher?.threshold ?? 1, enabled: true }])
                }
              >
                +
              </Button>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setRulesOpen(false)}>{t('common.cancel')}</Button>
                <Button size="sm" disabled={rulesMutation.isPending} onClick={() => rulesMutation.mutate()}>
                  {t('common.save')}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Kamera-Einmessung: Live-Snapshot, vier Ecken anklicken (TL, TR, BR, BL). */}
      {calibrationOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 overflow-y-auto">
          <div className="bg-bambu-dark-secondary rounded-xl p-5 max-w-2xl w-full border border-bambu-dark-tertiary">
            <h3 className="text-base font-semibold text-white mb-2">
              {t('maintenance.programs.calibrateCamera')}
            </h3>
            <p className="text-xs text-bambu-gray mb-3">{t('maintenance.programs.calibrationHint')}</p>
            <div
              className="relative"
              onPointerDown={(event) => {
                if (calibrationPoints.length >= 4 || calibrationMutation.isPending) return;
                const target = event.currentTarget.getBoundingClientRect();
                const x = Math.min(1, Math.max(0, (event.clientX - target.left) / target.width));
                const y = Math.min(1, Math.max(0, (event.clientY - target.top) / target.height));
                setCalibrationPoints((points) => [...points, [Number(x.toFixed(4)), Number(y.toFixed(4))]]);
              }}
            >
              <img
                src={api.getCameraSnapshotUrl(printerId) + '&ts=' + Date.now()}
                alt=""
                className="w-full rounded-lg select-none pointer-events-none"
                draggable={false}
              />
              {calibrationPoints.map(([x, y], index) => (
                <span
                  key={`${x}-${y}`}
                  className="absolute w-4 h-4 -ml-2 -mt-2 rounded-full bg-bambu-green ring-2 ring-white/80 pointer-events-none"
                  style={{ left: `${x * 100}%`, top: `${y * 100}%` }}
                />
              ))}
              {/* Klick-Reihenfolge anzeigen */}
              <span className="absolute left-2 top-2 rounded bg-black/60 px-2 py-0.5 text-[11px] text-white">
                {calibrationPoints.length < 4
                  ? `${t('maintenance.programs.calibrationNext')} ${calibrationPoints.length + 1}/4`
                  : t('maintenance.programs.calibrationSet')}
              </span>
            </div>
            <div className="mt-4 flex flex-wrap justify-end gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setCalibrationOpen(false);
                  setCalibrationPoints([]);
                }}
              >
                {t('common.cancel')}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={calibrationMutation.isPending}
                onClick={() => setCalibrationPoints((points) => points.slice(0, -1))}
              >
                {t('maintenance.programs.calibrationUndo')}
              </Button>
              <Button
                size="sm"
                disabled={calibrationPoints.length !== 4 || calibrationMutation.isPending}
                onClick={() => calibrationMutation.mutate()}
              >
                {t('common.save')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

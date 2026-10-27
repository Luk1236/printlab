import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeftRight, Check, DoorClosed, DoorOpen, Download, Droplet, RefreshCw, Square, Wrench } from 'lucide-react';

import { api } from '../api/client';
import type {
  HardwareStatus,
  LayerAlertStatus,
  MaintenanceProgram,
  MaintenanceProgramStatus,
  Printer,
} from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
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
    mutationFn: (action: 'open' | 'close' | 'plate' | 'refill') => {
      if (action === 'open') return api.openHardwareDoor(printerId);
      if (action === 'close') return api.closeHardwareDoor(printerId);
      if (action === 'plate') return api.changeHardwarePlate(printerId);
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
          </div>
          {hardware?.error && (
            <p className="text-xs text-red-700 dark:text-red-400">{hardware.error}</p>
          )}
          <p className="text-xs text-bambu-gray">{t('maintenance.programs.hardwareSafety')}</p>
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

        <p className="text-xs text-bambu-gray">{t('maintenance.programs.safety')}</p>
      </CardContent>
    </Card>
  );
}

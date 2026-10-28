import { useState } from 'react';
import { X } from 'lucide-react';

import type { CalibrationMode, PrintQueueBulkUpdate } from '../api/client';
import { Button } from './Button';
import { BulkPriorityFields } from './QueuePriority';
import type { BulkPriorityPatch } from './QueuePriority';

// Bulk edit modal for multiple queue items
export function BulkEditModal({
  selectedCount,
  printers,
  onSave,
  onClose,
  isSaving,
  canControlPrinter,
  hasGcodeSnippets,
  t,
}: {
  selectedCount: number;
  printers: { id: number; name: string; nozzle_count?: number }[];
  onSave: (data: Partial<PrintQueueBulkUpdate>) => void;
  onClose: () => void;
  isSaving: boolean;
  canControlPrinter: boolean;
  hasGcodeSnippets: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
}) {
  const [printerId, setPrinterId] = useState<number | null | 'unchanged'>('unchanged');
  const [manualStart, setManualStart] = useState<boolean | 'unchanged'>('unchanged');
  const [autoOffAfter, setAutoOffAfter] = useState<boolean | 'unchanged'>('unchanged');
  const [requirePreviousSuccess, setRequirePreviousSuccess] = useState<boolean | 'unchanged'>('unchanged');
  const [gcodeInjection, setGcodeInjection] = useState<boolean | 'unchanged'>('unchanged');
  const [bedLevelling, setBedLevelling] = useState<CalibrationMode | 'unchanged'>('unchanged');
  const [flowCali, setFlowCali] = useState<CalibrationMode | 'unchanged'>('unchanged');
  const [vibrationCali, setVibrationCali] = useState<boolean | 'unchanged'>('unchanged');
  const [layerInspect, setLayerInspect] = useState<boolean | 'unchanged'>('unchanged');
  const [timelapse, setTimelapse] = useState<boolean | 'unchanged'>('unchanged');
  const [useAms, setUseAms] = useState<boolean | 'unchanged'>('unchanged');
  const [confirmOutcome, setConfirmOutcome] = useState<boolean | 'unchanged'>('unchanged');
  const [nozzleOffsetCali, setNozzleOffsetCali] = useState<CalibrationMode | 'unchanged'>('unchanged');
  const [priorityPatch, setPriorityPatch] = useState<BulkPriorityPatch>({});

  // Show the dual-nozzle-only toggle when the user has at least one
  // dual-nozzle printer registered (H2D/H2D Pro/H2C/X2D). Single-nozzle
  // queues never see it — the MQTT layer ignores the field anyway.
  const hasDualNozzlePrinter = printers.some(p => p.nozzle_count === 2);

  const handleSave = () => {
    const data: Partial<PrintQueueBulkUpdate> = {};
    if (printerId !== 'unchanged') data.printer_id = printerId;
    if (manualStart !== 'unchanged') data.manual_start = manualStart;
    if (autoOffAfter !== 'unchanged') data.auto_off_after = autoOffAfter;
    if (requirePreviousSuccess !== 'unchanged') data.require_previous_success = requirePreviousSuccess;
    if (gcodeInjection !== 'unchanged') data.gcode_injection = gcodeInjection;
    if (bedLevelling !== 'unchanged') data.bed_levelling = bedLevelling;
    if (flowCali !== 'unchanged') data.flow_cali = flowCali;
    if (vibrationCali !== 'unchanged') data.vibration_cali = vibrationCali;
    if (layerInspect !== 'unchanged') data.layer_inspect = layerInspect;
    if (timelapse !== 'unchanged') data.timelapse = timelapse;
    if (useAms !== 'unchanged') data.use_ams = useAms;
    if (confirmOutcome !== 'unchanged') data.confirm_outcome = confirmOutcome;
    if (nozzleOffsetCali !== 'unchanged') data.nozzle_offset_cali = nozzleOffsetCali;
    onSave({ ...data, ...priorityPatch });
  };

  const hasChanges = printerId !== 'unchanged' || manualStart !== 'unchanged' || autoOffAfter !== 'unchanged' ||
    requirePreviousSuccess !== 'unchanged' || bedLevelling !== 'unchanged' || flowCali !== 'unchanged' ||
    vibrationCali !== 'unchanged' || layerInspect !== 'unchanged' || timelapse !== 'unchanged' || useAms !== 'unchanged' ||
    confirmOutcome !== 'unchanged' || nozzleOffsetCali !== 'unchanged' || gcodeInjection !== 'unchanged' ||
    Object.keys(priorityPatch).length > 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between p-4 border-b border-bambu-dark-tertiary">
          <h2 className="text-lg font-semibold text-white">
            {t('queue.bulkEdit.title', { count: selectedCount })}
          </h2>
          <button onClick={onClose} className="p-1 hover:bg-bambu-dark rounded">
            <X className="w-5 h-5 text-bambu-gray" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          <p className="text-sm text-bambu-gray">
            {t('queue.bulkEdit.description')}
          </p>

          <BulkPriorityFields onChange={setPriorityPatch} />

          {/* Printer Assignment */}
          <div>
            <label className="block text-sm font-medium text-white mb-2">{t('queue.bulkEdit.printer')}</label>
            <select
              value={printerId === null ? 'null' : printerId === 'unchanged' ? 'unchanged' : String(printerId)}
              onChange={(e) => {
                const val = e.target.value;
                if (val === 'unchanged') setPrinterId('unchanged');
                else if (val === 'null') setPrinterId(null);
                else setPrinterId(Number(val));
              }}
              className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
            >
              <option value="unchanged">{t('queue.bulkEdit.noChange')}</option>
              <option value="null">{t('queue.filter.unassigned')}</option>
              {printers.map(p => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>

          {/* Queue Options */}
          <div>
            <label className="block text-sm font-medium text-white mb-2">{t('queue.bulkEdit.queueOptions')}</label>
            <div className="space-y-2">
              <TriStateToggle label={t('queue.bulkEdit.staged')} value={manualStart} onChange={setManualStart} t={t} />
              <TriStateToggle label={t('queue.bulkEdit.autoPowerOff')} value={autoOffAfter} onChange={setAutoOffAfter} disabled={!canControlPrinter} t={t} />
              <TriStateToggle label={t('queue.bulkEdit.requirePrevious')} value={requirePreviousSuccess} onChange={setRequirePreviousSuccess} t={t} />
              {/* Same gate as the print modal's checkbox (#3058): hidden until an
                  admin has saved a snippet for some printer model, so the toggle
                  never promises an injection that has nothing to inject. */}
              {hasGcodeSnippets && (
                <TriStateToggle label={t('queue.bulkEdit.gcodeInjection')} value={gcodeInjection} onChange={setGcodeInjection} t={t} />
              )}
            </div>
          </div>

          {/* Print Options */}
          <div>
            <label className="block text-sm font-medium text-white mb-2">{t('queue.bulkEdit.printOptions')}</label>
            <div className="space-y-2">
              <CalibrationModeToggle label={t('queue.bulkEdit.bedLevelling')} value={bedLevelling} onChange={setBedLevelling} t={t} />
              <CalibrationModeToggle label={t('queue.bulkEdit.flowCalibration')} value={flowCali} onChange={setFlowCali} t={t} />
              <TriStateToggle label={t('queue.bulkEdit.vibrationCalibration')} value={vibrationCali} onChange={setVibrationCali} t={t} />
              <TriStateToggle label={t('queue.bulkEdit.layerInspection')} value={layerInspect} onChange={setLayerInspect} t={t} />
              <TriStateToggle label={t('queue.bulkEdit.timelapse')} value={timelapse} onChange={setTimelapse} t={t} />
              <TriStateToggle label={t('queue.bulkEdit.useAms')} value={useAms} onChange={setUseAms} t={t} />
              <TriStateToggle label={t('queue.bulkEdit.confirmOutcome')} value={confirmOutcome} onChange={setConfirmOutcome} t={t} />
              {hasDualNozzlePrinter && (
                <CalibrationModeToggle label={t('queue.bulkEdit.nozzleOffsetCali')} value={nozzleOffsetCali} onChange={setNozzleOffsetCali} t={t} />
              )}
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-3 p-4 border-t border-bambu-dark-tertiary">
          <Button variant="secondary" onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
          >
            {isSaving ? t('common.saving') : t('queue.bulkEdit.applyChanges')}
          </Button>
        </div>
      </div>
    </div>
  );
}

// Tri-state toggle for bulk edit (unchanged / on / off)
function TriStateToggle({
  label,
  value,
  onChange,
  disabled,
  t,
}: {
  label: string;
  value: boolean | 'unchanged';
  onChange: (val: boolean | 'unchanged') => void;
  disabled?: boolean;
  t: (key: string) => string;
}) {
  return (
    <div className={`flex items-center justify-between py-1 ${disabled ? 'opacity-50' : ''}`}>
      <span className="text-sm text-bambu-gray">{label}</span>
      <div className="flex items-center gap-1 bg-bambu-dark rounded-lg p-0.5">
        <button
          onClick={() => onChange('unchanged')}
          disabled={disabled}
          className={`px-2 py-1 text-xs rounded ${value === 'unchanged' ? 'bg-bambu-dark-tertiary text-white' : 'text-bambu-gray hover:text-white'} disabled:cursor-not-allowed`}
        >
          —
        </button>
        <button
          onClick={() => onChange(false)}
          disabled={disabled}
          className={`px-2 py-1 text-xs rounded ${value === false ? 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400' : 'text-bambu-gray hover:text-white'} disabled:cursor-not-allowed`}
        >
          {t('common.off')}
        </button>
        <button
          onClick={() => onChange(true)}
          disabled={disabled}
          className={`px-2 py-1 text-xs rounded ${value === true ? 'bg-bambu-green/20 text-bambu-green' : 'text-bambu-gray hover:text-white'} disabled:cursor-not-allowed`}
        >
          {t('common.on')}
        </button>
      </div>
    </div>
  );
}

// Four-state selector for the tri-state calibration options in bulk edit
// (unchanged / off / auto / on). Mirrors TriStateToggle's chrome.
function CalibrationModeToggle({
  label,
  value,
  onChange,
  t,
}: {
  label: string;
  value: CalibrationMode | 'unchanged';
  onChange: (val: CalibrationMode | 'unchanged') => void;
  t: (key: string) => string;
}) {
  const modes: Array<{ key: CalibrationMode | 'unchanged'; label: string; active: string }> = [
    { key: 'unchanged', label: '—', active: 'bg-bambu-dark-tertiary text-white' },
    { key: 'off', label: t('settings.calibrationMode_off'), active: 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400' },
    { key: 'auto', label: t('settings.calibrationMode_auto'), active: 'bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400' },
    { key: 'on', label: t('settings.calibrationMode_on'), active: 'bg-bambu-green/20 text-bambu-green' },
  ];
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-sm text-bambu-gray">{label}</span>
      <div className="flex items-center gap-1 bg-bambu-dark rounded-lg p-0.5">
        {modes.map(({ key, label: modeLabel, active }) => (
          <button
            key={key}
            onClick={() => onChange(key)}
            className={`px-2 py-1 text-xs rounded ${value === key ? active : 'text-bambu-gray hover:text-white'}`}
          >
            {modeLabel}
          </button>
        ))}
      </div>
    </div>
  );
}

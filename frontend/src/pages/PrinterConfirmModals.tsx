/**
 * Action confirmation modals for the printer card (power, maintenance, stop, pause, resume, HA entities).
 * Extracted from PrinterCard.tsx for modularity and file size budget compliance.
 */

import { useTranslation } from 'react-i18next';
import { ConfirmModal } from '../components/ConfirmModal';
import type { Printer, SmartPlug } from '../api/types';

export interface PrinterConfirmModalsProps {
  printer: Printer;
  status: { state?: string | null } | null | undefined;
  smartPlug: Pick<SmartPlug, 'id' | 'name'> | null | undefined;
  showPowerOnConfirm: boolean;
  setShowPowerOnConfirm: (show: boolean) => void;
  confirmMaintenanceEnter: boolean;
  setConfirmMaintenanceEnter: (confirm: boolean) => void;
  showPowerOffConfirm: boolean;
  setShowPowerOffConfirm: (show: boolean) => void;
  haToggleConfirm: Pick<SmartPlug, 'id' | 'name' | 'ha_entity_id'> | null;
  setHaToggleConfirm: (val: null) => void;
  showStopConfirm: boolean;
  setShowStopConfirm: (show: boolean) => void;
  showPauseConfirm: boolean;
  setShowPauseConfirm: (show: boolean) => void;
  showResumeConfirm: boolean;
  setShowResumeConfirm: (show: boolean) => void;
  powerControlMutation: { mutate: (action: 'on' | 'off') => void };
  maintenanceMutation: { mutate: (enabled: boolean) => void };
  runScriptMutation: { mutate: (args: { id: number; action: 'on' | 'toggle' }) => void };
  stopPrintMutation: { mutate: () => void };
  pausePrintMutation: { mutate: () => void };
  resumePrintMutation: { mutate: () => void };
}

export function PrinterConfirmModals({
  printer,
  status,
  smartPlug,
  showPowerOnConfirm,
  setShowPowerOnConfirm,
  confirmMaintenanceEnter,
  setConfirmMaintenanceEnter,
  showPowerOffConfirm,
  setShowPowerOffConfirm,
  haToggleConfirm,
  setHaToggleConfirm,
  showStopConfirm,
  setShowStopConfirm,
  showPauseConfirm,
  setShowPauseConfirm,
  showResumeConfirm,
  setShowResumeConfirm,
  powerControlMutation,
  maintenanceMutation,
  runScriptMutation,
  stopPrintMutation,
  pausePrintMutation,
  resumePrintMutation,
}: PrinterConfirmModalsProps) {
  const { t } = useTranslation();

  return (
    <>
      {/* Power On Confirmation */}
      {showPowerOnConfirm && smartPlug && (
        <ConfirmModal
          title={t('printers.confirm.powerOnTitle')}
          message={t('printers.confirm.powerOnMessage', { name: printer.name })}
          confirmText={t('printers.confirm.powerOnButton')}
          variant="default"
          onConfirm={() => {
            powerControlMutation.mutate('on');
            setShowPowerOnConfirm(false);
          }}
          onCancel={() => setShowPowerOnConfirm(false)}
        />
      )}

      {/* Maintenance Mode mid-print confirmation (#1476) — entering maintenance
          disconnects MQTT, which stops progress tracking + completion
          notifications for the in-flight job. Idle / FINISH / FAILED states
          skip this dialog and toggle directly. */}
      {confirmMaintenanceEnter && (
        <ConfirmModal
          title={t('printers.maintenance.confirmMidPrintTitle')}
          message={t('printers.maintenance.confirmMidPrintMessage', { name: printer.name })}
          confirmText={t('printers.maintenance.menuEnter')}
          variant="danger"
          onConfirm={() => {
            maintenanceMutation.mutate(false);
            setConfirmMaintenanceEnter(false);
          }}
          onCancel={() => setConfirmMaintenanceEnter(false)}
        />
      )}

      {/* Power Off Confirmation */}
      {showPowerOffConfirm && smartPlug && (
        <ConfirmModal
          title={t('printers.confirm.powerOffTitle')}
          message={
            status?.state === 'RUNNING'
              ? t('printers.confirm.powerOffWarning', { name: printer.name })
              : t('printers.confirm.powerOffMessage', { name: printer.name })
          }
          confirmText={t('printers.confirm.powerOffButton')}
          variant="danger"
          onConfirm={() => {
            powerControlMutation.mutate('off');
            setShowPowerOffConfirm(false);
          }}
          onCancel={() => setShowPowerOffConfirm(false)}
        />
      )}

      {/* HA entity toggle confirmation (Show on Printer Card switches) */}
      {haToggleConfirm && (
        <ConfirmModal
          title={t('printers.confirm.haToggleTitle', { name: haToggleConfirm.name })}
          message={
            status?.state === 'RUNNING'
              ? t('printers.confirm.haToggleWarning', {
                  name: printer.name,
                  entity: haToggleConfirm.ha_entity_id || haToggleConfirm.name,
                })
              : t('printers.confirm.haToggleMessage', {
                  entity: haToggleConfirm.ha_entity_id || haToggleConfirm.name,
                })
          }
          confirmText={t('printers.confirm.haToggleButton')}
          variant={status?.state === 'RUNNING' ? 'danger' : 'default'}
          onConfirm={() => {
            runScriptMutation.mutate({ id: haToggleConfirm.id, action: 'toggle' });
            setHaToggleConfirm(null);
          }}
          onCancel={() => setHaToggleConfirm(null)}
        />
      )}

      {/* Stop Print Confirmation */}
      {showStopConfirm && (
        <ConfirmModal
          title={t('printers.confirm.stopTitle')}
          message={t('printers.confirm.stopMessage', { name: printer.name })}
          confirmText={t('printers.confirm.stopButton')}
          variant="danger"
          onConfirm={() => {
            stopPrintMutation.mutate();
            setShowStopConfirm(false);
          }}
          onCancel={() => setShowStopConfirm(false)}
        />
      )}

      {/* Pause Print Confirmation */}
      {showPauseConfirm && (
        <ConfirmModal
          title={t('printers.confirm.pauseTitle')}
          message={t('printers.confirm.pauseMessage', { name: printer.name })}
          confirmText={t('printers.confirm.pauseButton')}
          variant="default"
          onConfirm={() => {
            pausePrintMutation.mutate();
            setShowPauseConfirm(false);
          }}
          onCancel={() => setShowPauseConfirm(false)}
        />
      )}

      {/* Resume Print Confirmation */}
      {showResumeConfirm && (
        <ConfirmModal
          title={t('printers.confirm.resumeTitle')}
          message={t('printers.confirm.resumeMessage', { name: printer.name })}
          confirmText={t('printers.confirm.resumeButton')}
          variant="default"
          onConfirm={() => {
            resumePrintMutation.mutate();
            setShowResumeConfirm(false);
          }}
          onCancel={() => setShowResumeConfirm(false)}
        />
      )}
    </>
  );
}

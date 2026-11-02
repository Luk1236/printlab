/**
 * Die Dialoge und Popovers der Druckerkarte: Firmware-Aktualisierung, Bearbeiten,
 * Druckbett-Prüfung (Plate Check) und AMS-Trocknungs-Popover.
 *
 * Eigene Datei, damit die Druckerkarte modular und unter dem Größenbudget bleibt.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  AlertCircle,
  AlertTriangle,
  Box,
  CheckCircle,
  Download,
  Flame,
  Loader2,
  Pencil,
  ScanSearch,
  Wrench,
  X,
  XCircle,
} from 'lucide-react';
import { api, firmwareApi } from '../api/client';
import type {
  AMSUnit,
  FirmwareUpdateInfo,
  FirmwareUploadStatus,
  Printer,
  PrinterCreate,
  PrinterDiagnosticResult,
} from '../api/client';
import { Card, CardContent } from '../components/Card';
import { Button } from '../components/Button';
import { NumberInput } from '../components/NumberInput';
import { DiagnosticChecklist } from '../components/ConnectionDiagnostic';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { compareFwVersions } from '../utils/firmwareVersion';
import { formatDurationFromHours, parseUTCDate } from '../utils/date';
import type { PopoverPosition } from '../utils/popoverPosition';
import type { DryingPreset } from '../utils/dryingPresets';
import { DRYING_DELAY_OPTIONS, DRYING_PRESETS } from './printerCardHelpers';
import { ToolbarDropdown } from './PrinterCardParts';
import { computeStartAfter, type DryingStartMode } from '../lib/scheduledDrying';
export function FirmwareUpdateModal({
  printer,
  firmwareInfo,
  onClose,
}: {
  printer: Printer;
  firmwareInfo: FirmwareUpdateInfo;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { hasPermission } = useAuth();
  const canUpdate = hasPermission('firmware:update');
  const [uploadStatus, setUploadStatus] = useState<FirmwareUploadStatus | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [pollInterval, setPollInterval] = useState<NodeJS.Timeout | null>(null);
  const [selectedVersion, setSelectedVersion] = useState<string | null>(
    firmwareInfo.update_available ? firmwareInfo.latest_version : null,
  );

  // Prepare check query — runs when a version is selected and user can update
  const { data: prepareInfo, isLoading: isPreparing } = useQuery({
    queryKey: ['firmwarePrepare', printer.id, selectedVersion],
    queryFn: () => firmwareApi.prepareUpload(printer.id, selectedVersion ?? undefined),
    staleTime: 30000,
    enabled: !!selectedVersion && canUpdate && !isUploading,
  });

  // Start upload mutation
  const uploadMutation = useMutation({
    mutationFn: () => firmwareApi.startUpload(printer.id, selectedVersion ?? undefined),
    onSuccess: () => {
      setIsUploading(true);
      // Start polling for status
      const interval = setInterval(async () => {
        try {
          const status = await firmwareApi.getUploadStatus(printer.id);
          setUploadStatus(status);
          if (status.status === 'complete' || status.status === 'error') {
            clearInterval(interval);
            setPollInterval(null);
            setIsUploading(false);
            if (status.status === 'complete') {
              showToast(t('printers.firmwareModal.uploadedToast'), 'success');
              queryClient.invalidateQueries({ queryKey: ['firmwareUpdate', printer.id] });
            }
          }
        } catch {
          // Ignore errors during polling
        }
      }, 2000);
      setPollInterval(interval);
    },
    onError: (error: Error) => {
      showToast(t('printers.firmwareModal.uploadFailed', { error: error.message }), 'error');
      setIsUploading(false);
    },
  });

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [pollInterval]);

  const handleStartUpload = () => {
    setUploadStatus(null);
    uploadMutation.mutate();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <Card className="w-full max-w-md mx-4">
        <CardContent>
          <div className="flex items-start gap-3 mb-4">
            <div className={`p-2 rounded-full ${firmwareInfo.update_available ? 'bg-orange-100 dark:bg-orange-500/20' : 'bg-status-ok/20'}`}>
              {firmwareInfo.update_available
                ? <Download className="w-5 h-5 text-orange-600 dark:text-orange-400" />
                : <CheckCircle className="w-5 h-5 text-status-ok" />}
            </div>
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-white">
                {firmwareInfo.update_available ? t('printers.firmwareModal.title') : t('printers.firmwareModal.titleUpToDate')}
              </h3>
              <p className="text-sm text-bambu-gray mt-1">
                {printer.name}
              </p>
            </div>
          </div>

          {/* Version Info */}
          {(() => {
            const selectedEntry = selectedVersion
              ? firmwareInfo.available_versions?.find((v) => v.version === selectedVersion)
              : null;
            const displayVersion = selectedVersion ?? firmwareInfo.latest_version;
            const displayNotes = selectedEntry?.release_notes ?? firmwareInfo.release_notes;
            const showSecondLine = !!displayVersion && displayVersion !== firmwareInfo.current_version;
            return (
              <div className="bg-bambu-dark rounded-lg p-3 mb-4">
                <div className="flex justify-between items-center text-sm">
                  <span className="text-bambu-gray">{t('printers.firmwareModal.currentVersion')}</span>
                  <span className={`font-mono ${showSecondLine ? 'text-white' : 'text-status-ok'}`}>
                    {firmwareInfo.current_version || t('common.unknown')}
                  </span>
                </div>
                {showSecondLine && (
                  <div className="flex justify-between items-center text-sm mt-1">
                    <span className="text-bambu-gray">{t('printers.firmwareModal.latestVersion')}</span>
                    <span className="text-orange-700 dark:text-orange-400 font-mono">{displayVersion}</span>
                  </div>
                )}
                {displayNotes && (
                  <details className="mt-3 text-sm" open={!showSecondLine} key={displayVersion ?? 'none'}>
                    <summary className={`cursor-pointer hover:underline ${showSecondLine ? 'text-orange-700 dark:text-orange-400' : 'text-status-ok'}`}>
                      {t('printers.firmwareModal.releaseNotes')}
                    </summary>
                    <div className="mt-2 text-bambu-gray text-xs max-h-40 overflow-y-auto whitespace-pre-wrap">
                      {displayNotes}
                    </div>
                  </details>
                )}
              </div>
            );
          })()}

          {/* Available versions list */}
          {firmwareInfo.available_versions && firmwareInfo.available_versions.length > 0 && !isUploading && uploadStatus?.status !== 'complete' && (
            <div className="mb-4">
              <div className="text-xs text-bambu-gray mb-2">{t('printers.firmwareModal.availableVersions')}</div>
              <div className="max-h-56 overflow-y-auto border border-bambu-dark-tertiary rounded-lg divide-y divide-bambu-dark-tertiary">
                {firmwareInfo.available_versions.map((v) => {
                  const isCurrent = firmwareInfo.current_version === v.version;
                  const isSelected = selectedVersion === v.version;
                  const cmp = firmwareInfo.current_version
                    ? compareFwVersions(v.version, firmwareInfo.current_version)
                    : 0;
                  const relLabel = isCurrent
                    ? t('printers.firmwareModal.currentBadge')
                    : cmp > 0
                      ? t('printers.firmwareModal.newerBadge')
                      : t('printers.firmwareModal.olderBadge');
                  const relClass = isCurrent
                    ? 'text-bambu-gray'
                    : cmp > 0
                      ? 'text-orange-700 dark:text-orange-400'
                      : 'text-blue-700 dark:text-blue-400';
                  return (
                    <button
                      key={v.version}
                      type="button"
                      disabled={!v.file_available || !canUpdate || isCurrent}
                      onClick={() => setSelectedVersion(v.version)}
                      className={`w-full text-left px-3 py-2 text-sm flex items-center justify-between gap-2 transition-colors ${
                        isSelected ? 'bg-orange-50 dark:bg-orange-500/10' : 'hover:bg-bambu-dark'
                      } ${!v.file_available || !canUpdate || isCurrent ? 'opacity-60 cursor-not-allowed' : 'cursor-pointer'}`}
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-mono text-white">{v.version}</span>
                        <span className={`text-xs ${relClass}`}>{relLabel}</span>
                      </div>
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        isCurrent
                          ? 'bg-blue-50 dark:bg-blue-500/15 text-blue-700 dark:text-blue-400 border border-blue-300 dark:border-blue-500/30'
                          : v.file_available
                            ? 'bg-bambu-green/15 text-bambu-green border border-bambu-green/30'
                            : 'bg-bambu-gray/10 text-bambu-gray border border-bambu-gray/30'
                      }`}>
                        {isCurrent
                          ? t('printers.firmwareModal.installed')
                          : v.file_available
                          ? t('printers.firmwareModal.usable')
                          : t('printers.firmwareModal.unavailable')}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Status / Progress (only when a version is selected) */}
          {!selectedVersion ? null : isPreparing ? (
            <div className="flex items-center gap-2 text-bambu-gray text-sm mb-4">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('printers.firmwareModal.checkingPrereqs')}
            </div>
          ) : prepareInfo && !isUploading && !uploadStatus ? (
            <div className="mb-4">
              {prepareInfo.can_proceed ? (
                <div className="flex items-center gap-2 text-bambu-green text-sm">
                  <Box className="w-4 h-4" />
                  {t('printers.firmwareModal.sdCardReady')}
                </div>
              ) : (
                <div className="space-y-1">
                  {prepareInfo.errors.map((error, i) => (
                    <div key={i} className="flex items-center gap-2 text-red-700 dark:text-red-400 text-sm">
                      <AlertCircle className="w-4 h-4 flex-shrink-0" />
                      {error}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}

          {/* Upload Progress */}
          {(isUploading || uploadStatus) && uploadStatus && (
            <div className="mb-4">
              <div className="flex items-center justify-between text-sm mb-1">
                <span className="text-bambu-gray capitalize">{uploadStatus.status}</span>
                <span className="text-white">{uploadStatus.progress}%</span>
              </div>
              <div className="w-full bg-bambu-dark-tertiary rounded-full h-2">
                <div
                  className={`h-2 rounded-full transition-all ${
                    uploadStatus.status === 'error' ? 'bg-status-error' :
                    uploadStatus.status === 'complete' ? 'bg-status-ok' : 'bg-orange-500'
                  } ${uploadStatus.status === 'uploading' ? 'animate-pulse' : ''}`}
                  style={{ width: `${uploadStatus.progress}%` }}
                />
              </div>
              <p className="text-xs text-bambu-gray mt-1">{uploadStatus.message}</p>
              {uploadStatus.error && (
                <p className="text-xs text-red-700 dark:text-red-400 mt-1">{uploadStatus.error}</p>
              )}
            </div>
          )}

          {/* Success Message */}
          {uploadStatus?.status === 'complete' && (
            <div className="bg-bambu-green/10 border border-bambu-green/30 rounded-lg p-3 mb-4">
              <p className="text-sm text-bambu-green font-medium mb-2">
                {t('printers.firmwareModal.uploadedSuccess')}
              </p>
              <p className="text-xs text-bambu-gray">
                {t('printers.firmwareModal.applyInstructions')}
              </p>
              <ol className="text-xs text-bambu-gray mt-1 list-decimal list-inside space-y-1">
                <li dangerouslySetInnerHTML={{ __html: t('printers.firmwareModal.step1') }} />
                <li dangerouslySetInnerHTML={{ __html: t('printers.firmwareModal.step2') }} />
                <li dangerouslySetInnerHTML={{ __html: t('printers.firmwareModal.step3') }} />
                <li>{t('printers.firmwareModal.step4')}</li>
              </ol>
            </div>
          )}

          {/* Buttons */}
          <div className="flex gap-2 justify-end">
            <Button variant="secondary" onClick={onClose}>
              {uploadStatus?.status === 'complete' ? t('printers.firmwareModal.done') : t('common.cancel')}
            </Button>
            {prepareInfo?.can_proceed && !isUploading && uploadStatus?.status !== 'complete' && canUpdate && (
              <Button
                onClick={handleStartUpload}
                disabled={uploadMutation.isPending}
              >
                {uploadMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin mr-2" />
                    {t('printers.firmwareModal.starting')}
                  </>
                ) : (
                  <>
                    <Download className="w-4 h-4 mr-2" />
                    {t('printers.firmwareModal.uploadFirmware')}
                  </>
                )}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

export function EditPrinterModal({
  printer,
  onClose,
}: {
  printer: Printer;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [form, setForm] = useState({
    name: printer.name,
    ip_address: printer.ip_address,
    access_code: '',
    model: printer.model || '',
    location: printer.location || '',
    auto_archive: printer.auto_archive,
    is_active: printer.is_active,
  });

  // Setup-time pre-flight — same warn-on-save as the Add-Printer dialog, so an
  // edit that breaks connectivity (e.g. a mistyped IP) is caught before save.
  const [checkingSave, setCheckingSave] = useState(false);
  const [saveWarning, setSaveWarning] = useState<PrinterDiagnosticResult | null>(null);

  const updateMutation = useMutation({
    mutationFn: (data: Partial<PrinterCreate>) => api.updatePrinter(printer.id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['printers'] });
      queryClient.invalidateQueries({ queryKey: ['printerStatus', printer.id] });
      onClose();
    },
    onError: (error: Error) => showToast(error.message || t('printers.toast.failedToUpdate'), 'error'),
  });

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const doSave = () => {
    const data: Partial<PrinterCreate> = {
      name: form.name,
      ip_address: form.ip_address,
      model: form.model || undefined,
      location: form.location || undefined,
      auto_archive: form.auto_archive,
      is_active: form.is_active,
    };
    // Only include access_code if it was changed
    if (form.access_code) {
      data.access_code = form.access_code;
    }
    updateMutation.mutate(data);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setCheckingSave(true);
    try {
      const result = await api.diagnoseConnection({
        ip_address: form.ip_address.trim(),
        serial_number: printer.serial_number,
        access_code: form.access_code || undefined,
      });
      if (result.checks.some((c) => c.status === 'fail')) {
        setSaveWarning(result);
        return;
      }
    } catch {
      // Diagnostic infrastructure failed — never block the save on it.
    } finally {
      setCheckingSave(false);
    }
    doSave();
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-start sm:items-center justify-center z-50 p-4 overflow-y-auto"
      onClick={onClose}
    >
      <Card className="w-full max-w-md my-auto max-h-[calc(100vh-2rem)] overflow-y-auto" onClick={(e: React.MouseEvent) => e.stopPropagation()}>
        <CardContent>
          <h2 className="text-xl font-semibold mb-4">{t('printers.editPrinter')}</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-bambu-gray mb-1">{t('printers.name')}</label>
              <input
                type="text"
                required
                className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder={t('printers.modal.myPrinter')}
              />
            </div>
            <div>
              <label className="block text-sm text-bambu-gray mb-1">{t('printers.ipAddress')}</label>
              <input
                type="text"
                required
                pattern="(\d{1,3}(\.\d{1,3}){3}|[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*)"
                className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                value={form.ip_address}
                onChange={(e) => setForm({ ...form, ip_address: e.target.value })}
                placeholder="192.168.1.100 or printer.local"
              />
            </div>
            <div>
              <label className="block text-sm text-bambu-gray mb-1">{t('printers.serialNumber')}</label>
              <input
                type="text"
                disabled
                className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-bambu-gray cursor-not-allowed"
                value={printer.serial_number}
              />
              <p className="text-xs text-bambu-gray mt-1">{t('printers.serialCannotBeChanged')}</p>
            </div>
            <div>
              <label className="block text-sm text-bambu-gray mb-1">{t('printers.accessCode')}</label>
              <input
                type="password"
                className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                value={form.access_code}
                onChange={(e) => setForm({ ...form, access_code: e.target.value })}
                placeholder={t('printers.accessCodePlaceholder')}
              />
            </div>
            <div>
              <label className="block text-sm text-bambu-gray mb-1">{t('printers.model')}</label>
              <select
                className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              >
                <option value="">{t('printers.modal.selectModel')}</option>
                <optgroup label="A1 Series">
                  <option value="A1">A1</option>
                  <option value="A1 Mini">A1 Mini</option>
                </optgroup>
                <optgroup label="A2 Series">
                  <option value="A2L">A2L</option>
                </optgroup>
                <optgroup label="H2 Series">
                  <option value="H2C">H2C</option>
                  <option value="H2D">H2D</option>
                  <option value="H2D Pro">H2D Pro</option>
                  <option value="H2S">H2S</option>
                </optgroup>
                <optgroup label="P Series">
                  <option value="P1P">P1P</option>
                  <option value="P1S">P1S</option>
                  <option value="P2S">P2S</option>
                </optgroup>
                <optgroup label="X1 Series">
                  <option value="X1">X1</option>
                  <option value="X1C">X1 Carbon</option>
                  <option value="X1E">X1E</option>
                </optgroup>
                <optgroup label="X2 Series">
                  <option value="X2D">X2D</option>
                </optgroup>
              </select>
            </div>
            <div>
              <label className="block text-sm text-bambu-gray mb-1">Location / Group</label>
              <input
                type="text"
                className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                value={form.location}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
                placeholder={t('printers.modal.locationPlaceholder')}
              />
              <p className="text-xs text-bambu-gray mt-1">{t('printers.locationHelp')}</p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="edit_auto_archive"
                checked={form.auto_archive}
                onChange={(e) => setForm({ ...form, auto_archive: e.target.checked })}
                className="rounded border-bambu-dark-tertiary bg-bambu-dark text-bambu-green focus:ring-bambu-green"
              />
              <label htmlFor="edit_auto_archive" className="text-sm text-bambu-gray">
                {t('printers.modal.autoArchiveLabel')}
              </label>
            </div>
            {/* Maintenance Mode toggle (#1476) — checkbox is the inverse of
                is_active because the user-facing concept is "is this printer
                in maintenance" not "is it active". */}
            <div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="edit_maintenance_mode"
                  checked={!form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: !e.target.checked })}
                  className="rounded border-bambu-dark-tertiary bg-bambu-dark text-amber-400 focus:ring-amber-400"
                />
                <label htmlFor="edit_maintenance_mode" className="text-sm text-bambu-gray flex items-center gap-1.5">
                  <Wrench className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400" />
                  {t('printers.maintenance.editFieldLabel')}
                </label>
              </div>
              <p className="text-xs text-bambu-gray/70 mt-1 ml-6">
                {t('printers.maintenance.editFieldHelp')}
              </p>
            </div>
            {saveWarning ? (
              <div className="rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-300 dark:border-amber-500/30 p-3 space-y-3">
                <div className="flex items-start gap-2">
                  <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0 text-amber-600 dark:text-amber-400" />
                  <p className="text-sm text-amber-700 dark:text-amber-300">{t('printers.addPreflight.warning')}</p>
                </div>
                <DiagnosticChecklist result={saveWarning} />
                <div className="flex gap-3">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setSaveWarning(null)}
                    className="flex-1"
                  >
                    {t('printers.addPreflight.back')}
                  </Button>
                  <Button
                    type="button"
                    onClick={doSave}
                    className="flex-1"
                    disabled={updateMutation.isPending}
                  >
                    {t('printers.addPreflight.saveAnyway')}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex gap-3 pt-4">
                <Button type="button" variant="secondary" onClick={onClose} className="flex-1">
                  {t('common.cancel')}
                </Button>
                <Button
                  type="submit"
                  className="flex-1"
                  disabled={updateMutation.isPending || checkingSave}
                >
                  {checkingSave
                    ? t('printers.addPreflight.checking')
                    : updateMutation.isPending
                      ? t('common.saving')
                      : t('printers.modal.saveChanges')}
                </Button>
              </div>
            )}
          </form>
        </CardContent>
      </Card>
    </div>
  );
}


export function PlateCheckResultModal({
  printer,
  plateCheckResult,
  plateReferences,
  closePlateCheckModal,
  handleCalibratePlate,
  isCalibrating,
  handleDeleteRef,
  editingRefLabel,
  setEditingRefLabel,
  handleUpdateRefLabel,
  editingRoi,
  setEditingRoi,
  isSavingRoi,
  handleSaveRoi,
}: {
  printer: Printer;
  plateCheckResult: {
    is_empty: boolean;
    confidence: number;
    difference_percent: number;
    message: string;
    debug_image_url?: string;
    needs_calibration: boolean;
    light_warning?: boolean;
    reference_count?: number;
    max_references?: number;
    roi?: { x: number; y: number; w: number; h: number };
  };
  plateReferences: {
    references: Array<{
      index: number;
      label?: string;
      timestamp?: string;
    }>;
    max_references?: number;
  } | null;
  closePlateCheckModal: () => void;
  handleCalibratePlate: (label?: string) => Promise<void>;
  isCalibrating: boolean;
  handleDeleteRef: (index: number) => Promise<void>;
  editingRefLabel: { index: number; label: string } | null;
  setEditingRefLabel: (val: { index: number; label: string } | null) => void;
  handleUpdateRefLabel: (index: number, label: string) => Promise<void>;
  editingRoi: { x: number; y: number; w: number; h: number } | null;
  setEditingRoi: (roi: { x: number; y: number; w: number; h: number } | null) => void;
  isSavingRoi: boolean;
  handleSaveRoi: () => Promise<void>;
}) {
  const { t } = useTranslation();

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={() => closePlateCheckModal()}>
      <div className="bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-xl shadow-2xl max-w-lg w-full" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-bambu-dark-tertiary">
          <div className="flex items-center gap-2">
            {plateCheckResult.needs_calibration ? (
              <ScanSearch className="w-[var(--pc-i5,1.25rem)] h-[var(--pc-i5,1.25rem)] text-blue-500" />
            ) : plateCheckResult.is_empty ? (
              <CheckCircle className="w-[var(--pc-i5,1.25rem)] h-[var(--pc-i5,1.25rem)] text-green-500" />
            ) : (
              <XCircle className="w-[var(--pc-i5,1.25rem)] h-[var(--pc-i5,1.25rem)] text-yellow-500" />
            )}
            <h2 className="text-lg font-semibold text-white">
              Build Plate Check
            </h2>
            {plateCheckResult.reference_count !== undefined && plateCheckResult.max_references && (
              <span className="text-xs text-bambu-gray bg-bambu-dark-tertiary px-2 py-1 rounded">
                {plateCheckResult.reference_count}/{plateCheckResult.max_references} refs
              </span>
            )}
          </div>
          <button
            onClick={() => closePlateCheckModal()}
            className="p-1 text-bambu-gray hover:text-white rounded transition-colors"
          >
            <X className="w-[var(--pc-i5,1.25rem)] h-[var(--pc-i5,1.25rem)]" />
          </button>
        </div>
        <div className="p-4 space-y-4">
          {plateCheckResult.needs_calibration ? (
            <>
              <div className="p-3 rounded-lg bg-blue-100 dark:bg-blue-500/20 border border-blue-300 dark:border-blue-500/50">
                <p className="font-medium text-blue-700 dark:text-blue-400">
                  {t('printers.plateDetection.calibrationRequired')}
                </p>
                <p className="text-sm text-bambu-gray mt-1" dangerouslySetInnerHTML={{ __html: t('printers.plateDetection.calibrationInstructions') }} />
              </div>
              <div className="text-sm text-bambu-gray space-y-2">
                <p>{t('printers.plateDetection.calibrationDescription')}</p>
                <p dangerouslySetInnerHTML={{ __html: t('printers.plateDetection.calibrationTip') }} />
              </div>
            </>
          ) : (
            <>
              <div className={`p-3 rounded-lg ${plateCheckResult.is_empty ? 'bg-green-100 dark:bg-green-500/20 border border-green-300 dark:border-green-500/50' : 'bg-yellow-100 dark:bg-yellow-500/20 border border-yellow-300 dark:border-yellow-500/50'}`}>
                <p className={`font-medium ${plateCheckResult.is_empty ? 'text-green-700 dark:text-green-400' : 'text-yellow-700 dark:text-yellow-400'}`}>
                  {plateCheckResult.is_empty ? t('printers.plateDetection.plateEmpty') : t('printers.plateDetection.objectsDetected')}
                </p>
                <p className="text-sm text-bambu-gray mt-1">
                  {t('printers.plateDetection.confidence')}: {Math.round(plateCheckResult.confidence * 100)}% | {t('printers.plateDetection.difference')}: {plateCheckResult.difference_percent.toFixed(1)}%
                </p>
              </div>
              {plateCheckResult.debug_image_url && (
                <div>
                  <p className="text-sm text-bambu-gray mb-2">{t('printers.plateDetection.analysisPreview')}</p>
                  <img
                    src={plateCheckResult.debug_image_url}
                    alt={t('printers.plateDetection.analysisPreview')}
                    className="w-full rounded-lg border border-bambu-dark-tertiary"
                  />
                  <p className="text-xs text-bambu-gray mt-2">
                    {t('printers.plateDetection.analysisLegend')}
                  </p>
                </div>
              )}
              <p className="text-xs text-bambu-gray">
                {plateCheckResult.message}
              </p>
            </>
          )}

          {/* Saved References Grid */}
          {plateReferences && plateReferences.references.length > 0 && (
            <div className="mt-4">
              <div className="flex items-center gap-2 mb-2">
                <p className="text-sm font-medium text-white shrink-0">
                  {t('printers.plateDetection.savedReferences', { count: plateReferences.references.length, max: plateReferences.max_references })}
                </p>
                <div className="flex-1 h-[2px] bg-bambu-dark-tertiary" />
              </div>
              <div className="grid grid-cols-5 gap-2">
                {plateReferences.references.map((ref) => (
                  <div key={ref.index} className="relative group">
                    <img
                      src={api.getPlateReferenceThumbnailUrl(printer.id, ref.index)}
                      alt={ref.label || `Reference ${ref.index + 1}`}
                      className="w-full aspect-video object-cover rounded border border-bambu-dark-tertiary"
                    />
                    {/* Delete button */}
                    <button
                      onClick={() => handleDeleteRef(ref.index)}
                      className="absolute top-1 right-1 p-0.5 bg-red-500/80 rounded can-hover:opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                      title={t('printers.plateDetection.deleteReference')}
                    >
                      <X className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)] text-white" />
                    </button>
                    {/* Label */}
                    {editingRefLabel?.index === ref.index ? (
                      <input
                        type="text"
                        value={editingRefLabel.label}
                        onChange={(e) => setEditingRefLabel({ ...editingRefLabel, label: e.target.value })}
                        onBlur={() => handleUpdateRefLabel(ref.index, editingRefLabel.label)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleUpdateRefLabel(ref.index, editingRefLabel.label);
                          if (e.key === 'Escape') setEditingRefLabel(null);
                        }}
                        className="w-full mt-1 px-1 py-0.5 text-xs bg-bambu-dark-tertiary border border-bambu-green rounded text-white"
                        autoFocus
                        placeholder={t('printers.plateDetection.labelPlaceholder')}
                      />
                    ) : (
                      <p
                        className="text-xs text-bambu-gray mt-1 truncate cursor-pointer hover:text-white"
                        onClick={() => setEditingRefLabel({ index: ref.index, label: ref.label || '' })}
                        title={ref.label ? t('printers.plateDetection.clickToEdit', { label: ref.label }) : t('printers.plateDetection.clickToAddLabel')}
                      >
                        {ref.label || <span className="italic opacity-50">{t('printers.noLabel')}</span>}
                      </p>
                    )}
                    {/* Timestamp */}
                    <p className="text-[length:var(--pc-t10,10px)] text-bambu-gray/60">
                      {ref.timestamp ? parseUTCDate(ref.timestamp)?.toLocaleDateString() ?? '' : ''}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ROI Editor */}
          {!plateCheckResult.needs_calibration && (
            <div className="mt-4">
              <div className="flex items-center justify-between mb-2">
                <div className="flex min-w-0 flex-1 items-center gap-2">
                  <p className="text-sm font-medium text-white shrink-0">{t('printers.roi.title')}</p>
                  <div className="flex-1 h-[2px] bg-bambu-dark-tertiary" />
                </div>
                {!editingRoi ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setEditingRoi(plateCheckResult.roi || { x: 0.15, y: 0.35, w: 0.70, h: 0.55 })}
                  >
                    <Pencil className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)] mr-1" />
                    {t('common.edit')}
                  </Button>
                ) : (
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setEditingRoi(null)}
                      disabled={isSavingRoi}
                    >
                      {t('common.cancel')}
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleSaveRoi}
                      disabled={isSavingRoi}
                    >
                      {isSavingRoi ? <Loader2 className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)] animate-spin" /> : t('common.save')}
                    </Button>
                  </div>
                )}
              </div>
              {editingRoi ? (
                <div className="space-y-3 bg-bambu-dark-tertiary/50 p-3 rounded-lg">
                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs text-bambu-gray">{t('printers.roi.xStart')}</label>
                      <input
                        type="range"
                        min="0"
                        max="0.9"
                        step="0.01"
                        value={editingRoi.x}
                        onChange={(e) => setEditingRoi({ ...editingRoi, x: parseFloat(e.target.value) })}
                        className="w-full h-1.5 bg-bambu-dark-tertiary rounded-lg cursor-pointer accent-green-500"
                      />
                      <span className="text-xs text-bambu-gray">{Math.round(editingRoi.x * 100)}%</span>
                    </div>
                    <div>
                      <label className="text-xs text-bambu-gray">{t('printers.roi.yStart')}</label>
                      <input
                        type="range"
                        min="0"
                        max="0.9"
                        step="0.01"
                        value={editingRoi.y}
                        onChange={(e) => setEditingRoi({ ...editingRoi, y: parseFloat(e.target.value) })}
                        className="w-full h-1.5 bg-bambu-dark-tertiary rounded-lg cursor-pointer accent-green-500"
                      />
                      <span className="text-xs text-bambu-gray">{Math.round(editingRoi.y * 100)}%</span>
                    </div>
                    <div>
                      <label className="text-xs text-bambu-gray">{t('printers.width')}</label>
                      <input
                        type="range"
                        min="0.1"
                        max="1"
                        step="0.01"
                        value={editingRoi.w}
                        onChange={(e) => setEditingRoi({ ...editingRoi, w: parseFloat(e.target.value) })}
                        className="w-full h-1.5 bg-bambu-dark-tertiary rounded-lg cursor-pointer accent-green-500"
                      />
                      <span className="text-xs text-bambu-gray">{Math.round(editingRoi.w * 100)}%</span>
                    </div>
                    <div>
                      <label className="text-xs text-bambu-gray">{t('printers.height')}</label>
                      <input
                        type="range"
                        min="0.1"
                        max="1"
                        step="0.01"
                        value={editingRoi.h}
                        onChange={(e) => setEditingRoi({ ...editingRoi, h: parseFloat(e.target.value) })}
                        className="w-full h-1.5 bg-bambu-dark-tertiary rounded-lg cursor-pointer accent-green-500"
                      />
                      <span className="text-xs text-bambu-gray">{Math.round(editingRoi.h * 100)}%</span>
                    </div>
                  </div>
                  <p className="text-xs text-bambu-gray">
                    {t('printers.roi.instruction')}
                  </p>
                </div>
              ) : (
                <p className="text-xs text-bambu-gray">
                  Current: X={Math.round((plateCheckResult.roi?.x || 0.15) * 100)}%, Y={Math.round((plateCheckResult.roi?.y || 0.35) * 100)}%,
                  W={Math.round((plateCheckResult.roi?.w || 0.70) * 100)}%, H={Math.round((plateCheckResult.roi?.h || 0.55) * 100)}%
                </p>
              )}
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 p-4">
          {plateCheckResult.needs_calibration ? (
            <>
              <Button variant="ghost" onClick={() => closePlateCheckModal()}>
                {t('common.cancel')}
              </Button>
              <Button
                onClick={() => handleCalibratePlate()}
                disabled={isCalibrating}
              >
                {isCalibrating ? (
                  <>
                    <Loader2 className="w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)] mr-2 animate-spin" />
                    Calibrating...
                  </>
                ) : (
                  'Calibrate Empty Plate'
                )}
              </Button>
            </>
          ) : (
            <>
              <Button variant="ghost" onClick={() => handleCalibratePlate()} disabled={isCalibrating}>
                {isCalibrating ? 'Adding...' : `Add Reference (${plateReferences?.references.length || 0}/${plateReferences?.max_references || 5})`}
              </Button>
              <Button onClick={() => closePlateCheckModal()}>
                Close
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function AmsDryingPopover({
  amsData,
  dryingPopoverAmsId,
  dryingPopoverPos,
  dryingPopoverModuleType,
  dryingFilament,
  setDryingFilament,
  dryingPresets,
  dryingTemp,
  setDryingTemp,
  dryingDuration,
  setDryingDuration,
  dryingRotateTray,
  setDryingRotateTray,
  dryingStartMode,
  setDryingStartMode,
  dryingDelayMinutes,
  setDryingDelayMinutes,
  dryingStartAt,
  setDryingStartAt,
  dryingBackdropSkipCloseRef,
  dryingAtTimeInputRef,
  onClose,
  onStartDrying,
  onScheduleDrying,
  isStarting,
  isScheduling,
}: {
  amsData: AMSUnit[];
  dryingPopoverAmsId: number;
  dryingPopoverPos: PopoverPosition;
  dryingPopoverModuleType?: string;
  dryingFilament: string;
  setDryingFilament: (val: string) => void;
  dryingPresets?: Record<string, DryingPreset>;
  dryingTemp: number;
  setDryingTemp: (val: number) => void;
  dryingDuration: number;
  setDryingDuration: (val: number) => void;
  dryingRotateTray: boolean;
  setDryingRotateTray: React.Dispatch<React.SetStateAction<boolean>>;
  dryingStartMode: DryingStartMode;
  setDryingStartMode: (val: DryingStartMode) => void;
  dryingDelayMinutes: number;
  setDryingDelayMinutes: (val: number) => void;
  dryingStartAt: string;
  setDryingStartAt: (val: string) => void;
  dryingBackdropSkipCloseRef: React.MutableRefObject<boolean>;
  dryingAtTimeInputRef: React.RefObject<HTMLInputElement | null>;
  onClose: () => void;
  onStartDrying: (params: { amsId: number; temp: number; duration: number; filament: string; rotateTray: boolean }) => void;
  onScheduleDrying: (params: { amsId: number; temp: number; duration: number; filament: string; rotateTray: boolean; startAfter: string }) => void;
  isStarting: boolean;
  isScheduling: boolean;
}) {
  const { t } = useTranslation();
  const maxTemp = dryingPopoverModuleType === 'n3s' ? 85 : 65;
  const sliderMin = 35;
  const sliderMax = maxTemp + 10;
  const presets = dryingPresets ?? DRYING_PRESETS;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-[100]"
        data-testid="drying-popover-backdrop"
        onMouseDown={() => {
          dryingBackdropSkipCloseRef.current =
            dryingAtTimeInputRef.current !== null &&
            document.activeElement === dryingAtTimeInputRef.current;
        }}
        onClick={() => {
          if (dryingBackdropSkipCloseRef.current) {
            dryingBackdropSkipCloseRef.current = false;
            return;
          }
          onClose();
        }}
      />
      {/* An 'above' popover is anchored by its bottom edge */}
      <div
        className="fixed z-[101] flex flex-col w-[240px] bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-xl shadow-2xl overflow-hidden"
        style={{
          left: dryingPopoverPos.left,
          ...(dryingPopoverPos.placement === 'above'
            ? {
                bottom: `calc(100dvh - ${dryingPopoverPos.anchorY}px)`,
                maxHeight: `${dryingPopoverPos.anchorY - 8}px`,
              }
            : {
                top: dryingPopoverPos.top,
                maxHeight: `calc(100dvh - ${dryingPopoverPos.top}px - 8px)`,
              }),
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="shrink-0 flex items-center justify-center gap-2 px-3 py-2.5">
          <Flame className="w-[var(--pc-i35,0.875rem)] h-[var(--pc-i35,0.875rem)] text-bambu-green" />
          <span className="text-sm text-white font-medium text-center">{t('printers.drying.start')}</span>
        </div>
        <div className="shrink-0 h-px bg-bambu-dark-tertiary" />
        {/* Body */}
        <div className="px-3 py-2.5 space-y-2.5 overflow-y-auto min-h-0">
          {/* Filament type select */}
          <div>
            <label className="text-[length:var(--pc-t10,10px)] text-white/70 font-medium mb-1 block">{t('printers.filaments')}</label>
            <ToolbarDropdown
              value={dryingFilament}
              options={Object.keys(presets).map(fil => ({ value: fil, label: fil }))}
              onChange={fil => {
                setDryingFilament(fil);
                const preset = presets[fil];
                if (preset) {
                  const key = dryingPopoverModuleType === 'n3s' ? 'n3s' : 'n3f';
                  setDryingTemp(preset[key]);
                  setDryingDuration(dryingPopoverModuleType === 'n3s' ? preset.n3s_hours : preset.n3f_hours);
                }
              }}
              fullWidth
            />
          </div>
          {/* Temperature */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[length:var(--pc-t10,10px)] text-white/70 font-medium">{t('printers.drying.temperature')}</label>
              <div className="flex items-center gap-1">
                <NumberInput
                  min={45}
                  max={maxTemp}
                  value={dryingTemp}
                  onChange={setDryingTemp}
                  fallback={45}
                  className="w-12 px-1 py-0.5 bg-bambu-dark border border-bambu-dark-tertiary rounded text-white text-[length:var(--pc-t11,11px)] text-center focus:outline-none focus:border-bambu-green [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                />
                <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">°C</span>
              </div>
            </div>
            <input
              type="range"
              min={sliderMin}
              max={sliderMax}
              value={dryingTemp}
              onChange={e => setDryingTemp(Math.min(maxTemp, Math.max(45, Number(e.target.value))))}
              className="w-full h-1 accent-bambu-green cursor-pointer"
            />
            <div className="flex justify-between text-[length:var(--pc-t9,9px)] text-bambu-gray/50 mt-0.5">
              <span>45°C</span>
              <span>{maxTemp}°C</span>
            </div>
          </div>
          {/* Duration */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-[length:var(--pc-t10,10px)] text-white/70 font-medium">{t('printers.drying.duration')}</label>
              <div className="flex items-center gap-1">
                <NumberInput
                  min={1}
                  max={24}
                  value={dryingDuration}
                  onChange={setDryingDuration}
                  fallback={1}
                  className="w-10 px-1 py-0.5 bg-bambu-dark border border-bambu-dark-tertiary rounded text-white text-[length:var(--pc-t11,11px)] text-center focus:outline-none focus:border-bambu-green [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                />
                <span className="text-[length:var(--pc-t10,10px)] text-bambu-gray">{t('printers.drying.hours')}</span>
              </div>
            </div>
            <input
              type="range"
              min={1}
              max={24}
              value={dryingDuration}
              onChange={e => setDryingDuration(Number(e.target.value))}
              className="w-full h-1 accent-bambu-green cursor-pointer"
            />
            <div className="flex justify-between text-[length:var(--pc-t9,9px)] text-bambu-gray/50 mt-0.5">
              <span>1h</span>
              <span>24h</span>
            </div>
          </div>
          {/* Rotate tray */}
          {(() => {
            const targetAms = amsData.find(a => a.id === dryingPopoverAmsId);
            const trayLoadedInThisAms = (targetAms?.tray ?? []).some(
              tray => tray.state === 11,
            );
            const rotateChecked = dryingRotateTray && !trayLoadedInThisAms;
            return (
              <button
                type="button"
                onClick={() => setDryingRotateTray(enabled => !enabled)}
                aria-pressed={rotateChecked}
                disabled={trayLoadedInThisAms}
                title={trayLoadedInThisAms ? t('printers.drying.rotateUnavailableReason') : undefined}
                className={`h-8 w-full rounded-lg border px-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  rotateChecked
                    ? 'bg-bambu-green border-bambu-green text-white'
                    : 'bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary disabled:hover:bg-bambu-dark'
                }`}
              >
                {t('printers.drying.rotateTray')}
              </button>
            );
          })()}
          {/* Start mode */}
          <div>
            <label className="text-[10px] text-white/70 font-medium mb-1 block">{t('printers.drying.startMode')}</label>
            <div className="grid grid-cols-3 gap-1">
              {(['now', 'delay', 'at_time'] as const).map(mode => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setDryingStartMode(mode)}
                  className={`py-1 rounded-lg border text-[10px] font-medium transition-colors ${
                    dryingStartMode === mode
                      ? 'bg-bambu-green border-bambu-green text-white'
                      : 'bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary'
                  }`}
                >
                  {t(mode === 'now' ? 'printers.drying.modeNow' : mode === 'delay' ? 'printers.drying.modeDelay' : 'printers.drying.modeAtTime')}
                </button>
              ))}
            </div>
            {dryingStartMode === 'delay' && (
              <div className="mt-1.5 grid grid-cols-4 gap-1">
                {DRYING_DELAY_OPTIONS.map(min => (
                  <button
                    key={min}
                    type="button"
                    aria-pressed={dryingDelayMinutes === min}
                    onClick={() => setDryingDelayMinutes(min)}
                    className={`py-1 rounded-lg border text-[10px] font-medium transition-colors ${
                      dryingDelayMinutes === min
                        ? 'bg-bambu-green border-bambu-green text-white'
                        : 'bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary'
                    }`}
                  >
                    {formatDurationFromHours(min / 60)}
                  </button>
                ))}
              </div>
            )}
            {dryingStartMode === 'at_time' && (
              <input
                ref={dryingAtTimeInputRef}
                type="datetime-local"
                data-testid="drying-start-at"
                value={dryingStartAt}
                onChange={e => setDryingStartAt(e.target.value)}
                className="mt-1.5 w-full px-2 py-1 bg-bambu-dark border border-bambu-dark-tertiary rounded text-white text-[11px] focus:outline-none focus:border-bambu-green [color-scheme:dark]"
              />
            )}
          </div>
        </div>
        <div className="shrink-0 h-px bg-bambu-dark-tertiary" />
        {/* Footer */}
        <div className="shrink-0 px-3 pt-2.5 pb-3">
          <button
            onClick={() => {
              const targetAms = amsData.find(a => a.id === dryingPopoverAmsId);
              const trayLoadedInThisAms = (targetAms?.tray ?? []).some(
                tray => tray.state === 11,
              );
              const rotate = dryingRotateTray && !trayLoadedInThisAms;
              if (dryingStartMode === 'now') {
                onStartDrying({
                  amsId: dryingPopoverAmsId,
                  temp: dryingTemp,
                  duration: dryingDuration,
                  filament: dryingFilament,
                  rotateTray: rotate,
                });
              } else {
                const startAfter = computeStartAfter(dryingStartMode, dryingDelayMinutes, dryingStartAt);
                if (startAfter) {
                  onScheduleDrying({
                    amsId: dryingPopoverAmsId,
                    temp: dryingTemp,
                    duration: dryingDuration,
                    filament: dryingFilament,
                    rotateTray: rotate,
                    startAfter,
                  });
                }
              }
            }}
            disabled={isStarting || isScheduling || (dryingStartMode === 'at_time' && !dryingStartAt)}
            data-testid="drying-start-confirm"
            className="w-full py-1.5 bg-bambu-green hover:bg-bambu-green/80 text-white text-xs font-medium rounded-lg transition-colors disabled:opacity-50"
          >
            {dryingStartMode === 'now'
              ? (isStarting ? t('printers.drying.startingDrying') : t('printers.drying.start'))
              : t('printers.drying.schedule')}
          </button>
        </div>
      </div>
      {/* Anchor arrow */}
      <div
        className="fixed z-[102] w-2.5 h-2.5 rotate-45 bg-bambu-dark-secondary border-bambu-dark-tertiary pointer-events-none"
        style={{
          left: dryingPopoverPos.left + dryingPopoverPos.arrowLeft - 5,
          top: dryingPopoverPos.anchorY - 5,
          ...(dryingPopoverPos.placement === 'above'
            ? { borderRightWidth: 1, borderBottomWidth: 1 }
            : { borderLeftWidth: 1, borderTopWidth: 1 }),
        }}
      />
    </>
  );
}

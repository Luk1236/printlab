/**
 * Die beiden Dialoge der Druckerkarte: Firmware-Aktualisierung und Bearbeiten.
 *
 * Eigene Datei, weil die Karte sonst weiter wuchs; die Dialoge brauchen von ihr nur die Datentypen. Wer einen
 * Dialog ändert, muss nicht mehr durch die 5 000 Zeilen der Karte scrollen.
 */

import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertCircle, AlertTriangle, Box, CheckCircle, Download, Loader2, Wrench } from 'lucide-react';
import { api, firmwareApi } from '../api/client';
import type {
  FirmwareUpdateInfo,
  FirmwareUploadStatus,
  Printer,
  PrinterCreate,
  PrinterDiagnosticResult,
} from '../api/client';
import { Card, CardContent } from '../components/Card';
import { Button } from '../components/Button';
import { DiagnosticChecklist } from '../components/ConnectionDiagnostic';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { compareFwVersions } from '../utils/firmwareVersion';

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

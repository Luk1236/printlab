import React from 'react';
import { useTranslation } from 'react-i18next';
import type { UseMutationResult } from '@tanstack/react-query';
import {
  ArrowUpCircle,
  RefreshCw,
  Loader2,
  ExternalLink,
  Download,
  AlertTriangle,
  CheckCircle2,
  HelpCircle,
} from 'lucide-react';
import { api, type Settings, type VersionInfo, type UpdateCheckResponse, type UpdateStatusResponse } from '../../api/client';
import { Card, CardHeader, CardContent } from '../Card';
import { Button } from '../Button';
import { CopyButton } from '../CopyButton';
import { UpdateRestartWatcher } from '../UpdateRestartWatcher';
import { UpdateBackupsCard } from '../UpdateBackupsCard';
import { helpLink, HELP_ANCHORS } from '../../utils/docsLinks';
import { useAuth } from '../../contexts/AuthContext';

export interface UpdatesSettingsSectionProps {
  localSettings: Settings;
  updateSetting: (key: keyof Settings, value: unknown) => void;
  versionInfo?: VersionInfo;
  updateCheck?: UpdateCheckResponse;
  refetchUpdateCheck: () => void;
  isCheckingUpdate: boolean;
  updateStatus?: UpdateStatusResponse;
  refetchUpdateStatus: () => void;
  applyUpdateMutation: UseMutationResult<unknown, Error, void, unknown>;
  setShowReleaseNotes: (show: boolean) => void;
}

export function UpdatesSettingsSection({
  localSettings,
  updateSetting,
  versionInfo,
  updateCheck,
  refetchUpdateCheck,
  isCheckingUpdate,
  updateStatus,
  refetchUpdateStatus,
  applyUpdateMutation,
  setShowReleaseNotes,
}: UpdatesSettingsSectionProps) {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();

  const composeDir = localSettings?.docker_compose_dir || updateCheck?.compose_dir_detected;
  const composeUpdateCommand = composeDir
    ? `cd ${/\s/.test(composeDir) ? `"${composeDir}"` : composeDir} && docker compose pull && docker compose up -d`
    : 'docker compose pull && docker compose up -d';

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-bambu-green/10 text-bambu-green shrink-0">
              <ArrowUpCircle className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">{t('settings.updates', 'Updates & Version')}</h2>
              <p className="text-sm text-bambu-gray">
                {t('settings.updatesDescription', 'Software-Aktualisierungen, Versionsstand und Update-Kanäle')}
              </p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Printer Firmware Section */}
          <div>
            <p className="text-xs font-medium text-bambu-gray uppercase tracking-wider mb-3">
              {t('settings.printerFirmware')}
            </p>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-white">{t('settings.checkPrinterFirmware')}</p>
                <p className="text-sm text-bambu-gray">
                  {t('settings.checkFirmwareDescription')}
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.check_printer_firmware ?? true}
                  onChange={(e) => updateSetting('check_printer_firmware', e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
              </label>
            </div>
          </div>

          {/* Software Section */}
          <div className="border-t border-bambu-dark-tertiary pt-4 space-y-4">
            <p className="text-xs font-medium text-bambu-gray uppercase tracking-wider">
              {t('settings.bambuddySoftware')}
            </p>

            <div className="flex items-center justify-between">
              <div>
                <p className="text-white">{t('settings.checkForUpdatesLabel')}</p>
                <p className="text-sm text-bambu-gray">
                  {t('settings.autoCheckDescription')}
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.check_updates}
                  onChange={(e) => updateSetting('check_updates', e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
              </label>
            </div>

            <div className={`flex items-center justify-between ${!localSettings.check_updates ? 'opacity-50' : ''}`}>
              <div>
                <p className="text-white">{t('settings.includeBetaUpdates')}</p>
                <p className="text-sm text-bambu-gray">
                  {t('settings.includeBetaUpdatesDesc')}
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.include_beta_updates ?? false}
                  onChange={(e) => updateSetting('include_beta_updates', e.target.checked)}
                  disabled={!localSettings.check_updates}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
              </label>
            </div>

            <div className="p-4 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <p className="text-sm font-semibold text-white">{t('settings.currentVersion')}</p>
                  <p className="text-sm font-mono text-bambu-green font-medium">v{versionInfo?.version || '...'}</p>
                </div>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => refetchUpdateCheck()}
                  disabled={isCheckingUpdate}
                >
                  {isCheckingUpdate ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <RefreshCw className="w-4 h-4" />
                  )}
                  {t('settings.checkNow')}
                </Button>
              </div>

              {updateCheck?.update_available ? (
                <div className="mt-4 p-4 bg-bambu-green/10 border border-bambu-green/30 rounded-xl">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-bambu-green font-semibold">
                        Update verfügbar: v{updateCheck.latest_version}
                      </p>
                      {updateCheck.release_name && updateCheck.release_name !== updateCheck.latest_version && (
                        <p className="text-sm text-bambu-gray mt-1">{updateCheck.release_name}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {updateCheck.release_notes && (
                        <button
                          onClick={() => setShowReleaseNotes(true)}
                          className="text-bambu-gray hover:text-white transition-colors text-sm underline"
                        >
                          {t('settings.releaseNotes')}
                        </button>
                      )}
                      {updateCheck.release_url && (
                        <a
                          href={updateCheck.release_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-bambu-gray hover:text-white transition-colors"
                          title={t('settings.viewReleaseOnGitHub')}
                        >
                          <ExternalLink className="w-4 h-4" />
                        </a>
                      )}
                    </div>
                  </div>

                  {updateStatus?.signature_enforced !== undefined && (
                    <p
                      className={`mt-3 text-xs ${updateStatus.signature_enforced ? 'text-bambu-green' : 'text-bambu-gray'}`}
                      data-testid="update-signature-hint"
                    >
                      {updateStatus.signature_enforced ? t('settings.updateSignatureOn') : t('settings.updateSignatureOff')}
                    </p>
                  )}
                  <div className="mt-3">
                    <UpdateBackupsCard canRestore={hasPermission('settings:update')} />
                  </div>
                  {updateStatus?.rolled_back && (
                    <div className="mt-3 p-2 bg-yellow-500/20 rounded text-sm text-yellow-700 dark:text-yellow-400 flex items-start justify-between gap-3">
                      <span>
                        {t('settings.updateRolledBack')}
                        {updateStatus.rolled_back.reason ? ` (${updateStatus.rolled_back.reason})` : ''}
                      </span>
                      <button
                        type="button"
                        className="shrink-0 underline"
                        onClick={() => api.dismissRollbackNotice().then(() => refetchUpdateStatus())}
                      >
                        {t('settings.updateRolledBackDismiss')}
                      </button>
                    </div>
                  )}
                  {updateStatus?.status === 'downloading' || updateStatus?.status === 'installing' ? (
                    <div className="mt-3">
                      <div className="flex items-center gap-2 text-sm text-bambu-gray">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>{updateStatus.message}</span>
                      </div>
                      <div className="mt-2 w-full bg-bambu-dark-tertiary rounded-full h-2">
                        <div
                          className="bg-bambu-green h-2 rounded-full transition-all duration-300"
                          style={{ width: `${updateStatus.progress}%` }}
                        />
                      </div>
                    </div>
                  ) : updateStatus?.status === 'complete' && updateStatus.restarting ? (
                    <UpdateRestartWatcher currentVersion={updateCheck?.current_version} />
                  ) : updateStatus?.status === 'complete' ? (
                    <div className="mt-3 p-2 bg-bambu-green/20 rounded text-sm text-bambu-green">
                      {updateStatus.message}
                    </div>
                  ) : updateStatus?.status === 'error' ? (
                    <div className="mt-3 p-2 bg-red-100 dark:bg-red-500/20 rounded text-sm text-red-700 dark:text-red-400">
                      {updateStatus.error || updateStatus.message}
                    </div>
                  ) : updateCheck?.is_ha_addon ? (
                    <div className="mt-3 p-3 bg-bambu-dark-tertiary rounded-lg">
                      <p className="text-sm text-bambu-gray">
                        {t('settings.updateViaHomeAssistant')}
                      </p>
                    </div>
                  ) : updateCheck?.is_docker ? (
                    <div className="mt-3 p-3 bg-bambu-dark-tertiary rounded-lg">
                      <p className="text-sm text-bambu-gray mb-2">
                        {t('settings.updateViaDocker')}
                      </p>
                      <div className="flex items-start gap-1">
                        <code className="flex-1 block text-xs bg-bambu-dark p-2 rounded text-bambu-green font-mono break-all select-all">
                          {composeUpdateCommand}
                        </code>
                        <CopyButton
                          value={composeUpdateCommand}
                          titleKey="settings.copyUpdateCommand"
                          copiedTitleKey="printers.copied"
                          className="ml-0 p-2 rounded hover:bg-bambu-dark text-bambu-gray hover:text-white transition-colors flex-shrink-0"
                          iconClassName="w-4 h-4"
                        />
                      </div>
                      <label className="block mt-3">
                        <span className="block text-xs text-bambu-gray mb-1">
                          {t('settings.composeDirectory')}
                        </span>
                        <input
                          type="text"
                          value={localSettings?.docker_compose_dir ?? ''}
                          onChange={(e) => updateSetting('docker_compose_dir', e.target.value)}
                          placeholder={updateCheck?.compose_dir_detected || '/opt/bambuddy'}
                          className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded text-sm text-white font-mono placeholder:text-bambu-gray/60 focus:outline-none focus:border-bambu-green"
                        />
                        <span className="block text-xs text-bambu-gray mt-1">
                          {t('settings.composeDirectoryHint')}
                        </span>
                      </label>
                    </div>
                  ) : updateCheck?.update_method === 'windows_installer' ? (
                    <div className="mt-3 p-3 bg-bambu-dark-tertiary rounded-lg">
                      <p className="text-sm text-bambu-gray mb-3">
                        {t('settings.updateViaWindowsInstaller')}
                      </p>
                      <a
                        href={updateCheck.installer_download_url || updateCheck.release_url || `https://github.com/Luk1236/printlab/releases/tag/v${updateCheck.latest_version}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center justify-center font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-bambu-dark disabled:opacity-50 bg-bambu-green hover:bg-bambu-green-light text-white focus:ring-bambu-green px-4 py-2 text-sm gap-2 min-h-[44px] md:min-h-0"
                      >
                        <Download className="w-4 h-4" />
                        {t('settings.downloadWindowsInstaller', { version: updateCheck.latest_version })}
                      </a>
                    </div>
                  ) : (
                    <Button
                      className="mt-3"
                      onClick={() => applyUpdateMutation.mutate()}
                      disabled={applyUpdateMutation.isPending}
                    >
                      {applyUpdateMutation.isPending ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )}
                      {t('settings.installUpdate')}
                    </Button>
                  )}
                </div>
              ) : updateCheck?.error ? (
                <div className="mt-2 p-2 bg-red-50 dark:bg-red-500/10 border border-red-300 dark:border-red-500/30 rounded text-sm text-red-700 dark:text-red-400">
                  {t('settings.failedToCheckUpdates', { error: updateCheck.error })}
                </div>
              ) : updateCheck && !updateCheck.update_available ? (
                <p className="mt-2 text-sm text-bambu-gray">
                  {t('settings.latestVersionRunning')}
                </p>
              ) : null}
            </div>
          </div>

          {/* Announcements Configuration */}
          <div className="border-t border-bambu-dark-tertiary pt-4 space-y-4">
            <p className="text-xs font-medium text-bambu-gray uppercase tracking-wider">{t('announcements.title')}</p>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-white">{t('settings.announcementsEnabled')}</p>
                <p className="text-sm text-bambu-gray">
                  {t('settings.announcementsEnabledDesc')}{' '}
                  <a
                    href={helpLink(HELP_ANCHORS.announcements)}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-bambu-green hover:underline"
                  >
                    {t('settings.announcementsLearnMore')}
                  </a>
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.announcements_enabled ?? true}
                  onChange={(e) => updateSetting('announcements_enabled', e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
              </label>
            </div>
            <div className={`flex items-center justify-between ${localSettings.announcements_enabled === false ? 'opacity-50' : ''}`}>
              <div>
                <p className="text-white">{t('settings.announcementsAllUsers')}</p>
                <p className="text-sm text-bambu-gray">
                  {t('settings.announcementsAllUsersDesc')}
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.announcements_all_users ?? false}
                  onChange={(e) => updateSetting('announcements_all_users', e.target.checked)}
                  disabled={localSettings.announcements_enabled === false}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
              </label>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

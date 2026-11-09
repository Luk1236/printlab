import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Sliders,
  Palette,
  DollarSign,
  Video,
  HardDrive,
  LayoutGrid,
  Globe,
  ChevronDown,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Loader2,
  RefreshCw,
  Trash2,
  Calendar,
  FileText,
  Database,
  ArrowRight,
  Camera,
} from 'lucide-react';

import {
  api,
  type AppSettings,
  type Printer,
} from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../contexts/ToastContext';
import {
  useTheme,
  type ThemeStyle,
  type DarkBackground,
  type LightBackground,
  type ThemeAccent,
} from '../../contexts/ThemeContext';
import { availableLanguages } from '../../i18n';
import { defaultNavItems, getDefaultView, setDefaultView as setDefaultViewStorage } from '../Layout';
import { getCurrencySymbol, SUPPORTED_CURRENCIES } from '../../utils/currency';
import { Card, CardHeader, CardContent } from '../Card';
import { Button } from '../Button';
import { NumberInput } from '../NumberInput';
import { ConfirmModal } from '../ConfirmModal';
import { ExternalLinksSettings } from '../ExternalLinksSettings';
import type { SettingsTabType } from './SettingsNavRail';

export type GeneralSubTab = 'basic' | 'appearance' | 'costs' | 'camera' | 'storage' | 'all';

const ANCHOR_SUBTAB_MAP: Record<string, GeneralSubTab> = {
  'card-general': 'basic',
  'card-appearance': 'appearance',
  'card-sidebar-links': 'appearance',
  'card-cost': 'costs',
  'card-camera': 'camera',
  'card-finish-photo': 'camera',
  'card-filemanager': 'storage',
  'card-archive': 'storage',
  'card-data': 'storage',
};

const STORAGE_CATEGORY_COLORS: Record<string, string> = {
  database: 'bg-blue-600',
  library_files: 'bg-green-500',
  library_thumbnails: 'bg-teal-500',
  library_other: 'bg-emerald-700',
  archive_timelapses: 'bg-red-500',
  archive_thumbnails: 'bg-amber-500',
  archive_files: 'bg-sky-500',
  virtual_printer_uploads: 'bg-purple-500',
  virtual_printer_upload_cache: 'bg-fuchsia-500',
  virtual_printer_certs: 'bg-violet-500',
  virtual_printer_other: 'bg-purple-700',
  downloads: 'bg-cyan-500',
  plate_calibration: 'bg-lime-500',
  logs: 'bg-orange-500',
  other_data: 'bg-yellow-500',
};

const STORAGE_FALLBACK_COLORS = [
  'bg-blue-500',
  'bg-green-500',
  'bg-yellow-500',
  'bg-red-500',
  'bg-orange-500',
  'bg-teal-500',
  'bg-cyan-500',
  'bg-purple-500',
];

const getStorageColor = (key: string, index: number) =>
  STORAGE_CATEGORY_COLORS[key] || STORAGE_FALLBACK_COLORS[index % STORAGE_FALLBACK_COLORS.length];

export interface GeneralSettingsSectionProps {
  localSettings: AppSettings;
  updateSetting: <K extends keyof AppSettings>(key: K, value: AppSettings[K]) => void;
  printers?: Printer[];
  onTabChange?: (tab: SettingsTabType) => void;
  initialSubTab?: GeneralSubTab;
}

export function GeneralSettingsSection({
  localSettings,
  updateSetting,
  printers,
  onTabChange,
  initialSubTab,
}: GeneralSettingsSectionProps) {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { authEnabled, hasPermission, isAdmin } = useAuth();

  const {
    mode,
    setMode,
    resolvedMode,
    darkBackground,
    setDarkBackground,
    darkAccent,
    setDarkAccent,
    darkStyle,
    setDarkStyle,
    lightBackground,
    setLightBackground,
    lightAccent,
    setLightAccent,
    lightStyle,
    setLightStyle,
    progressInTitle,
    setProgressInTitle,
  } = useTheme();

  // Subtab resolution: URL query param > prop > 'basic'
  const currentSubParam = searchParams.get('sub') as GeneralSubTab | null;
  const validSubTabs: GeneralSubTab[] = ['basic', 'appearance', 'costs', 'camera', 'storage', 'all'];
  const [activeSubTab, setActiveSubTab] = useState<GeneralSubTab>(() => {
    if (currentSubParam && validSubTabs.includes(currentSubParam)) {
      return currentSubParam;
    }
    return initialSubTab || 'basic';
  });

  const handleSubTabChange = (tab: GeneralSubTab) => {
    setActiveSubTab(tab);
    const newParams = new URLSearchParams(searchParams);
    if (tab === 'basic') {
      newParams.delete('sub');
    } else {
      newParams.set('sub', tab);
    }
    setSearchParams(newParams, { replace: true });
  };

  // Anchor jump handling
  useEffect(() => {
    const anchor = location.hash.replace('#', '');
    if (!anchor) return;
    const targetSubTab = ANCHOR_SUBTAB_MAP[anchor];
    if (targetSubTab && activeSubTab !== targetSubTab && activeSubTab !== 'all') {
      setActiveSubTab(targetSubTab);
    }
    const timer = window.setTimeout(() => {
      const el = document.getElementById(anchor);
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        el.classList.add('ring-2', 'ring-bambu-green');
        window.setTimeout(() => el.classList.remove('ring-2', 'ring-bambu-green'), 1500);
      }
    }, 120);
    return () => clearTimeout(timer);
  }, [location.hash]);

  // Default start view state
  const [defaultView, setDefaultViewState] = useState(() => getDefaultView());
  const handleDefaultViewChange = (to: string) => {
    setDefaultViewState(to);
    setDefaultViewStorage(to);
    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
  };

  // FFmpeg check
  const { data: ffmpegStatus } = useQuery({
    queryKey: ['ffmpeg-status'],
    queryFn: api.checkFfmpeg,
    staleTime: 60 * 1000,
  });

  // Archive purge settings
  const canPurgeArchives = !authEnabled || hasPermission('archives:purge');
  const { data: archivePurgeSettings } = useQuery({
    queryKey: ['archive-purge-settings'],
    queryFn: () => api.getArchivePurgeSettings(),
    enabled: canPurgeArchives,
  });

  const updateArchivePurgeMutation = useMutation({
    mutationFn: (body: { enabled: boolean; days: number; purge_stats: boolean }) =>
      api.updateArchivePurgeSettings(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['archive-purge-settings'] });
      showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
    },
    onError: (err: Error) => showToast(err.message || 'Fehler beim Speichern der Archiv-Bereinigung', 'error'),
  });

  const saveArchivePurgeSettings = (patch: Partial<{ enabled: boolean; days: number; purge_stats: boolean }>) => {
    if (!archivePurgeSettings) return;
    updateArchivePurgeMutation.mutate({
      enabled: archivePurgeSettings.enabled,
      days: archivePurgeSettings.days,
      purge_stats: archivePurgeSettings.purge_stats,
      ...patch,
    });
  };

  // Trash settings
  const canPurge = !authEnabled || hasPermission('library:purge');
  const { data: trashSettings } = useQuery({
    queryKey: ['library-trash-settings'],
    queryFn: () => api.getLibraryTrashSettings(),
    enabled: canPurge,
  });

  const updateTrashMutation = useMutation({
    mutationFn: (body: {
      retention_days: number;
      auto_purge_enabled: boolean;
      auto_purge_days: number;
      auto_purge_include_never_printed: boolean;
    }) => api.updateLibraryTrashSettings(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['library-trash-settings'] });
      showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
    },
    onError: (err: Error) => showToast(err.message || 'Fehler beim Speichern der Papierkorb-Regeln', 'error'),
  });

  const saveTrashSettings = (patch: Partial<{
    retention_days: number;
    auto_purge_enabled: boolean;
    auto_purge_days: number;
    auto_purge_include_never_printed: boolean;
  }>) => {
    if (!trashSettings) return;
    updateTrashMutation.mutate({
      retention_days: trashSettings.retention_days,
      auto_purge_enabled: trashSettings.auto_purge_enabled,
      auto_purge_days: trashSettings.auto_purge_days,
      auto_purge_include_never_printed: trashSettings.auto_purge_include_never_printed,
      ...patch,
    });
  };

  // Camera management
  const [localCameraUrls, setLocalCameraUrls] = useState<Record<number, string>>({});
  const [localSnapshotUrls, setLocalSnapshotUrls] = useState<Record<number, string>>({});
  const [extCameraTestLoading, setExtCameraTestLoading] = useState<Record<number, boolean>>({});
  const [extCameraTestResults, setExtCameraTestResults] = useState<
    Record<number, { success: boolean; resolution?: string; error?: string } | null>
  >({});

  const updatePrinterMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof api.updatePrinter>[1] }) =>
      api.updatePrinter(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['printers'] });
      showToast(t('settings.toast.cameraSaved', 'Kameraeinstellungen gespeichert'), 'success');
    },
    onError: (err: Error) => {
      showToast(err.message || t('settings.toast.cameraSaveFailed', 'Kameraeinstellungen konnten nicht gespeichert werden'), 'error');
    },
  });

  // Die URL-Felder speichern erst 800 ms nach dem letzten Tastendruck: sonst ginge pro Zeichen ein PATCH
  // samt Toast raus (und die Eingabe würde vom Neuladen der Druckerliste überschrieben).
  const cameraUrlSaveTimeoutRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({});
  const snapshotUrlSaveTimeoutRef = useRef<Record<number, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    const cameraTimers = cameraUrlSaveTimeoutRef.current;
    const snapshotTimers = snapshotUrlSaveTimeoutRef.current;
    return () => {
      Object.values(cameraTimers).forEach(clearTimeout);
      Object.values(snapshotTimers).forEach(clearTimeout);
    };
  }, []);

  const handleCameraUrlChange = (printerId: number, url: string) => {
    setLocalCameraUrls(prev => ({ ...prev, [printerId]: url }));
    clearTimeout(cameraUrlSaveTimeoutRef.current[printerId]);
    cameraUrlSaveTimeoutRef.current[printerId] = setTimeout(() => {
      updatePrinterMutation.mutate({ id: printerId, data: { external_camera_url: url || null } });
    }, 800);
  };

  const handleSnapshotUrlChange = (printerId: number, url: string) => {
    setLocalSnapshotUrls(prev => ({ ...prev, [printerId]: url }));
    clearTimeout(snapshotUrlSaveTimeoutRef.current[printerId]);
    snapshotUrlSaveTimeoutRef.current[printerId] = setTimeout(() => {
      updatePrinterMutation.mutate({ id: printerId, data: { external_camera_snapshot_url: url || null } });
    }, 800);
  };

  const handleUpdatePrinterCamera = (
    printerId: number,
    updates: { type?: string; enabled?: boolean; rotation?: number }
  ) => {
    const data: Parameters<typeof api.updatePrinter>[1] = {};
    if (updates.type !== undefined) data.external_camera_type = updates.type;
    if (updates.enabled !== undefined) data.external_camera_enabled = updates.enabled;
    if (updates.rotation !== undefined) data.camera_rotation = updates.rotation;
    updatePrinterMutation.mutate({ id: printerId, data });
  };

  const handleTestExternalCamera = async (printerId: number, url: string, cameraType: string) => {
    setExtCameraTestLoading(prev => ({ ...prev, [printerId]: true }));
    setExtCameraTestResults(prev => ({ ...prev, [printerId]: null }));
    try {
      const result = await api.testExternalCamera(printerId, url, cameraType);
      setExtCameraTestResults(prev => ({ ...prev, [printerId]: result }));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t('settings.toast.connectionFailed', 'Verbindung fehlgeschlagen');
      setExtCameraTestResults(prev => ({ ...prev, [printerId]: { success: false, error: msg } }));
    } finally {
      setExtCameraTestLoading(prev => ({ ...prev, [printerId]: false }));
    }
  };

  // Storage usage
  const [storageUsageRefreshing, setStorageUsageRefreshing] = useState(false);
  const {
    data: storageUsage,
    isLoading: storageUsageLoading,
    isFetching: storageUsageFetching,
    refetch: refetchStorageUsage,
  } = useQuery({
    queryKey: ['storage-usage'],
    queryFn: () => api.getStorageUsage(),
    staleTime: 60 * 1000,
  });

  const handleStorageUsageRefresh = async () => {
    setStorageUsageRefreshing(true);
    try {
      await api.getStorageUsage({ refresh: true });
      await refetchStorageUsage();
      showToast(t('settings.toast.storageUsageRefreshed', 'Speicheranalyse aktualisiert'), 'success');
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Fehler beim Aktualisieren der Speicheranalyse', 'error');
    } finally {
      setStorageUsageRefreshing(false);
    }
  };

  // Modals state
  const [showClearLogsConfirm, setShowClearLogsConfirm] = useState(false);
  const [showClearStorageConfirm, setShowClearStorageConfirm] = useState(false);
  const [showRebuildConfirm, setShowRebuildConfirm] = useState(false);
  const [isRebuildLoading, setIsRebuildLoading] = useState(false);

  // Render individual card blocks
  const renderBasicCard = () => (
    <Card id="card-general">
      <CardHeader>
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Sliders className="w-5 h-5 text-bambu-green" />
          {t('settings.general', 'Allgemeine Einstellungen')}
        </h2>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              <Globe className="w-4 h-4 inline mr-1" />
              {t('settings.language', 'Sprache')}
            </label>
            <div className="relative">
              <select
                value={i18n.language}
                onChange={(e) => {
                  const newLang = e.target.value;
                  if (authEnabled && !hasPermission('settings:update')) {
                    showToast(t('settings.toast.noPermissionUpdate', 'Keine Berechtigung zum Ändern der Einstellungen'), 'error');
                    return;
                  }
                  i18n.changeLanguage(newLang);
                  updateSetting('language', newLang);
                }}
                className="w-full px-3 py-2 pr-10 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none appearance-none cursor-pointer"
              >
                {availableLanguages.map((lang) => (
                  <option key={lang.code} value={lang.code}>
                    {lang.nativeName} ({lang.name})
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray pointer-events-none" />
            </div>
            <p className="text-xs text-bambu-gray mt-1">
              {t('settings.languageDescription', 'Wählen Sie Ihre bevorzugte Sprache für die Benutzeroberfläche.')}
            </p>
          </div>

          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              {t('settings.defaultView', 'Standardansicht')}
            </label>
            <div className="relative">
              <select
                value={defaultView}
                onChange={(e) => handleDefaultViewChange(e.target.value)}
                className="w-full px-3 py-2 pr-10 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none appearance-none cursor-pointer"
              >
                {defaultNavItems.map((item) => (
                  <option key={item.id} value={item.to}>
                    {t(item.labelKey)}
                  </option>
                ))}
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray pointer-events-none" />
            </div>
            <p className="text-xs text-bambu-gray mt-1">
              {t('settings.defaultViewDescription', 'Seite, die beim Öffnen der Anwendung standardmäßig angezeigt wird.')}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2 border-t border-bambu-dark-tertiary">
          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              {t('settings.dateFormat', 'Datumsformat')}
            </label>
            <div className="relative">
              <select
                value={localSettings.date_format || 'system'}
                onChange={(e) => updateSetting('date_format', e.target.value as 'system' | 'us' | 'eu' | 'iso')}
                className="w-full px-3 py-2 pr-10 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none appearance-none cursor-pointer"
              >
                <option value="system">{t('settings.systemDefault', 'Systemstandard')}</option>
                <option value="us">{t('settings.dateFormatUs', 'MM/DD/YYYY')}</option>
                <option value="eu">{t('settings.dateFormatEu', 'DD.MM.YYYY')}</option>
                <option value="iso">{t('settings.dateFormatIso', 'YYYY-MM-DD')}</option>
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray pointer-events-none" />
            </div>
          </div>

          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              {t('settings.timeFormat', 'Zeitformat')}
            </label>
            <div className="relative">
              <select
                value={localSettings.time_format || 'system'}
                onChange={(e) => updateSetting('time_format', e.target.value as 'system' | '12h' | '24h')}
                className="w-full px-3 py-2 pr-10 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none appearance-none cursor-pointer"
              >
                <option value="system">{t('settings.systemDefault', 'Systemstandard')}</option>
                <option value="12h">{t('settings.timeFormat12', '12 Stunden (AM/PM)')}</option>
                <option value="24h">{t('settings.timeFormat24', '24 Stunden')}</option>
              </select>
              <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray pointer-events-none" />
            </div>
          </div>
        </div>

        <div className="pt-2 border-t border-bambu-dark-tertiary">
          <label className="block text-sm text-bambu-gray mb-1">
            {t('settings.defaultPrinter', 'Standarddrucker')}
          </label>
          <div className="relative">
            <select
              value={localSettings.default_printer_id ?? ''}
              onChange={(e) => updateSetting('default_printer_id', e.target.value ? Number(e.target.value) : null)}
              className="w-full px-3 py-2 pr-10 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none appearance-none cursor-pointer"
            >
              <option value="">{t('settings.noDefaultPrinter', 'Kein Standard (jedes Mal fragen)')}</option>
              {printers?.map((printer) => (
                <option key={printer.id} value={printer.id}>
                  {printer.name}
                </option>
              ))}
            </select>
            <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray pointer-events-none" />
          </div>
          <p className="text-xs text-bambu-gray mt-1">
            {t('settings.defaultPrinterDescription', 'Diesen Drucker für Uploads, Nachdrucke und andere Vorgänge vorauswählen.')}
          </p>
        </div>
      </CardContent>
    </Card>
  );

  const renderAppearanceCard = () => (
    <div className="space-y-6">
      <Card id="card-appearance">
        <CardHeader>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Palette className="w-5 h-5 text-bambu-green" />
            {t('settings.appearance', 'Erscheinungsbild')}
          </h2>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Theme Mode Selector */}
          <div className="flex items-center gap-2">
            <label className="text-sm text-bambu-gray">{t('settings.theme', 'Design')}:</label>
            <div className="flex gap-1">
              {([
                { id: 'dark', label: t('settings.themeDark', 'Dunkel') },
                { id: 'light', label: t('settings.themeLight', 'Hell') },
                { id: 'system', label: t('settings.themeSystem', 'System') },
              ] as const).map(({ id, label }) => (
                <button
                  key={id}
                  onClick={() => {
                    setMode(id);
                    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                  }}
                  className={`px-3 py-1 text-xs rounded-lg border transition-colors ${
                    mode === id
                      ? 'border-bambu-green bg-bambu-green/10 text-bambu-green font-medium'
                      : 'border-bambu-dark-tertiary text-bambu-gray hover:text-white cursor-pointer'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Dark Mode Settings */}
          <div className={`space-y-3 p-4 rounded-lg border ${resolvedMode === 'dark' ? 'border-bambu-green bg-bambu-green/5' : 'border-bambu-dark-tertiary'}`}>
            <h3 className="text-sm font-medium text-white flex items-center gap-2">
              {t('settings.darkMode', 'Dunkelmodus')}
              {resolvedMode === 'dark' && <span className="text-xs text-bambu-green">({t('settings.active', 'aktiv')})</span>}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-bambu-gray mb-1">{t('settings.background', 'Hintergrund')}</label>
                <select
                  value={darkBackground}
                  onChange={(e) => {
                    setDarkBackground(e.target.value as DarkBackground);
                    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                  }}
                  className="w-full px-2 py-1.5 text-sm bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                >
                  <option value="neutral">{t('settings.bgNeutral', 'Neutral')}</option>
                  <option value="warm">{t('settings.bgWarm', 'Warm')}</option>
                  <option value="cool">{t('settings.bgCool', 'Kühl')}</option>
                  <option value="oled">{t('settings.bgOled', 'OLED')}</option>
                  <option value="slate">{t('settings.bgSlate', 'Schiefer')}</option>
                  <option value="forest">{t('settings.bgForest', 'Wald')}</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-bambu-gray mb-1">{t('settings.accent', 'Akzent')}</label>
                <select
                  value={darkAccent}
                  onChange={(e) => {
                    setDarkAccent(e.target.value as ThemeAccent);
                    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                  }}
                  className="w-full px-2 py-1.5 text-sm bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                >
                  <option value="green">{t('settings.accentGreen', 'Grün')}</option>
                  <option value="teal">{t('settings.accentTeal', 'Türkis')}</option>
                  <option value="blue">{t('settings.accentBlue', 'Blau')}</option>
                  <option value="orange">{t('settings.accentOrange', 'Orange')}</option>
                  <option value="purple">{t('settings.accentPurple', 'Lila')}</option>
                  <option value="red">{t('settings.accentRed', 'Rot')}</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-bambu-gray mb-1">{t('settings.style', 'Stil')}</label>
                <select
                  value={darkStyle}
                  onChange={(e) => {
                    setDarkStyle(e.target.value as ThemeStyle);
                    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                  }}
                  className="w-full px-2 py-1.5 text-sm bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                >
                  <option value="classic">{t('settings.styleClassic', 'Klassisch')}</option>
                  <option value="glow">{t('settings.styleGlow', 'Leuchtend')}</option>
                  <option value="vibrant">{t('settings.styleVibrant', 'Lebendig')}</option>
                </select>
              </div>
            </div>
          </div>

          {/* Light Mode Settings */}
          <div className={`space-y-3 p-4 rounded-lg border ${resolvedMode === 'light' ? 'border-bambu-green bg-bambu-green/5' : 'border-bambu-dark-tertiary'}`}>
            <h3 className="text-sm font-medium text-white flex items-center gap-2">
              {t('settings.lightMode', 'Hellmodus')}
              {resolvedMode === 'light' && <span className="text-xs text-bambu-green">({t('settings.active', 'aktiv')})</span>}
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <label className="block text-xs text-bambu-gray mb-1">{t('settings.background', 'Hintergrund')}</label>
                <select
                  value={lightBackground}
                  onChange={(e) => {
                    setLightBackground(e.target.value as LightBackground);
                    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                  }}
                  className="w-full px-2 py-1.5 text-sm bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                >
                  <option value="neutral">{t('settings.bgNeutral', 'Neutral')}</option>
                  <option value="warm">{t('settings.bgWarm', 'Warm')}</option>
                  <option value="cool">{t('settings.bgCool', 'Kühl')}</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-bambu-gray mb-1">{t('settings.accent', 'Akzent')}</label>
                <select
                  value={lightAccent}
                  onChange={(e) => {
                    setLightAccent(e.target.value as ThemeAccent);
                    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                  }}
                  className="w-full px-2 py-1.5 text-sm bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                >
                  <option value="green">{t('settings.accentGreen', 'Grün')}</option>
                  <option value="teal">{t('settings.accentTeal', 'Türkis')}</option>
                  <option value="blue">{t('settings.accentBlue', 'Blau')}</option>
                  <option value="orange">{t('settings.accentOrange', 'Orange')}</option>
                  <option value="purple">{t('settings.accentPurple', 'Lila')}</option>
                  <option value="red">{t('settings.accentRed', 'Rot')}</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-bambu-gray mb-1">{t('settings.style', 'Stil')}</label>
                <select
                  value={lightStyle}
                  onChange={(e) => {
                    setLightStyle(e.target.value as ThemeStyle);
                    showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                  }}
                  className="w-full px-2 py-1.5 text-sm bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
                >
                  <option value="classic">{t('settings.styleClassic', 'Klassisch')}</option>
                  <option value="glow">{t('settings.styleGlow', 'Leuchtend')}</option>
                  <option value="vibrant">{t('settings.styleVibrant', 'Lebendig')}</option>
                </select>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between pt-2 border-t border-bambu-dark-tertiary">
            <div>
              <p className="text-white">{t('settings.progressInTitle', 'Druckfortschritt im Browsertab')}</p>
              <p className="text-sm text-bambu-gray">
                {t('settings.progressInTitleDescription', 'Zeigt den Prozentsatz des aktiven Drucks direkt im Tab-Titel an.')}
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={progressInTitle}
                onChange={(e) => {
                  setProgressInTitle(e.target.checked);
                  showToast(t('settings.toast.settingsSaved', 'Einstellungen gespeichert'), 'success');
                }}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
            </label>
          </div>
        </CardContent>
      </Card>

      {/* Sidebar Links & Navigation Customization */}
      <div id="card-sidebar-links">
        <ExternalLinksSettings />
      </div>
    </div>
  );

  const renderCostsCard = () => (
    <Card id="card-cost">
      <CardHeader>
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <DollarSign className="w-5 h-5 text-bambu-green" />
          {t('settings.costTracking', 'Kostenverfolgung & Abrechnung')}
        </h2>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-sm text-bambu-gray mb-1">{t('settings.currency', 'Währung')}</label>
            <select
              value={localSettings.currency}
              onChange={(e) => updateSetting('currency', e.target.value)}
              className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
            >
              {SUPPORTED_CURRENCIES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              {t('settings.defaultFilamentCost', 'Standard-Filamentkosten (pro kg)')}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-bambu-gray text-sm pointer-events-none">
                {getCurrencySymbol(localSettings.currency)}
              </span>
              <NumberInput
                step="0.01"
                min={0}
                value={localSettings.default_filament_cost}
                onChange={(v) => updateSetting('default_filament_cost', v)}
                integer={false}
                fallback={0}
                style={{ paddingLeft: `${Math.max(2, getCurrencySymbol(localSettings.currency).length * 0.6 + 1)}rem` }}
                className="w-full pr-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              {t('settings.electricityCost', 'Stromkosten pro kWh')}
            </label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-bambu-gray text-sm pointer-events-none">
                {getCurrencySymbol(localSettings.currency)}
              </span>
              <NumberInput
                step="0.001"
                min={0}
                value={localSettings.energy_cost_per_kwh}
                onChange={(v) => updateSetting('energy_cost_per_kwh', v)}
                integer={false}
                fallback={0}
                style={{ paddingLeft: `${Math.max(2, getCurrencySymbol(localSettings.currency).length * 0.6 + 1)}rem` }}
                className="w-full pr-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
              />
            </div>
          </div>
        </div>

        <div>
          <label className="block text-sm text-bambu-gray mb-1">
            {t('settings.energyDisplayMode', 'Energieanzeige-Modus')}
          </label>
          <select
            value={localSettings.energy_tracking_mode || 'total'}
            onChange={(e) => updateSetting('energy_tracking_mode', e.target.value as 'print' | 'total')}
            className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
          >
            <option value="print">{t('settings.printsOnly', 'Nur Druckvorgänge')}</option>
            <option value="total">{t('settings.totalConsumption', 'Gesamtverbrauch')}</option>
          </select>
          <p className="text-xs text-bambu-gray mt-1">
            {localSettings.energy_tracking_mode === 'print'
              ? t('settings.energyModePrintDescription', 'Berücksichtigt nur den Energieverbrauch während aktiver Drucke.')
              : t('settings.energyModeTotalDescription', 'Dashboard zeigt die Gesamtenergie der konfigurierten Smart Plugs.')}
          </p>
        </div>

        <div className="pt-3 border-t border-bambu-dark-tertiary">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white font-medium">{t('settings.billingEnabled', 'Abrechnung & Kostenstellen aktivieren')}</p>
              <p className="text-xs text-bambu-gray">
                {t('settings.billingEnabledDescription', 'Ermöglicht Kostenstellen-Zuweisung, Guthaben-Verwaltung und Auftragsabrechnung.')}
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={localSettings.billing_enabled ?? false}
                onChange={(e) => updateSetting('billing_enabled', e.target.checked)}
                className="peer sr-only"
              />
              <div className="w-11 h-6 bg-bambu-dark-tertiary rounded-full peer-checked:bg-bambu-green peer-checked:after:translate-x-5 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border after:rounded-full after:h-5 after:w-5 after:transition-all" />
            </label>
          </div>

          {localSettings.billing_enabled && (
            <div className="mt-4 space-y-4">
              <div className="flex items-center justify-between gap-4 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-4 py-3">
                <div className="flex-1">
                  <p className="text-white font-medium">
                    {t('settings.printerKillSwitch', 'Automatischer Druckstopp bei fehlender Autorisierung')}
                  </p>
                  <p className="text-xs text-bambu-gray mt-1">
                    {t(
                      'settings.printerKillSwitchDescription',
                      'Bricht Drucke sofort automatisch ab, falls diese ohne gültige Kostenstellen-Autorisierung gestartet werden.'
                    )}
                  </p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={localSettings.printer_kill_switch_enabled ?? false}
                    onChange={(e) => updateSetting('printer_kill_switch_enabled', e.target.checked)}
                    className="peer sr-only"
                  />
                  <div className="w-11 h-6 bg-bambu-dark-tertiary rounded-full peer-checked:bg-bambu-green peer-checked:after:translate-x-5 after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border after:rounded-full after:h-5 after:w-5 after:transition-all" />
                </label>
              </div>

              <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-4">
                <div className="mb-3">
                  <h4 className="text-base font-medium text-white flex items-center gap-2">
                    <Calendar className="w-4 h-4 text-bambu-green" />
                    {t('settings.financeBudgetReset', 'Finanzbudget monatlich zurücksetzen')}
                  </h4>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs text-bambu-gray mb-1">
                      {t('settings.financeBudgetResetDay', 'Reset-Tag')}
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={31}
                      value={localSettings.finance_budget_reset_day ?? 1}
                      onChange={(e) =>
                        updateSetting(
                          'finance_budget_reset_day',
                          Math.max(1, Math.min(31, parseInt(e.target.value, 10) || 1))
                        )
                      }
                      className="w-full px-3 py-2 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:outline-none focus:border-bambu-green"
                    />
                    <p className="text-xs text-bambu-gray mt-1">
                      {t('settings.financeBudgetResetDayHelp', 'Für kurze Monate wird automatisch der letzte Tag des Monats verwendet.')}
                    </p>
                  </div>
                  <div>
                    <label className="block text-xs text-bambu-gray mb-1">
                      {t('settings.financeBudgetResetTimezone', 'Reset-Zeitzone')}
                    </label>
                    <select
                      value={localSettings.finance_budget_reset_timezone ?? 'UTC'}
                      onChange={(e) => updateSetting('finance_budget_reset_timezone', e.target.value)}
                      className="w-full px-3 py-2 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white text-sm focus:outline-none focus:border-bambu-green"
                    >
                      <option value="UTC">UTC</option>
                      <option value="Europe/Berlin">Europe/Berlin</option>
                      <option value="Europe/Vienna">Europe/Vienna</option>
                      <option value="Europe/Zurich">Europe/Zurich</option>
                      <option value="America/New_York">America/New_York</option>
                      <option value="America/Chicago">America/Chicago</option>
                      <option value="America/Denver">America/Denver</option>
                      <option value="America/Los_Angeles">America/Los_Angeles</option>
                      <option value="Asia/Tokyo">Asia/Tokyo</option>
                      <option value="Asia/Singapore">Asia/Singapore</option>
                      <option value="Australia/Sydney">Australia/Sydney</option>
                    </select>
                    <p className="text-xs text-bambu-gray mt-1">
                      {t('settings.financeBudgetResetTimezoneHelp', 'Der Start des Budget-Fensters wird in dieser Zeitzone berechnet.')}
                    </p>
                  </div>
                </div>
              </div>

              {isAdmin && (
                <div className="pt-2">
                  <Button
                    variant="secondary"
                    onClick={() => setShowRebuildConfirm(true)}
                    disabled={isRebuildLoading}
                  >
                    {isRebuildLoading ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        {t('settings.rebuildLedgerInProgress', 'Startet...')}
                      </>
                    ) : (
                      t('settings.rebuildLedger', 'Wallet-Ledger neu aufbauen')
                    )}
                  </Button>

                  {showRebuildConfirm && (
                    <ConfirmModal
                      title={t('settings.rebuildLedgerConfirmTitle', 'Wallet-Ledger neu aufbauen?')}
                      message={t(
                        'settings.rebuildLedgerConfirmMessage',
                        'Dies baut das Ledger neu auf, um historische Salden zu reparieren. Führen Sie dies nur aus, wenn Unstimmigkeiten in Konten vorliegen.'
                      )}
                      confirmText={t('common.run', 'Ausführen')}
                      cancelText={t('common.cancel', 'Abbrechen')}
                      isLoading={isRebuildLoading}
                      loadingText={t('common.running', 'Wird ausgeführt')}
                      variant="warning"
                      onCancel={() => setShowRebuildConfirm(false)}
                      onConfirm={async () => {
                        setIsRebuildLoading(true);
                        try {
                          await api.rebuildBalanceLedger();
                          showToast(t('settings.rebuildLedgerStarted', 'Ledger-Neuberechnung gestartet'), 'success');
                          setShowRebuildConfirm(false);
                        } catch (err: unknown) {
                          showToast(err instanceof Error ? err.message : 'Fehler beim Starten der Neuberechnung', 'error');
                        } finally {
                          setIsRebuildLoading(false);
                        }
                      }}
                    />
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );

  const renderCameraCard = () => (
    <div className="space-y-6">
      <Card id="card-camera">
        <CardHeader>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Video className="w-5 h-5 text-bambu-green" />
            {t('settings.externalCameras', 'Externe Kameras')}
          </h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-bambu-gray">
            {t(
              'settings.externalCamerasDescription',
              'Konfigurieren Sie externe Kameras für jeden Drucker (z. B. MJPEG, RTSP, Snapshot oder USB V4L2). Wenn aktiv, ersetzt die externe Kamera die interne Druckerkamera für Live-Stream und Fotos.'
            )}
          </p>

          {printers && printers.length > 0 ? (
            <div className="space-y-3">
              {printers.map((printer) => (
                <div key={printer.id} className="p-4 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-white font-medium text-sm flex items-center gap-2">
                      <Camera className="w-4 h-4 text-bambu-green" />
                      {printer.name}
                    </span>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        checked={printer.external_camera_enabled}
                        onChange={(e) => handleUpdatePrinterCamera(printer.id, { enabled: e.target.checked })}
                        className="sr-only peer"
                      />
                      <div className="w-9 h-5 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-bambu-green"></div>
                    </label>
                  </div>

                  {printer.external_camera_enabled && (
                    <div className="space-y-3 mt-3 pt-3 border-t border-bambu-dark-tertiary">
                      <div>
                        <label className="block text-xs text-bambu-gray mb-1">
                          {printer.external_camera_type === 'usb' ? 'USB Gerät / Pfad' : 'Stream-URL'}
                        </label>
                        <input
                          type="text"
                          placeholder={
                            printer.external_camera_type === 'usb'
                              ? t('settings.cameraPlaceholderUsb', '/dev/video0')
                              : t('settings.cameraPlaceholderUrl', 'http://192.168.1.100:8080/?action=stream')
                          }
                          value={localCameraUrls[printer.id] ?? printer.external_camera_url ?? ''}
                          onChange={(e) => handleCameraUrlChange(printer.id, e.target.value)}
                          className="w-full px-3 py-2 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded text-white text-sm focus:border-bambu-green focus:outline-none"
                        />
                      </div>

                      <div className="flex flex-wrap items-center gap-3">
                        <div className="flex-1 min-w-[140px]">
                          <label className="block text-xs text-bambu-gray mb-1">Protokoll / Typ</label>
                          <select
                            value={printer.external_camera_type || 'mjpeg'}
                            onChange={(e) => handleUpdatePrinterCamera(printer.id, { type: e.target.value })}
                            className="w-full px-3 py-2 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded text-white text-sm focus:border-bambu-green focus:outline-none"
                          >
                            <option value="mjpeg">{t('settings.cameraTypeMjpeg', 'MJPEG Stream')}</option>
                            <option value="rtsp">{t('settings.cameraTypeRtsp', 'RTSP Stream')}</option>
                            <option value="snapshot">{t('settings.cameraTypeSnapshot', 'HTTP Snapshot')}</option>
                            <option value="usb">{t('settings.cameraTypeUsb', 'USB Kamera (V4L2)')}</option>
                          </select>
                        </div>

                        <div className="w-28">
                          <label className="block text-xs text-bambu-gray mb-1">{t('settings.cameraRotation', 'Rotation')}</label>
                          <select
                            value={printer.camera_rotation || 0}
                            onChange={(e) => handleUpdatePrinterCamera(printer.id, { rotation: parseInt(e.target.value, 10) })}
                            className="w-full px-2 py-2 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded text-white text-sm focus:border-bambu-green focus:outline-none"
                          >
                            <option value={0}>0°</option>
                            <option value={90}>90°</option>
                            <option value={180}>180°</option>
                            <option value={270}>270°</option>
                          </select>
                        </div>

                        <div className="pt-5">
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              handleTestExternalCamera(
                                printer.id,
                                localCameraUrls[printer.id] ?? printer.external_camera_url ?? '',
                                printer.external_camera_type || 'mjpeg'
                              )
                            }
                            disabled={extCameraTestLoading[printer.id] || !(localCameraUrls[printer.id] ?? printer.external_camera_url)}
                          >
                            {extCameraTestLoading[printer.id] ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              t('settings.test', 'Verbindung testen')
                            )}
                          </Button>
                        </div>
                      </div>

                      {extCameraTestResults[printer.id] && (
                        <div
                          className={`text-xs flex items-center gap-1.5 p-2 rounded ${
                            extCameraTestResults[printer.id]?.success
                              ? 'bg-green-500/10 text-green-400 border border-green-500/30'
                              : 'bg-red-500/10 text-red-400 border border-red-500/30'
                          }`}
                        >
                          {extCameraTestResults[printer.id]?.success ? (
                            <>
                              <CheckCircle className="w-3.5 h-3.5 shrink-0" />
                              <span>
                                {t('settings.connected', 'Verbunden')}
                                {extCameraTestResults[printer.id]?.resolution && ` (${extCameraTestResults[printer.id]?.resolution})`}
                              </span>
                            </>
                          ) : (
                            <>
                              <XCircle className="w-3.5 h-3.5 shrink-0" />
                              <span>{extCameraTestResults[printer.id]?.error || t('settings.toast.connectionFailed', 'Verbindung fehlgeschlagen')}</span>
                            </>
                          )}
                        </div>
                      )}

                      {(printer.external_camera_type === 'mjpeg' ||
                        printer.external_camera_type === 'rtsp' ||
                        printer.external_camera_type === 'usb') && (
                        <div className="space-y-1.5 pt-2 border-t border-bambu-dark-tertiary">
                          <label className="text-xs text-bambu-gray font-medium">
                            {t('settings.cameraSnapshotUrl', 'Snapshot URL (optional)')}
                          </label>
                          <div className="flex gap-2">
                            <input
                              type="text"
                              placeholder={t('settings.cameraSnapshotUrlPlaceholder', 'http://192.168.1.61:1984/api/frame.jpeg?src=printer')}
                              value={localSnapshotUrls[printer.id] ?? printer.external_camera_snapshot_url ?? ''}
                              onChange={(e) => handleSnapshotUrlChange(printer.id, e.target.value)}
                              className="flex-1 px-3 py-2 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded text-white text-sm focus:border-bambu-green focus:outline-none"
                            />
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() =>
                                handleTestExternalCamera(
                                  printer.id,
                                  localSnapshotUrls[printer.id] ?? printer.external_camera_snapshot_url ?? '',
                                  'snapshot'
                                )
                              }
                              disabled={extCameraTestLoading[printer.id] || !(localSnapshotUrls[printer.id] ?? printer.external_camera_snapshot_url)}
                            >
                              {extCameraTestLoading[printer.id] ? (
                                <Loader2 className="w-4 h-4 animate-spin" />
                              ) : (
                                t('settings.test', 'Testen')
                              )}
                            </Button>
                          </div>
                          <p className="text-xs text-bambu-gray opacity-75">
                            {t(
                              'settings.cameraSnapshotUrlHelp',
                              'Einzelbild-URL für Benachrichtigungsvorschauen, Abschlussfotos und Zeiterfassung. Leer lassen, um aus dem Livestream zu erfassen.'
                            )}
                          </p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-bambu-gray italic">{t('settings.noPrintersConfigured', 'Keine Drucker konfiguriert.')}</p>
          )}
        </CardContent>
      </Card>

      {/* Finish Photo & Capture Settings */}
      <Card id="card-finish-photo">
        <CardHeader>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Camera className="w-5 h-5 text-bambu-green" />
            {t('settings.captureFinishPhotoTitle', 'Abschlussfotos & Druckbett')}
          </h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white">{t('settings.captureFinishPhoto', 'Abschlussfoto bei Druckende aufnehmen')}</p>
              <p className="text-sm text-bambu-gray">
                {t('settings.captureFinishPhotoDescription', 'Speichert automatisch ein hochauflösendes Foto, sobald ein Druckauftrag beendet wird.')}
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={localSettings.capture_finish_photo ?? false}
                onChange={(e) => updateSetting('capture_finish_photo', e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
            </label>
          </div>

          {localSettings.capture_finish_photo && (
            <div className="flex items-center justify-between pl-4 border-l-2 border-bambu-green/50">
              <div>
                <p className="text-white">{t('settings.finishPhotoRestorePlate', 'Druckbett nach Foto wiederherstellen')}</p>
                <p className="text-sm text-bambu-gray">
                  {t('settings.finishPhotoRestorePlateDescription', 'Fährt das Druckbett nach der Aufnahme wieder in die Parkposition.')}
                </p>
              </div>
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  checked={localSettings.finish_photo_restore_plate ?? true}
                  onChange={(e) => updateSetting('finish_photo_restore_plate', e.target.checked)}
                  className="sr-only peer"
                />
                <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
              </label>
            </div>
          )}

          {localSettings.capture_finish_photo && ffmpegStatus && !ffmpegStatus.installed && (
            <div className="flex items-start gap-2 p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-yellow-500 flex-shrink-0 mt-0.5" />
              <div className="text-sm">
                <p className="text-yellow-500 font-medium">{t('settings.ffmpegNotInstalled', 'FFmpeg nicht installiert')}</p>
                <p className="text-bambu-gray mt-1">
                  {t('settings.ffmpegRequired', 'FFmpeg wird für Video-Snapshots und Zeitraffer-Kompression benötigt.')}
                </p>
              </div>
            </div>
          )}

          <div className="pt-3 border-t border-bambu-dark-tertiary flex items-center justify-between text-xs text-bambu-gray">
            <span>OBS-Overlay oder Stream-Tokens benötigt?</span>
            {onTabChange && (
              <button
                type="button"
                onClick={() => onTabChange('apikeys')}
                className="text-bambu-green hover:underline flex items-center gap-1 font-medium"
              >
                Zu API-Schlüssel & Kamera-Tokens
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );

  const renderStorageCard = () => (
    <div className="space-y-6">
      {/* File Manager & Retention */}
      <Card id="card-filemanager">
        <CardHeader>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <FileText className="w-5 h-5 text-bambu-green" />
            {t('settings.fileManager', 'Dateimanager & Aufbewahrung')}
          </h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              {t('settings.createArchiveEntry', 'Archivierungs-Modus')}
            </label>
            <select
              value={localSettings.library_archive_mode ?? 'ask'}
              onChange={(e) => updateSetting('library_archive_mode', e.target.value as 'always' | 'never' | 'ask')}
              className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
            >
              <option value="always">{t('settings.archiveMode.always', 'Immer archivieren')}</option>
              <option value="never">{t('settings.archiveMode.never', 'Nie archivieren')}</option>
              <option value="ask">{t('settings.archiveMode.ask', 'Jedes Mal fragen')}</option>
            </select>
            <p className="text-xs text-bambu-gray mt-1">
              {t('settings.createArchiveEntryDescription', 'Legt fest, wie mit neuen Druckdateien in der Bibliothek umgegangen wird.')}
            </p>
          </div>

          <div>
            <label className="block text-sm text-bambu-gray mb-1">
              {t('settings.lowDiskSpaceWarning', 'Speicherplatz-Warnschwelle')}
            </label>
            <div className="flex items-center gap-2">
              <NumberInput
                min={0.5}
                max={100}
                step="0.5"
                value={localSettings.library_disk_warning_gb ?? 5}
                onChange={(v) => updateSetting('library_disk_warning_gb', v)}
                integer={false}
                fallback={5}
                className="w-24 px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none"
              />
              <span className="text-bambu-gray font-medium">GB</span>
            </div>
            <p className="text-xs text-bambu-gray mt-1">
              {t('settings.lowDiskSpaceDescription', 'Warnt im Dashboard, wenn der freie Festplattenspeicher diesen Wert unterschreitet.')}
            </p>
          </div>

          {canPurge && trashSettings && (
            <div className="border-t border-bambu-dark-tertiary pt-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-white font-medium">{t('libraryAutoPurge.enableLabel', 'Papierkorb automatisch leeren')}</p>
                  <p className="text-sm text-bambu-gray">{t('libraryAutoPurge.enableDescription', 'Löscht alte gelöschte Dateien nach einer bestimmten Frist endgültig.')}</p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={trashSettings.auto_purge_enabled}
                    onChange={(e) => saveTrashSettings({ auto_purge_enabled: e.target.checked })}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
                </label>
              </div>

              <div>
                <label className="block text-sm text-bambu-gray mb-1">
                  {t('libraryAutoPurge.ageLabel', 'Aufbewahrungsdauer')}
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={7}
                    max={3650}
                    disabled={!trashSettings.auto_purge_enabled}
                    value={trashSettings.auto_purge_days}
                    onChange={(e) =>
                      saveTrashSettings({
                        auto_purge_days: Math.max(7, Math.min(3650, parseInt(e.target.value || '0', 10) || 0)),
                      })
                    }
                    className="w-24 px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none disabled:opacity-50"
                  />
                  <span className="text-bambu-gray">{t('libraryAutoPurge.days', 'Tage')}</span>
                </div>
              </div>

              <label className="flex items-center gap-2 text-sm text-white cursor-pointer pt-1">
                <input
                  type="checkbox"
                  disabled={!trashSettings.auto_purge_enabled}
                  checked={trashSettings.auto_purge_include_never_printed}
                  onChange={(e) => saveTrashSettings({ auto_purge_include_never_printed: e.target.checked })}
                  className="rounded border-gray-300 disabled:opacity-50"
                />
                {t('libraryAutoPurge.includeNeverPrinted', 'Nie gedruckte Dateien mit einbeziehen')}
              </label>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Archive Settings */}
      <Card id="card-archive">
        <CardHeader>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Database className="w-5 h-5 text-bambu-green" />
            {t('settings.archiveSettings', 'Archivierung & Verlaufsbereinigung')}
          </h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-white font-medium">{t('settings.autoArchivePrints', 'Drucke automatisch archivieren')}</p>
              <p className="text-sm text-bambu-gray">
                {t('settings.autoArchiveDescription', 'Erstellt nach Fertigstellung automatisch einen archivierten Verlaufseintrag.')}
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={localSettings.auto_archive ?? true}
                onChange={(e) => updateSetting('auto_archive', e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
            </label>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <p className="text-white font-medium">{t('settings.saveThumbnails', 'Vorschaubilder speichern')}</p>
              <p className="text-sm text-bambu-gray">
                {t('settings.saveThumbnailsDescription', 'Speichert gerenderte G-Code-Vorschauen in der Datenbank für schnellen Zugriff.')}
              </p>
            </div>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={localSettings.save_thumbnails ?? true}
                onChange={(e) => updateSetting('save_thumbnails', e.target.checked)}
                className="sr-only peer"
              />
              <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
            </label>
          </div>

          {canPurgeArchives && archivePurgeSettings && (
            <div className="border-t border-bambu-dark-tertiary pt-4 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-white font-medium">{t('archiveAutoPurge.enableLabel', 'Archiv automatisch bereinigen')}</p>
                  <p className="text-sm text-bambu-gray">{t('archiveAutoPurge.enableDescription', 'Löscht Verläufe, die älter als der angegebene Zeitraum sind.')}</p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={archivePurgeSettings.enabled}
                    onChange={(e) => saveArchivePurgeSettings({ enabled: e.target.checked })}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-bambu-dark-tertiary peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-bambu-green"></div>
                </label>
              </div>

              <div>
                <label className="block text-sm text-bambu-gray mb-1">
                  {t('archiveAutoPurge.ageLabel', 'Maximales Alter')}
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    min={7}
                    max={3650}
                    disabled={!archivePurgeSettings.enabled}
                    value={archivePurgeSettings.days}
                    onChange={(e) =>
                      saveArchivePurgeSettings({
                        days: Math.max(7, Math.min(3650, parseInt(e.target.value || '0', 10) || 0)),
                      })
                    }
                    className="w-24 px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white focus:border-bambu-green focus:outline-none disabled:opacity-50"
                  />
                  <span className="text-bambu-gray">{t('archiveAutoPurge.days', 'Tage')}</span>
                </div>
              </div>

              <label className="flex items-start gap-2 cursor-pointer pt-1">
                <input
                  type="checkbox"
                  disabled={!archivePurgeSettings.enabled}
                  checked={archivePurgeSettings.purge_stats}
                  onChange={(e) => saveArchivePurgeSettings({ purge_stats: e.target.checked })}
                  className="mt-0.5 shrink-0 disabled:opacity-50"
                />
                <span className="text-sm">
                  <span className="text-white block font-medium">{t('archiveAutoPurge.purgeStatsLabel', 'Statistiken mit löschen')}</span>
                  <span className="text-xs text-bambu-gray block mt-0.5">
                    {t('archiveAutoPurge.purgeStatsDescription', 'Löscht auch zugehörige Verbrauchsdaten aus der Datenbank.')}
                  </span>
                </span>
              </label>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Storage Breakdown & System Cleanup */}
      <Card id="card-data">
        <CardHeader>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <HardDrive className="w-5 h-5 text-bambu-green" />
              {t('settings.storageUsage', 'Speicherplatz-Nutzung & Bereinigung')}
            </h2>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleStorageUsageRefresh}
              disabled={storageUsageFetching || storageUsageRefreshing}
            >
              <RefreshCw
                className={`w-4 h-4 mr-1.5 ${storageUsageFetching || storageUsageRefreshing ? 'animate-spin' : ''}`}
              />
              {t('common.refresh', 'Aktualisieren')}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-bambu-gray">
            {t('settings.storageUsageDescription', 'Aufschlüsselung des belegten Speicherplatzes nach Datenkategorien')}
          </p>

          <div>
            {storageUsageLoading ? (
              <div className="flex items-center gap-2 text-sm text-bambu-gray py-4">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('common.loading', 'Laden...')}
              </div>
            ) : storageUsage ? (
              <>
                <div className="w-full h-3.5 bg-bambu-dark-secondary rounded-full overflow-hidden flex border border-bambu-dark-tertiary">
                  {storageUsage.categories
                    .filter((category) => category.bytes > 0)
                    .map((category, index) => (
                      <div
                        key={category.key}
                        className={`${getStorageColor(category.key, index)} h-full transition-all`}
                        style={{ width: `${category.percent_of_total}%` }}
                        title={`${category.label}: ${category.formatted}`}
                      />
                    ))}
                </div>
                <div className="mt-3 flex flex-wrap gap-3">
                  {storageUsage.categories
                    .filter((category) => category.bytes > 0)
                    .map((category, index) => (
                      <div key={category.key} className="flex items-center gap-1.5 text-xs bg-bambu-dark px-2.5 py-1 rounded-lg border border-bambu-dark-tertiary">
                        <span className={`w-2.5 h-2.5 rounded-full ${getStorageColor(category.key, index)}`} />
                        <span className="text-bambu-gray">{category.label}:</span>
                        <span className="text-white font-medium">{category.formatted}</span>
                        <span className="text-bambu-gray font-mono">({category.percent_of_total.toFixed(1)}%)</span>
                      </div>
                    ))}
                </div>
                <div className="mt-2 text-xs text-bambu-gray flex items-center justify-between">
                  <span>
                    {t('settings.storageUsageTotal', 'Gesamtbelegung')}: <strong className="text-white">{storageUsage.total_formatted}</strong>
                  </span>
                  {storageUsage.scan_errors > 0 && (
                    <span className="text-amber-400">
                      {t('settings.storageUsageErrors', 'Scan-Fehler')}: {storageUsage.scan_errors}
                    </span>
                  )}
                </div>
              </>
            ) : (
              <p className="text-sm text-bambu-gray italic">
                {t('settings.storageUsageUnavailable', 'Speicheranalyse derzeit nicht verfügbar.')}
              </p>
            )}
          </div>

          <div className="pt-4 border-t border-bambu-dark-tertiary space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-white font-medium">{t('settings.clearNotificationLogs', 'Benachrichtigungsprotokolle leeren')}</p>
                <p className="text-xs text-bambu-gray">
                  {t('settings.clearNotificationLogsDescription', 'Entfernt alte Protokolleinträge aus der Datenbank.')}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowClearLogsConfirm(true)}
              >
                <Trash2 className="w-4 h-4 mr-1 text-red-400" />
                {t('common.clear', 'Bereinigen')}
              </Button>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-bambu-dark-tertiary">
              <div>
                <p className="text-white font-medium">{t('settings.resetUiPreferences', 'UI-Einstellungen zurücksetzen')}</p>
                <p className="text-xs text-bambu-gray">
                  {t('settings.resetUiPreferencesDescription', 'Setzt lokal gespeicherte Filtereinstellungen und Layoutpräferenzen auf Werkseinstellungen zurück.')}
                </p>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => setShowClearStorageConfirm(true)}
              >
                <Trash2 className="w-4 h-4 mr-1" />
                {t('settings.reset', 'Zurücksetzen')}
              </Button>
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-bambu-dark-tertiary">
              <div>
                <p className="text-white font-medium">{t('settings.backupRestore', 'Vollständige Datensicherung')}</p>
                <p className="text-xs text-bambu-gray">
                  {t('settings.backupRestoreDescription', 'Erstellen Sie verschlüsselte Backups oder richten Sie GitHub-Cloud-Synchronisation ein.')}
                </p>
              </div>
              {onTabChange && (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => onTabChange('backup')}
                >
                  <Database className="w-4 h-4 mr-1.5" />
                  {t('settings.goToBackup', 'Zur Datensicherung')}
                  <ArrowRight className="w-3.5 h-3.5 ml-1" />
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Header Info Card */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-bambu-green/10 text-bambu-green shrink-0">
              <Sliders className="w-6 h-6" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-white">
                {t('settings.generalTitle', 'Allgemeine Einstellungen')}
              </h2>
              <p className="text-sm text-bambu-gray">
                {t(
                  'settings.generalSubtitle',
                  'Grundeinstellungen, Erscheinungsbild, Kosten & Abrechnung, Kameraanbindung und Speicherverwaltung übersichtlich gegliedert.'
                )}
              </p>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Sub-tab Navigation */}
      <div
        className="flex items-center gap-1.5 p-1 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary overflow-x-auto"
        role="tablist"
        aria-label="Allgemein Unterbereiche"
      >
        <button
          role="tab"
          aria-selected={activeSubTab === 'basic'}
          onClick={() => handleSubTabChange('basic')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'basic'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <Sliders className="w-4 h-4" />
          <span>{t('settings.subtabs.basic', 'Grundeinstellungen')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'appearance'}
          onClick={() => handleSubTabChange('appearance')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'appearance'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <Palette className="w-4 h-4" />
          <span>{t('settings.subtabs.appearance', 'Erscheinungsbild')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'costs'}
          onClick={() => handleSubTabChange('costs')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'costs'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <DollarSign className="w-4 h-4" />
          <span>{t('settings.subtabs.costs', 'Kosten & Abrechnung')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'camera'}
          onClick={() => handleSubTabChange('camera')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'camera'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <Video className="w-4 h-4" />
          <span>{t('settings.subtabs.camera', 'Kamera & Medien')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'storage'}
          onClick={() => handleSubTabChange('storage')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'storage'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <HardDrive className="w-4 h-4" />
          <span>{t('settings.subtabs.storage', 'Dateien & Speicher')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'all'}
          onClick={() => handleSubTabChange('all')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'all'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <LayoutGrid className="w-4 h-4" />
          <span>{t('common.all', 'Alle')}</span>
        </button>
      </div>

      {/* Subtab Contents */}
      {activeSubTab === 'basic' && (
        <div className="max-w-3xl space-y-6">
          {renderBasicCard()}
        </div>
      )}

      {activeSubTab === 'appearance' && (
        <div className="max-w-4xl space-y-6">
          {renderAppearanceCard()}
        </div>
      )}

      {activeSubTab === 'costs' && (
        <div className="max-w-3xl space-y-6">
          {renderCostsCard()}
        </div>
      )}

      {activeSubTab === 'camera' && (
        <div className="max-w-3xl space-y-6">
          {renderCameraCard()}
        </div>
      )}

      {activeSubTab === 'storage' && (
        <div className="max-w-3xl space-y-6">
          {renderStorageCard()}
        </div>
      )}

      {activeSubTab === 'all' && (
        <div className="space-y-8">
          <div>
            <h3 className="text-sm font-semibold text-bambu-green uppercase tracking-wider mb-3 flex items-center gap-2">
              <Sliders className="w-4 h-4" />
              {t('settings.subtabs.basic', 'Grundeinstellungen')}
            </h3>
            {renderBasicCard()}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-bambu-green uppercase tracking-wider mb-3 flex items-center gap-2">
              <Palette className="w-4 h-4" />
              {t('settings.subtabs.appearance', 'Erscheinungsbild')}
            </h3>
            {renderAppearanceCard()}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-bambu-green uppercase tracking-wider mb-3 flex items-center gap-2">
              <DollarSign className="w-4 h-4" />
              {t('settings.subtabs.costs', 'Kosten & Abrechnung')}
            </h3>
            {renderCostsCard()}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-bambu-green uppercase tracking-wider mb-3 flex items-center gap-2">
              <Video className="w-4 h-4" />
              {t('settings.subtabs.camera', 'Kamera & Medien')}
            </h3>
            {renderCameraCard()}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-bambu-green uppercase tracking-wider mb-3 flex items-center gap-2">
              <HardDrive className="w-4 h-4" />
              {t('settings.subtabs.storage', 'Dateien & Speicher')}
            </h3>
            {renderStorageCard()}
          </div>
        </div>
      )}

      {/* Confirmation Modals */}
      {showClearLogsConfirm && (
        <ConfirmModal
          title={t('settings.clearNotificationLogs', 'Benachrichtigungsprotokolle leeren')}
          message={t('settings.clearLogsMessage', 'Möchten Sie alle Benachrichtigungsprotokolle unwiderruflich aus der Datenbank löschen?')}
          confirmText={t('settings.clearLogs', 'Protokolle leeren')}
          variant="warning"
          onConfirm={async () => {
            setShowClearLogsConfirm(false);
            try {
              const result = await api.clearNotificationLogs(30);
              showToast(result.message || 'Protokolle bereinigt', 'success');
            } catch {
              showToast(t('settings.toast.clearLogsFailed', 'Fehler beim Leeren der Protokolle'), 'error');
            }
          }}
          onCancel={() => setShowClearLogsConfirm(false)}
        />
      )}

      {showClearStorageConfirm && (
        <ConfirmModal
          title={t('settings.resetUiPreferences', 'UI-Einstellungen zurücksetzen')}
          message={t(
            'settings.resetUiPreferencesMessage',
            'Dies löscht Ihre lokalen Filtereinstellungen, Tab-Zustände und gespeicherten Ansichten und lädt die Seite neu.'
          )}
          confirmText={t('settings.resetPreferences', 'Zurücksetzen & Neu laden')}
          variant="default"
          onConfirm={() => {
            setShowClearStorageConfirm(false);
            localStorage.clear();
            showToast(t('settings.toast.uiPreferencesReset', 'UI-Einstellungen zurückgesetzt'), 'success');
            setTimeout(() => window.location.reload(), 800);
          }}
          onCancel={() => setShowClearStorageConfirm(false)}
        />
      )}
    </div>
  );
}

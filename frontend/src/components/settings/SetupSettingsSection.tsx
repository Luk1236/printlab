import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Compass,
  CheckSquare,
  Bot,
  Network,
  ShieldCheck,
  LayoutGrid,
  Layers,
} from 'lucide-react';

import { api } from '../../api/client';
import { useAuth } from '../../contexts/AuthContext';
import { useToast } from '../../contexts/ToastContext';
import { Card, CardHeader, CardContent } from '../Card';
import { Button } from '../Button';
import { QuickSetupHubCard } from '../QuickSetupHubCard';
import { SetupChecklistCard } from '../SetupChecklistCard';
import { AutoSetupCard } from '../AutoSetupCard';
import { AssistantPanel } from '../AssistantPanel';
import { SetupWizardCard } from '../SetupWizardCard';
import { SlicerConnectionCheck } from '../SlicerConnectionCheck';
import { GCode3DPreview } from '../GCode3DPreview';
import { RemoteAccessCard } from '../RemoteAccessCard';
import { AlertChannelsCard } from '../AlertChannelsCard';
import { SelfTestCard } from '../SelfTestCard';
import { PiHealthCard } from '../PiHealthCard';
import { DatabaseMaintenanceCard } from '../DatabaseMaintenanceCard';
import { FactoryResetCard } from '../FactoryResetCard';

export type SetupSubTab = 'checklist' | 'assistant' | 'connections' | 'maintenance' | 'all';

const ANCHOR_SUBTAB_MAP: Record<string, SetupSubTab> = {
  'setup-checklist': 'checklist',
  'card-setup-hub': 'checklist',
  'setup-assistant': 'assistant',
  'auto-setup': 'assistant',
  'setup-wizard': 'assistant',
  'setup-slicer': 'connections',
  'setup-remote': 'connections',
  'setup-alerts': 'connections',
  'setup-selftest': 'maintenance',
  'setup-health': 'maintenance',
  'setup-database': 'maintenance',
  'setup-reset': 'maintenance',
};

export interface SetupSettingsSectionProps {
  printersCount?: number;
  authEnabled?: boolean;
  slicerApiEnabled?: boolean;
  canUpdate?: boolean;
}

export function SetupSettingsSection({
  printersCount: propPrintersCount,
  authEnabled: propAuthEnabled,
  slicerApiEnabled: propSlicerApiEnabled,
  canUpdate = true,
}: SetupSettingsSectionProps) {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { authEnabled: contextAuthEnabled, hasPermission } = useAuth();

  const isAuthEnabled = propAuthEnabled ?? contextAuthEnabled;
  const canControl = !isAuthEnabled || hasPermission('settings:update');

  const [activeSubTab, setActiveSubTab] = useState<SetupSubTab>('checklist');

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  });

  const { data: printers } = useQuery({
    queryKey: ['printers'],
    queryFn: api.getPrinters,
  });

  const { data: setupStatus } = useQuery({
    queryKey: ['setupStatus'],
    queryFn: api.getSetupStatus,
  });

  const enableBillingMutation = useMutation({
    mutationFn: () => api.updateSettings({ billing_enabled: true }),
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated);
      queryClient.invalidateQueries({ queryKey: ['ui-flags'] });
      showToast(t('setupGuide.billingEnabledToast', 'Finanzen & Angebote in der Seitenleiste eingeschaltet.'), 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  // Handle deep-linking to card anchors
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
        el.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
        el.classList.add('ring-2', 'ring-bambu-green');
        window.setTimeout(() => el.classList.remove('ring-2', 'ring-bambu-green'), 1500);
      }
    }, 150);
    return () => window.clearTimeout(timer);
  }, [location.hash]);

  const effectivePrintersCount = propPrintersCount ?? printers?.length ?? 0;
  const effectiveSlicerApiEnabled = propSlicerApiEnabled ?? Boolean(settings?.use_slicer_api);
  const preferredSlicer = settings?.preferred_slicer === 'orcaslicer' ? 'OrcaSlicer' : 'Bambu Studio';
  const slicerUrl =
    settings?.preferred_slicer === 'orcaslicer'
      ? settings?.orcaslicer_api_url
      : settings?.bambu_studio_api_url;

  const checklistProgress = setupStatus ? `${setupStatus.done}/${setupStatus.total}` : null;

  return (
    <div className="space-y-6">
      {/* Intro Header Card */}
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-bambu-green/10 text-bambu-green shrink-0">
                <Compass className="w-6 h-6" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-white">
                  {t('setupWizard.title', 'Einrichtungsassistent & Schnellstart')}
                </h2>
                <p className="text-sm text-bambu-gray">
                  {t(
                    'setupGuide.subtitle',
                    'Schritt-für-Schritt-Inbetriebnahme, Slicer- & Fernzugriffs-Verbindung sowie Systemprüfung sauber gegliedert.'
                  )}
                </p>
              </div>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Sub-tab Navigation */}
      <div
        className="flex items-center gap-1.5 p-1 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary overflow-x-auto"
        role="tablist"
        aria-label="Einrichtung Unterbereiche"
      >
        <button
          role="tab"
          aria-selected={activeSubTab === 'checklist'}
          onClick={() => setActiveSubTab('checklist')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'checklist'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <CheckSquare className="w-4 h-4" />
          <span>{t('setupGuide.tabChecklist', 'Checkliste & Kompass')}</span>
          {checklistProgress && (
            <span
              className={`text-[11px] px-1.5 py-0.5 rounded-full font-mono ${
                activeSubTab === 'checklist'
                  ? 'bg-black/20 text-black font-bold'
                  : 'bg-bambu-dark-tertiary text-bambu-gray-light'
              }`}
            >
              {checklistProgress}
            </span>
          )}
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'assistant'}
          onClick={() => setActiveSubTab('assistant')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'assistant'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <Bot className="w-4 h-4" />
          <span>{t('setupGuide.tabAssistant', 'KI & Schnellstart')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'connections'}
          onClick={() => setActiveSubTab('connections')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'connections'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <Network className="w-4 h-4" />
          <span>{t('setupGuide.tabConnections', 'Verbindungen & Slicer')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'maintenance'}
          onClick={() => setActiveSubTab('maintenance')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeSubTab === 'maintenance'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <ShieldCheck className="w-4 h-4" />
          <span>{t('setupGuide.tabSystem', 'Diagnose & Wartung')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeSubTab === 'all'}
          onClick={() => setActiveSubTab('all')}
          className={`px-3 py-2 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 shrink-0 ml-auto ${
            activeSubTab === 'all'
              ? 'bg-bambu-dark-tertiary text-white'
              : 'text-bambu-gray hover:text-white'
          }`}
          title={t('setupGuide.tabAllTitle', 'Alle Bereiche untereinander anzeigen')}
        >
          <LayoutGrid className="w-3.5 h-3.5" />
          <span>{t('setupGuide.tabAll', 'Alle Bereiche')}</span>
        </button>
      </div>

      {/* 1. Checkliste & Kompass */}
      {(activeSubTab === 'checklist' || activeSubTab === 'all') && (
        <div className="space-y-6">
          <div id="setup-checklist">
            <SetupChecklistCard />
          </div>
          <div id="card-setup-hub">
            <QuickSetupHubCard
              mode="setup"
              printersCount={effectivePrintersCount}
              authEnabled={isAuthEnabled}
              slicerApiEnabled={effectiveSlicerApiEnabled}
              billingEnabled={Boolean(settings?.billing_enabled)}
              onEnableBilling={canControl ? () => enableBillingMutation.mutate() : undefined}
            />
          </div>
        </div>
      )}

      {/* 2. KI & Schnellstart */}
      {(activeSubTab === 'assistant' || activeSubTab === 'all') && (
        <div className="space-y-6">
          <div id="auto-setup">
            <AutoSetupCard />
          </div>
          <div id="setup-assistant">
            <AssistantPanel canConfigure={canControl} isSetupGuide />
          </div>
          <div id="setup-wizard">
            <SetupWizardCard />
          </div>
        </div>
      )}

      {/* 3. Verbindungen: Slicer, Fernzugriff & Meldungen */}
      {(activeSubTab === 'connections' || activeSubTab === 'all') && (
        <div className="space-y-6">
          <div id="setup-slicer" className="space-y-4">
            <Card>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                    <Layers className="w-5 h-5 text-bambu-green" />
                    {t('setupGuide.slicerTitle', 'PC-Slicer & Sidecar-Verbindung')}
                  </h2>
                  <Button size="sm" variant="secondary" onClick={() => navigate('/settings?tab=queue#card-slicer')}>
                    {t('setupGuide.changeSlicerAddress', 'Slicer-Adresse in Workflow ändern')}
                  </Button>
                </div>
                <p className="text-xs text-bambu-gray">
                  {t('setupGuide.preferredSlicer', 'Bevorzugter Slicer')}:{' '}
                  <span className="text-white font-medium">{preferredSlicer}</span> ·{' '}
                  {t('setupGuide.inAppSlicerApi', 'In-App-Slicer-API')}:{' '}
                  <span className={settings?.use_slicer_api ? 'text-bambu-green font-medium' : 'text-bambu-gray'}>
                    {settings?.use_slicer_api
                      ? t('common.enabled', 'Eingeschaltet')
                      : t('common.disabled', 'Aus (Desktop-Übergabe)')}
                  </span>
                  {slicerUrl ? (
                    <>
                      {' '}· Sidecar-Adresse: <span className="font-mono text-white">{slicerUrl}</span>
                    </>
                  ) : null}
                </p>
                <SlicerConnectionCheck />
              </CardContent>
            </Card>
            <GCode3DPreview />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div id="setup-remote">
              <RemoteAccessCard canControl={canControl} />
            </div>
            <div id="setup-alerts">
              <AlertChannelsCard canControl={canControl} />
            </div>
          </div>
        </div>
      )}

      {/* 4. Diagnose, Gerätezustand & Systemprüfung */}
      {(activeSubTab === 'maintenance' || activeSubTab === 'all') && (
        <div className="space-y-6">
          <div id="setup-selftest">
            <SelfTestCard canRun={canControl && canUpdate} />
          </div>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div id="setup-health">
              <PiHealthCard />
            </div>
            <div id="setup-database">
              <DatabaseMaintenanceCard canControl={canControl} />
            </div>
          </div>
          <div id="setup-reset">
            <FactoryResetCard canControl={canControl} />
          </div>
        </div>
      )}
    </div>
  );
}

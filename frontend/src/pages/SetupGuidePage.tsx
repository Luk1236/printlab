import { GCode3DPreview } from '../components/GCode3DPreview';
import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, CheckSquare, Compass, Layers, Network, ShieldCheck, LayoutGrid } from 'lucide-react';

import { api } from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { AlertChannelsCard } from '../components/AlertChannelsCard';
import { AssistantPanel } from '../components/AssistantPanel';
import { AutoSetupCard } from '../components/AutoSetupCard';
import { Button } from '../components/Button';
import { Card, CardContent } from '../components/Card';
import { DatabaseMaintenanceCard } from '../components/DatabaseMaintenanceCard';
import { FactoryResetCard } from '../components/FactoryResetCard';
import { PiHealthCard } from '../components/PiHealthCard';
import { QuickSetupHubCard } from '../components/QuickSetupHubCard';
import { RemoteAccessCard } from '../components/RemoteAccessCard';
import { SelfTestCard } from '../components/SelfTestCard';
import { SetupChecklistCard } from '../components/SetupChecklistCard';
import { SetupWizardCard } from '../components/SetupWizardCard';
import { SlicerConnectionCheck } from '../components/SlicerConnectionCheck';

export type SetupTab = 'assistant' | 'checklist' | 'connections' | 'system' | 'all';

const ANCHOR_TAB_MAP: Record<string, SetupTab> = {
  'setup-assistant': 'assistant',
  'auto-setup': 'assistant',
  'setup-wizard': 'assistant',
  'setup-checklist': 'checklist',
  'card-setup-hub': 'checklist',
  'setup-alerts': 'connections',
  'setup-remote': 'connections',
  'setup-slicer': 'connections',
  'setup-selftest': 'system',
  'setup-health': 'system',
  'setup-database': 'system',
  'setup-reset': 'system',
};

/**
 * Aufgeräumte Inbetriebnahme & Einstellungs-Zentrale:
 * Die Funktionen sind in 4 logische Bereiche unterteilt (KI & Schnellstart, Checkliste & Kompass,
 * Verbindungen, Diagnose & System), sodass nicht mehr 12 Karten auf einmal den Bildschirm überfluten.
 */
export function SetupGuidePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { authEnabled, hasPermission } = useAuth();
  const canControl = !authEnabled || hasPermission('settings:update');

  const paramTab = searchParams.get('tab') as SetupTab | null;
  const initialTab: SetupTab =
    paramTab && ['assistant', 'checklist', 'connections', 'system', 'all'].includes(paramTab)
      ? paramTab
      : 'assistant';

  const [activeTab, setActiveTabState] = useState<SetupTab>(initialTab);

  const setActiveTab = (tab: SetupTab) => {
    setActiveTabState(tab);
    setSearchParams(tab === 'assistant' ? {} : { tab }, { replace: true });
  };

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
      showToast('Finanzen & Angebote in der Seitenleiste eingeschaltet.', 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  useEffect(() => {
    const anchor = location.hash.replace('#', '');
    if (!anchor) return;
    const targetTab = ANCHOR_TAB_MAP[anchor];
    if (targetTab && activeTab !== targetTab && activeTab !== 'all') {
      setActiveTabState(targetTab);
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

  const preferredSlicer = settings?.preferred_slicer === 'orcaslicer' ? 'OrcaSlicer' : 'Bambu Studio';
  const slicerUrl =
    settings?.preferred_slicer === 'orcaslicer'
      ? settings?.orcaslicer_api_url
      : settings?.bambu_studio_api_url;

  const checklistProgress = setupStatus ? `${setupStatus.done}/${setupStatus.total}` : null;

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <Compass className="w-7 h-7 text-bambu-green shrink-0" />
            <h1 className="text-2xl font-bold text-white">{t('setupWizard.title')}</h1>
          </div>
          <p className="text-sm text-bambu-gray mt-1">
            {t('setupGuide.subtitle', 'Schritt-für-Schritt-Inbetriebnahme, Slicer- & Fernzugriffs-Verbindung sowie Systemprüfung sauber gegliedert.')}
          </p>
        </div>
      </div>

      {/* Aufgeräumte Reiter-Navigation */}
      <div
        className="flex items-center gap-1.5 p-1 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary overflow-x-auto"
        role="tablist"
      >
        <button
          role="tab"
          aria-selected={activeTab === 'assistant'}
          onClick={() => setActiveTab('assistant')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeTab === 'assistant'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <Bot className="w-4 h-4" />
          <span>{t('setupGuide.tabAssistant', 'KI & Schnellstart')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeTab === 'checklist'}
          onClick={() => setActiveTab('checklist')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeTab === 'checklist'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <CheckSquare className="w-4 h-4" />
          <span>{t('setupGuide.tabChecklist', 'Checkliste & Kompass')}</span>
          {checklistProgress && (
            <span
              className={`text-[11px] px-1.5 py-0.5 rounded-full font-mono ${
                activeTab === 'checklist' ? 'bg-black/20 text-black font-bold' : 'bg-bambu-dark-tertiary text-bambu-gray-light'
              }`}
            >
              {checklistProgress}
            </span>
          )}
        </button>

        <button
          role="tab"
          aria-selected={activeTab === 'connections'}
          onClick={() => setActiveTab('connections')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeTab === 'connections'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <Network className="w-4 h-4" />
          <span>{t('setupGuide.tabConnections', 'Verbindungen & Slicer')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeTab === 'system'}
          onClick={() => setActiveTab('system')}
          className={`px-3.5 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2 shrink-0 ${
            activeTab === 'system'
              ? 'bg-bambu-green text-black font-semibold shadow'
              : 'text-bambu-gray hover:text-white hover:bg-bambu-dark'
          }`}
        >
          <ShieldCheck className="w-4 h-4" />
          <span>{t('setupGuide.tabSystem', 'Diagnose & Zustand')}</span>
        </button>

        <button
          role="tab"
          aria-selected={activeTab === 'all'}
          onClick={() => setActiveTab('all')}
          className={`px-3 py-2 rounded-lg text-xs font-medium transition-all flex items-center gap-1.5 shrink-0 ml-auto ${
            activeTab === 'all'
              ? 'bg-bambu-dark-tertiary text-white'
              : 'text-bambu-gray hover:text-white'
          }`}
          title="Alle Bereiche untereinander anzeigen"
        >
          <LayoutGrid className="w-3.5 h-3.5" />
          <span>{t('setupGuide.tabAll', 'Alle Bereiche')}</span>
        </button>
      </div>

      {/* 1. KI & Schnellstart */}
      {(activeTab === 'assistant' || activeTab === 'all') && (
        <div className="space-y-6">
          <AutoSetupCard />
          <div id="setup-assistant">
            <AssistantPanel canConfigure={canControl} isSetupGuide />
          </div>
          <div id="setup-wizard">
            <SetupWizardCard />
          </div>
        </div>
      )}

      {/* 2. Checkliste & Einstellungs-Kompass */}
      {(activeTab === 'checklist' || activeTab === 'all') && (
        <div className="space-y-6">
          <div id="setup-checklist">
            <SetupChecklistCard />
          </div>
          <div id="card-setup-hub">
            <QuickSetupHubCard
              mode="setup"
              printersCount={printers?.length}
              authEnabled={authEnabled}
              slicerApiEnabled={Boolean(settings?.use_slicer_api)}
              billingEnabled={Boolean(settings?.billing_enabled)}
              onEnableBilling={canControl ? () => enableBillingMutation.mutate() : undefined}
            />
          </div>
        </div>
      )}

      {/* 3. Verbindungen: Slicer, Fernzugriff & Meldungen */}
      {(activeTab === 'connections' || activeTab === 'all') && (
        <div className="space-y-6">
          <div id="setup-slicer" className="space-y-4">
            <Card>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                    <Layers className="w-5 h-5 text-bambu-green" />
                    PC-Slicer &amp; Sidecar-Verbindung
                  </h2>
                  <Button size="sm" variant="secondary" onClick={() => navigate('/settings?tab=queue#card-slicer')}>
                    Slicer-Adresse in Einstellungen ändern
                  </Button>
                </div>
                <p className="text-xs text-bambu-gray">
                  Bevorzugter Slicer: <span className="text-white font-medium">{preferredSlicer}</span> ·{' '}
                  In-App-Slicer-API:{' '}
                  <span className={settings?.use_slicer_api ? 'text-bambu-green font-medium' : 'text-bambu-gray'}>
                    {settings?.use_slicer_api ? 'Eingeschaltet' : 'Aus (Desktop-Übergabe)'}
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
      {(activeTab === 'system' || activeTab === 'all') && (
        <div className="space-y-6">
          <div id="setup-selftest">
            <SelfTestCard canRun={canControl} />
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

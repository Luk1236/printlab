import { useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Compass, Layers } from 'lucide-react';

import { api } from '../api/client';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { AlertChannelsCard } from '../components/AlertChannelsCard';
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

/**
 * Einrichtung an einem Ort: der Assistent führt Punkt für Punkt durch die offenen Schritte, die Checkliste zeigt den
 * Gesamtstand, der Einstellungs-Kompass bündelt alle 6 Konfigurationsbereiche, und darunter lassen sich Slicer,
 * Ausfall-Meldungen, Tailscale-Fernzugriff und Systemprüfung direkt auf dieser Seite bedienen.
 */
export function SetupGuidePage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { authEnabled, hasPermission } = useAuth();
  const canControl = !authEnabled || hasPermission('settings:update');

  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  });

  const { data: printers } = useQuery({
    queryKey: ['printers'],
    queryFn: api.getPrinters,
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

  return (
    <div className="p-4 md:p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <Compass className="w-7 h-7 text-bambu-green shrink-0" />
            <h1 className="text-2xl font-bold text-white">{t('setupWizard.title')}</h1>
          </div>
          <p className="text-sm text-bambu-gray mt-1">
            Schritt-für-Schritt-Inbetriebnahme, Direktzugriff auf alle PrintLab- &amp; P2S-Einstellungen sowie Systemprüfung an einem Ort.
          </p>
        </div>
      </div>

      {/* 1. Automatische Einrichtung, Assistent & Checkliste */}
      <AutoSetupCard />
      <SetupWizardCard />
      <SetupChecklistCard />

      {/* 2. Zentraler Einstellungs-Kompass (alle 6 Bereiche im Überblick) */}
      <QuickSetupHubCard
        mode="setup"
        printersCount={printers?.length}
        authEnabled={authEnabled}
        slicerApiEnabled={Boolean(settings?.use_slicer_api)}
        billingEnabled={Boolean(settings?.billing_enabled)}
        onEnableBilling={canControl ? () => enableBillingMutation.mutate() : undefined}
      />

      {/* 3. Direkt-Einrichtung: Slicer, Ausfall-Meldungen & Fernzugriff */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div id="setup-alerts">
          <AlertChannelsCard canControl={canControl} />
        </div>
        <div id="setup-remote">
          <RemoteAccessCard canControl={canControl} />
        </div>
      </div>

      <div id="setup-slicer">
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
      </div>

      {/* 4. Systemprüfung, Gerätezustand, Datenbank & Werkseinstellungen */}
      <div id="setup-selftest">
        <SelfTestCard canRun={canControl} />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PiHealthCard />
        <DatabaseMaintenanceCard canControl={canControl} />
      </div>
      <div id="setup-reset">
        <FactoryResetCard canControl={canControl} />
      </div>
    </div>
  );
}

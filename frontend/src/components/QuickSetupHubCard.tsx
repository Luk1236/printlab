import { useNavigate } from 'react-router-dom';
import {
  BellRing,
  Bot,
  CheckCircle2,
  Compass,
  Cpu,
  DollarSign,
  ExternalLink,
  Layers,
  Printer,
  Settings,
  Wrench,
} from 'lucide-react';

import { Button } from './Button';
import { Card, CardContent } from './Card';

export interface QuickSetupHubProps {
  /** 'setup' auf /einrichtung, 'settings' auf /settings */
  mode: 'setup' | 'settings';
  /** Anzahl angelegter Drucker (optional, für Status-Anzeige) */
  printersCount?: number;
  /** Ist die Benutzer-Anmeldung aktiv? */
  authEnabled?: boolean;
  /** Ist Slicer-Sidecar-API eingeschaltet? */
  slicerApiEnabled?: boolean;
  /** Ist die Abrechnung / Finanzen in der Seitenleiste eingeschaltet? */
  billingEnabled?: boolean;
  /** Direkt-Umschalter auf der Einstellungsseite, um Finanzen/Angebote einzuschalten */
  onEnableBilling?: () => void;
  /** Direkt-Sprung zu einem Einstellungs-Reiter + Karten-Anker, wenn bereits auf /settings */
  onJumpSettingsTab?: (tab: string, anchor?: string) => void;
}

function scrollToId(id: string): boolean {
  const el = document.getElementById(id);
  if (!el) return false;
  el.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  el.classList.add('ring-2', 'ring-bambu-green');
  window.setTimeout(() => el.classList.remove('ring-2', 'ring-bambu-green'), 1500);
  return true;
}

/**
 * Zentraler Einstellungs-Kompass & P2S-Werkstatt-Überblick.
 * Bündelt alle verstreuten Einrichtungs- und Einstellungsbereiche (Drucker, Slicer,
 * P2S-Mechanik/Kamera, Ausfall-Meldungen/Tailscale, Lokale KI und Finanzen/XRechnung)
 * übersichtlich an einem Ort.
 */
export function QuickSetupHubCard({
  mode,
  printersCount,
  authEnabled,
  slicerApiEnabled,
  billingEnabled,
  onEnableBilling,
  onJumpSettingsTab,
}: QuickSetupHubProps) {
  const navigate = useNavigate();

  const goSettings = (tab: string, anchor?: string) => {
    if (mode === 'settings' && onJumpSettingsTab) {
      onJumpSettingsTab(tab, anchor);
      return;
    }
    const query = tab === 'general' ? '' : `?tab=${tab}`;
    const hash = anchor ? `#${anchor}` : '';
    navigate(`/settings${query}${hash}`);
  };

  const goAnchorOrRoute = (anchor: string, fallbackRoute: string) => {
    if (scrollToId(anchor)) return;
    navigate(fallbackRoute);
  };

  return (
    <Card id="card-setup-hub">
      <CardContent className="space-y-4" data-testid="quick-setup-hub">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-bambu-dark-tertiary pb-3">
          <div>
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <Compass className="w-5 h-5 text-bambu-green shrink-0" />
              Einstellungs-Kompass &amp; P2S-Werkstatt
            </h2>
            <p className="text-xs text-bambu-gray mt-0.5">
              Alle wichtigen Einrichtungs- und Konfigurationsbereiche geordnet im Direktzugriff — ohne langes Suchen in Unterreitern.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {mode === 'settings' ? (
              <Button size="sm" variant="secondary" onClick={() => navigate('/einrichtung')}>
                <Compass className="w-3.5 h-3.5" />
                Einrichtungsassistent &amp; Checkliste
              </Button>
            ) : (
              <Button size="sm" variant="secondary" onClick={() => navigate('/settings')}>
                <Settings className="w-3.5 h-3.5" />
                Alle Detail-Einstellungen
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={() => navigate('/maintenance?tab=hardware')}>
              <Wrench className="w-3.5 h-3.5" />
              Hardware &amp; Kalibrierung
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {/* 1. Drucker, LAN & Zugangsschutz */}
          <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3.5 flex flex-col justify-between space-y-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white flex items-center gap-2">
                  <Printer className="w-4 h-4 text-bambu-green shrink-0" />
                  1. Drucker, LAN &amp; Zugang
                </span>
                {typeof printersCount === 'number' && (
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full ${
                      printersCount > 0 ? 'bg-bambu-green/15 text-bambu-green' : 'bg-amber-500/15 text-amber-400'
                    }`}
                  >
                    {printersCount > 0 ? `${printersCount} Drucker` : 'Kein Drucker'}
                  </span>
                )}
              </div>
              <p className="text-xs text-bambu-gray">
                Drucker per IP, Seriennummer &amp; Zugangscode verbinden, Benutzer-Anmeldung schützen und Netzwerk-Adresse festlegen.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button size="sm" onClick={() => navigate('/')}>
                Drucker verwalten
              </Button>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => (authEnabled === false ? navigate('/setup') : goSettings('users', 'card-currentuser'))}
              >
                Benutzer &amp; Passwort
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goSettings('network', 'card-externalurl')}>
                LAN &amp; Externe URL
              </Button>
            </div>
          </div>

          {/* 2. PC-Slicer & Druckablauf */}
          <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3.5 flex flex-col justify-between space-y-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white flex items-center gap-2">
                  <Layers className="w-4 h-4 text-bambu-green shrink-0" />
                  2. PC-Slicer &amp; Druckablauf
                </span>
                {typeof slicerApiEnabled === 'boolean' && (
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full ${
                      slicerApiEnabled ? 'bg-bambu-green/15 text-bambu-green' : 'bg-bambu-dark-tertiary text-bambu-gray'
                    }`}
                  >
                    {slicerApiEnabled ? 'Sidecar aktiv' : 'Desktop-Übergabe'}
                  </span>
                )}
              </div>
              <p className="text-xs text-bambu-gray">
                Bambu Studio / OrcaSlicer Sidecar-Adresse eintragen und prüfen, virtuellen Netzwerkdrucker sowie Vorheizen &amp; Trocknung einstellen.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button size="sm" onClick={() => goSettings('queue', 'card-slicer')}>
                Slicer-Adresse &amp; Test
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goSettings('virtual-printer', 'card-vp')}>
                Virtueller Drucker
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goSettings('queue', 'card-print-options')}>
                Druck-Optionen &amp; Soak
              </Button>
            </div>
          </div>

          {/* 3. P2S-Mechanik, Plattenwechsler & Kamera */}
          <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3.5 flex flex-col justify-between space-y-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white flex items-center gap-2">
                  <Cpu className="w-4 h-4 text-bambu-green shrink-0" />
                  3. P2S-Mechanik &amp; Kamera
                </span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-bambu-dark-tertiary text-bambu-gray">
                  Hardware &amp; Optik
                </span>
              </div>
              <p className="text-xs text-bambu-gray">
                Tür &amp; Plattenwechsler (Simulation oder GPIO), 5-Schritte-Einmess-Assistent, Leerbett-Kamera-Kalibrierung und Wartungsprogramme.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button size="sm" onClick={() => navigate('/maintenance?tab=hardware#hw-admin')}>
                Tür &amp; Plattenwechsler
              </Button>
              <Button size="sm" variant="secondary" onClick={() => navigate('/maintenance?tab=hardware#hw-wizard')}>
                Einmess-Assistent
              </Button>
              <Button size="sm" variant="secondary" onClick={() => navigate('/maintenance?tab=hardware#hw-tuning')}>
                Kamera einmessen
              </Button>
            </div>
          </div>

          {/* 4. Ausfall-Meldungen, Tailscale & System */}
          <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3.5 flex flex-col justify-between space-y-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white flex items-center gap-2">
                  <BellRing className="w-4 h-4 text-bambu-green shrink-0" />
                  4. Ausfall-Meldung &amp; Fernzugriff
                </span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-bambu-dark-tertiary text-bambu-gray">
                  Pi &amp; Betrieb
                </span>
              </div>
              <p className="text-xs text-bambu-gray">
                Telegram / ntfy für Systemwarnungen, privater Fernzugriff über Tailscale (inkl. HTTPS &amp; QR-Code), Selbsttest und Sicherungen.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button size="sm" onClick={() => goAnchorOrRoute('setup-alerts', '/einrichtung#setup-alerts')}>
                Ausfall-Meldungen
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goAnchorOrRoute('setup-remote', '/einrichtung#setup-remote')}>
                Tailscale-Fernzugriff
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goAnchorOrRoute('setup-selftest', '/einrichtung#setup-selftest')}>
                Systemprüfung
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goSettings('backup', 'card-backup')}>
                Sicherungen
              </Button>
            </div>
          </div>

          {/* 5. Lokaler KI-Assistent (Ollama) & Fehlerhilfe */}
          <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3.5 flex flex-col justify-between space-y-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white flex items-center gap-2">
                  <Bot className="w-4 h-4 text-bambu-green shrink-0" />
                  5. Lokale KI (Ollama) &amp; Fehlerhilfe
                </span>
                <span className="text-[11px] px-2 py-0.5 rounded-full bg-bambu-dark-tertiary text-bambu-gray">
                  Lokal &amp; Offline
                </span>
              </div>
              <p className="text-xs text-bambu-gray">
                Lokales Sprach- und Bildmodell (Ollama) verbinden, Fragen zum Betrieb stellen, Fehlerbilder prüfen und Gegenmaßnahmen regeln.
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button size="sm" onClick={() => navigate('/maintenance?tab=assistant')}>
                KI-Assistent (Ollama)
              </Button>
              <Button size="sm" variant="secondary" onClick={() => navigate('/fehlerhilfe')}>
                Fehlerhilfe &amp; Bild-KI
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goSettings('failure-detection', 'card-fd-ml')}>
                Obico-Überwachung
              </Button>
            </div>
          </div>

          {/* 6. Finanzen, Angebote, Firmenprofil & XRechnung */}
          <div className="rounded-lg border border-bambu-dark-tertiary bg-bambu-dark p-3.5 flex flex-col justify-between space-y-3">
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-white flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-bambu-green shrink-0" />
                  6. Angebote, Firma &amp; XRechnung
                </span>
                {typeof billingEnabled === 'boolean' && (
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full flex items-center gap-1 ${
                      billingEnabled ? 'bg-bambu-green/15 text-bambu-green' : 'bg-amber-500/15 text-amber-400'
                    }`}
                  >
                    {billingEnabled && <CheckCircle2 className="w-3 h-3" />}
                    {billingEnabled ? 'In Seitenleiste aktiv' : 'In Seitenleiste aus'}
                  </span>
                )}
              </div>
              <p className="text-xs text-bambu-gray">
                Firmendaten, Steuernummer/IBAN, Angebotskalkulator mit Kunden-Freigabelink, Rechnungen und XRechnung 3.0 (EN 16931).
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {billingEnabled === false && onEnableBilling && (
                <Button size="sm" onClick={onEnableBilling}>
                  Finanzen-Menü einschalten
                </Button>
              )}
              <Button size="sm" variant={billingEnabled === false && onEnableBilling ? 'secondary' : 'primary'} onClick={() => navigate('/finance')}>
                <ExternalLink className="w-3.5 h-3.5" />
                Angebote &amp; Firmendaten
              </Button>
              <Button size="sm" variant="secondary" onClick={() => goSettings('general', 'card-cost')}>
                Strom- &amp; Materialpreis
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Settings search registry.
//
// Each settings card/section registers itself at module-import time by calling
// `registerSettingsSearch(...)` at module scope (NOT inside a component).
// SettingsPage reads the accumulated registry to power its cross-tab search.
//
// Convention: co-locate the registration call with the component/section that
// owns the `anchor` id. When you add a new settings card, add one call here
// next to it — no central index to forget to update.

export type SettingsSearchTab =
  | 'general'
  | 'setup'
  | 'system'
  | 'updates'
  | 'plugs'
  | 'sensors'
  | 'notifications'
  | 'queue'
  | 'filament'
  | 'network'
  | 'apikeys'
  | 'virtual-printer'
  | 'spoolbuddy'
  | 'users'
  | 'backup'
  | 'failure-detection';

export type SettingsSearchSubTab = 'users' | 'email' | 'ldap' | 'oidc' | 'twofa' | 'security';

export type UsersSubTab = SettingsSearchSubTab;

export interface SettingsSearchEntry {
  /** i18n key for the label. Resolved with t() at render time. */
  labelKey: string;
  /** Fallback label if the i18n key is missing. */
  labelFallback?: string;
  tab: SettingsSearchTab;
  subTab?: SettingsSearchSubTab;
  /** Optional external route (e.g. '/einrichtung', '/maintenance?tab=hardware#hw-admin', '/finance'). */
  route?: string;
  /** Optional subtitle shown in search dropdown for external routes. */
  routeLabel?: string;
  /** Space-separated extra search terms (lowercase). */
  keywords: string;
  /** DOM id attached to the target card — used for scrollIntoView. */
  anchor: string;
}

const entries = new Map<string, SettingsSearchEntry>();

export function registerSettingsSearch(entry: SettingsSearchEntry): void {
  entries.set(entry.anchor, entry);
}

export function getSettingsSearchEntries(): SettingsSearchEntry[] {
  return Array.from(entries.values());
}

/**
 * Registriert alle Standard-Einstellungskarten sowie die übergreifenden
 * PrintLab-/P2S-Einrichtungs- und Werkstattbereiche für die globale Suche.
 */
export function registerCoreSettingsSearchEntries(): void {
  registerSettingsSearch({ labelKey: 'settings.general', tab: 'general', keywords: 'language date time format printer model printers cards sprache datum uhrzeit', anchor: 'card-general' });
  registerSettingsSearch({ labelKey: 'settings.appearance', tab: 'general', keywords: 'theme dark light mode colors design dunkel hell farben', anchor: 'card-appearance' });
  registerSettingsSearch({ labelKey: 'settings.archiveSettings', tab: 'general', keywords: 'archive auto save thumbnails captures archiv vorschaubilder abschlussfoto', anchor: 'card-archive' });
  registerSettingsSearch({ labelKey: 'settings.camera', tab: 'general', keywords: 'camera external video stream kamera extern', anchor: 'card-camera' });
  registerSettingsSearch({ labelKey: 'settings.costTracking', tab: 'general', keywords: 'currency filament cost energy kwh price billing abrechnung finanzen strompreis währung', anchor: 'card-cost' });
  registerSettingsSearch({ labelKey: 'settings.fileManager', tab: 'general', keywords: 'file manager archive mode disk warning storage dateimanager speicherplatz', anchor: 'card-filemanager' });
  registerSettingsSearch({ labelKey: 'setupWizard.title', labelFallback: 'Setup & Assistant', tab: 'setup', keywords: 'setup wizard assistant checklist selftest slicer erstinstallation assistent kompass einrichtung', anchor: 'card-setup-hub' });
  registerSettingsSearch({ labelKey: 'nav.systemStatus', labelFallback: 'System Status', tab: 'system', keywords: 'system status health cpu ram memory disk logs diagnose bundle supportprotokoll gesundheit diagnose', anchor: 'card-system' });
  registerSettingsSearch({ labelKey: 'settings.updates', tab: 'updates', keywords: 'updates version firmware beta check aktualisierung release', anchor: 'card-updates' });
  registerSettingsSearch({ labelKey: 'settings.dataManagement', tab: 'backup', keywords: 'data reset clear logs notifications preferences datenverwaltung speicher vacuum bereinigung', anchor: 'card-data' });
  registerSettingsSearch({ labelKey: 'settings.smartPlugs', tab: 'plugs', keywords: 'smart plug energy power automation tapo kasa tplink shelly tasmota steckdose strom', anchor: 'card-plugs' });
  registerSettingsSearch({ labelKey: 'haSensors.sectionTitle', tab: 'sensors', keywords: 'home assistant sensor printer temperature humidity alert notify block print', anchor: 'card-ha-sensors' });
  registerSettingsSearch({ labelKey: 'locationHaSensors.sectionTitle', tab: 'sensors', keywords: 'home assistant sensor location storage box temperature humidity battery alert notify', anchor: 'card-location-sensors' });
  registerSettingsSearch({ labelKey: 'settings.providers', tab: 'notifications', keywords: 'telegram discord email notification providers webhook benachrichtigungen', anchor: 'card-providers' });
  registerSettingsSearch({ labelKey: 'settings.messageTemplates', tab: 'notifications', keywords: 'message templates notification text edit vorlagen', anchor: 'card-templates' });
  registerSettingsSearch({ labelKey: 'settings.defaultPrintOptions', labelFallback: 'Default Print Options', tab: 'queue', keywords: 'print bed leveling flow calibration vibration first layer timelapse druckoptionen nivellierung', anchor: 'card-print-options' });
  registerSettingsSearch({ labelKey: 'settings.tempFanPresetsTitle', labelFallback: 'Temperature & Fan Presets', tab: 'queue', keywords: 'temperature fan presets nozzle bed chamber quick buttons popover lüfter temperatur', anchor: 'card-temp-fan-presets' });
  registerSettingsSearch({ labelKey: 'settings.staggeredStart', labelFallback: 'Staggered Start', tab: 'queue', keywords: 'staggered batch delay start queue group versetzter start', anchor: 'card-staggered' });
  registerSettingsSearch({ labelKey: 'settings.plateClear', labelFallback: 'Plate-Clear Confirmation', tab: 'queue', keywords: 'plate clear confirm auto queue druckplatte freigabe warmhalten preheat soak vorheizen', anchor: 'card-plate' });
  registerSettingsSearch({ labelKey: 'settings.concurrentUploadsTitle', labelFallback: 'Concurrent Uploads', tab: 'queue', keywords: 'concurrent parallel upload transfer ftp queue slow farm simultaneous', anchor: 'card-concurrent-uploads' });
  registerSettingsSearch({ labelKey: 'settings.gcodeInjection', labelFallback: 'G-code Injection', tab: 'queue', keywords: 'gcode injection start end autoprint farmloop swapmod autoclear printflow', anchor: 'card-gcode' });
  registerSettingsSearch({ labelKey: 'settings.slicerCard', labelFallback: 'Slicer', tab: 'queue', keywords: 'slicer orcaslicer bambustudio orca bambu api sidecar url docker preferred pc verbindung prüfen', anchor: 'card-slicer' });
  registerSettingsSearch({ labelKey: 'settings.queueDrying', tab: 'queue', keywords: 'drying presets temperature time humidity ams trocknung luftfeuchtigkeit', anchor: 'card-drying' });
  registerSettingsSearch({ labelKey: 'settings.filamentChecks', tab: 'filament', keywords: 'filament check warning runout remaining warnung', anchor: 'card-filamentchecks' });
  registerSettingsSearch({ labelKey: 'settings.printModal', tab: 'filament', keywords: 'print modal custom mapping druckdialog', anchor: 'card-printmodal' });
  registerSettingsSearch({ labelKey: 'settings.amsDisplayThresholds', tab: 'filament', keywords: 'ams humidity temperature threshold history retention schwellenwerte', anchor: 'card-amsthresholds' });
  registerSettingsSearch({ labelKey: 'settings.externalUrl', tab: 'network', keywords: 'external url reverse proxy public notification link externe adresse', anchor: 'card-externalurl' });
  registerSettingsSearch({ labelKey: 'settings.ftpRetry', tab: 'network', keywords: 'ftp retry upload retries backoff', anchor: 'card-ftpretry' });
  registerSettingsSearch({ labelKey: 'settings.homeAssistant', tab: 'network', keywords: 'home assistant ha hass mqtt integration', anchor: 'card-ha' });
  registerSettingsSearch({ labelKey: 'settings.mqttPublishing', tab: 'network', keywords: 'mqtt publish broker topic', anchor: 'card-mqtt' });
  registerSettingsSearch({ labelKey: 'settings.prometheusMetrics', tab: 'network', keywords: 'prometheus metrics grafana monitoring bearer token', anchor: 'card-prometheus' });
  registerSettingsSearch({ labelKey: 'settings.createNewApiKey', tab: 'apikeys', keywords: 'api key create permission scope schlüssel', anchor: 'card-createapi' });
  registerSettingsSearch({ labelKey: 'settings.webhookEndpoints', tab: 'apikeys', keywords: 'webhook endpoint post http', anchor: 'card-webhooks' });
  registerSettingsSearch({ labelKey: 'settings.apiBrowser', tab: 'apikeys', keywords: 'api browser endpoint documentation test', anchor: 'card-apibrowser' });
  registerSettingsSearch({ labelKey: 'connectedApps.title', tab: 'apikeys', keywords: 'connected app sign in single sign-on sso oauth login orders verbundene apps', anchor: 'card-connected-apps' });
  registerSettingsSearch({ labelKey: 'cameraTokens.title', tab: 'apikeys', keywords: 'camera token long-lived home assistant frigate kiosk stream camwall overlay', anchor: 'card-camera-tokens' });
  registerSettingsSearch({ labelKey: 'settings.tabs.virtualPrinter', tab: 'virtual-printer', keywords: 'virtual printer proxy archive slicer bambustudio orcaslicer ip bind virtueller drucker', anchor: 'card-vp' });
  registerSettingsSearch({ labelKey: 'settings.tabs.spoolbuddy', tab: 'spoolbuddy', keywords: 'spoolbuddy device scale nfc rfid kiosk unregister waage', anchor: 'card-spoolbuddy' });
  registerSettingsSearch({ labelKey: 'settings.currentUser', tab: 'users', subTab: 'users', keywords: 'current user profile password change passwort ändern benutzer', anchor: 'card-currentuser' });
  registerSettingsSearch({ labelKey: 'settings.users', tab: 'users', subTab: 'users', keywords: 'users accounts list benutzerkonten anmeldung', anchor: 'card-users' });
  registerSettingsSearch({ labelKey: 'settings.groups', tab: 'users', subTab: 'users', keywords: 'groups roles permissions administrators operators viewers gruppen berechtigungen', anchor: 'card-groups' });
  registerSettingsSearch({ labelKey: 'settings.sessionPolicy.title', labelFallback: 'Session Policy', tab: 'users', subTab: 'users', keywords: 'session timeout expiry logout remember me jwt token lifetime sitzung', anchor: 'card-session-policy' });
  registerSettingsSearch({ labelKey: 'settings.email.smtpSettings', labelFallback: 'SMTP Configuration', tab: 'users', subTab: 'email', keywords: 'smtp email send server port password auth starttls ssl', anchor: 'card-smtp' });
  registerSettingsSearch({ labelKey: 'settings.ldap.title', labelFallback: 'LDAP Authentication', tab: 'users', subTab: 'ldap', keywords: 'ldap active directory ad authentication bind dn search base group mapping', anchor: 'card-ldap' });
  registerSettingsSearch({ labelKey: 'settings.tabs.backup', tab: 'backup', keywords: 'backup github restore download cloud sync profiles archives sicherung wiederherstellen', anchor: 'card-backup' });
  registerSettingsSearch({ labelKey: 'externalLinks.sidebarLayout', labelFallback: 'Sidebar', tab: 'general', keywords: 'sidebar layout links pages hide show external custom navigation url add seitenleiste', anchor: 'card-sidebar-links' });
  registerSettingsSearch({ labelKey: 'settings.filamentTracking', tab: 'filament', keywords: 'spoolman filament tracking inventory sync remote integration bestand', anchor: 'card-spoolman' });
  registerSettingsSearch({ labelKey: 'settings.catalog.spoolCatalog', labelFallback: 'Spool Catalog', tab: 'filament', keywords: 'spool catalog entries brand material reset import export spulenkatalog', anchor: 'card-spool-catalog' });
  registerSettingsSearch({ labelKey: 'settings.colorCatalog.title', labelFallback: 'Color Catalog', tab: 'filament', keywords: 'color catalog hex swatch palette sync reset farbkatalog', anchor: 'card-color-catalog' });
  registerSettingsSearch({ labelKey: 'settings.tabs.failureDetection', labelFallback: 'Failure Detection', tab: 'failure-detection', keywords: 'failure detection ai ml obico spaghetti detect monitoring fehlererkennung', anchor: 'card-fd-ml' });
  registerSettingsSearch({ labelKey: 'failureDetection.perPrinterTitle', labelFallback: 'Per-Printer Settings', tab: 'failure-detection', keywords: 'failure detection per printer enable per-printer sensitivity', anchor: 'card-fd-perprinter' });
  registerSettingsSearch({ labelKey: 'failureDetection.statusTitle', labelFallback: 'Detection Status', tab: 'failure-detection', keywords: 'failure detection status running connection', anchor: 'card-fd-status' });
  registerSettingsSearch({ labelKey: 'failureDetection.historyTitle', labelFallback: 'Detection History', tab: 'failure-detection', keywords: 'failure detection history log events', anchor: 'card-fd-history' });
  registerSettingsSearch({ labelKey: 'settings.email.advancedAuth', labelFallback: 'Advanced Email Authentication', tab: 'users', subTab: 'email', keywords: 'email authentication advanced password reset self-service forgot', anchor: 'card-email-advanced-auth' });
  registerSettingsSearch({ labelKey: 'settings.email.testConnection', labelFallback: 'Test SMTP Connection', tab: 'users', subTab: 'email', keywords: 'email smtp test connection send check', anchor: 'card-email-test' });
  registerSettingsSearch({ labelKey: 'settings.twoFa.totpTitle', labelFallback: 'Authenticator App (TOTP)', tab: 'users', subTab: 'twofa', keywords: 'two factor 2fa totp authenticator app google authy otp', anchor: 'card-2fa-totp' });
  registerSettingsSearch({ labelKey: 'settings.twoFa.emailOtpTitle', labelFallback: 'Email One-Time Codes', tab: 'users', subTab: 'twofa', keywords: 'two factor 2fa email otp one time code', anchor: 'card-2fa-emailotp' });
  registerSettingsSearch({ labelKey: 'settings.twoFa.linkedAccounts', labelFallback: 'Linked Accounts', tab: 'users', subTab: 'twofa', keywords: 'two factor 2fa linked accounts sso oidc provider google github', anchor: 'card-2fa-linked' });
  registerSettingsSearch({ labelKey: 'settings.oidc.title', labelFallback: 'Single Sign-On (OIDC)', tab: 'users', subTab: 'oidc', keywords: 'sso oidc openid single sign-on pocketid authentik keycloak google okta azure provider', anchor: 'card-oidc' });
  registerSettingsSearch({ labelKey: 'settings.ldap.serverConfig', labelFallback: 'LDAP Server Configuration', tab: 'users', subTab: 'ldap', keywords: 'ldap server url bind dn user search base group filter tls', anchor: 'card-ldap-server' });
  registerSettingsSearch({ labelKey: 'backup.githubBackup', labelFallback: 'GitHub Backup', tab: 'backup', keywords: 'github backup cloud remote sync profiles token', anchor: 'card-backup-github' });
  registerSettingsSearch({ labelKey: 'backup.history', labelFallback: 'Backup History', tab: 'backup', keywords: 'backup history log runs github commits', anchor: 'card-backup-history' });
  registerSettingsSearch({ labelKey: 'backup.localBackup', labelFallback: 'Local Backup', tab: 'backup', keywords: 'local backup download zip manual export', anchor: 'card-backup-local' });
  registerSettingsSearch({ labelKey: 'backup.scheduledBackup', labelFallback: 'Scheduled Backups', tab: 'backup', keywords: 'scheduled backup automatic hourly daily weekly retention local path', anchor: 'card-backup-scheduled' });

  // Übergreifende PrintLab- & P2S-Einstellungsbereiche (Einrichtung, Wartung, Finanzen)
  registerSettingsSearch({
    labelKey: 'setupWizard.title',
    labelFallback: 'Einrichtungsassistent & Checkliste',
    tab: 'general',
    route: '/einrichtung',
    routeLabel: 'Einrichtung (/einrichtung)',
    keywords: 'einrichtung inbetriebnahme checkliste assistent auto setup erstinstallation raspberry pi start',
    anchor: 'ext-setup-guide',
  });
  registerSettingsSearch({
    labelKey: 'alertChannels.title',
    labelFallback: 'Meldung bei Ausfall (Telegram / ntfy)',
    tab: 'general',
    route: '/einrichtung#setup-alerts',
    routeLabel: 'Einrichtung › Meldung bei Ausfall',
    keywords: 'ausfall meldeweg telegram botfather ntfy warnung alarm benachrichtigung pi überwachung',
    anchor: 'ext-setup-alerts',
  });
  registerSettingsSearch({
    labelKey: 'remoteAccess.title',
    labelFallback: 'Fernzugriff (Tailscale & HTTPS)',
    tab: 'general',
    route: '/einrichtung#setup-remote',
    routeLabel: 'Einrichtung › Fernzugriff (Tailscale)',
    keywords: 'fernzugriff tailscale vpn https zertifikat qr code unterwegs mobil handy',
    anchor: 'ext-setup-remote',
  });
  registerSettingsSearch({
    labelKey: 'selfTest.title',
    labelFallback: 'Systemprüfung & Pi-Gerätezustand',
    tab: 'general',
    route: '/einrichtung#setup-selftest',
    routeLabel: 'Einrichtung › Systemprüfung',
    keywords: 'systemprüfung selbsttest selftest pi zustand temperatur unterspannung ssd sd karte prüfung',
    anchor: 'ext-setup-selftest',
  });
  registerSettingsSearch({
    labelKey: 'hardwareAdmin.title',
    labelFallback: 'Tür, Plattenwechsler & Magazin (P2S)',
    tab: 'general',
    route: '/maintenance?tab=hardware#hw-admin',
    routeLabel: 'Wartung › Hardware & Optik',
    keywords: 'tür plattenwechsel plattenwechsler magazin servo gpio not-halt estop mechanik p2s',
    anchor: 'ext-hw-admin',
  });
  registerSettingsSearch({
    labelKey: 'maintenance.programs.calibrateCamera',
    labelFallback: 'Einmess-Assistent Plattenwechsel (5 Schritte)',
    tab: 'general',
    route: '/maintenance?tab=hardware#hw-wizard',
    routeLabel: 'Wartung › Hardware & Optik',
    keywords: 'einmess-assistent einmessen plattenwechsel referenzpunkt aufnahme ablage endschalter probelauf kalibrierung',
    anchor: 'ext-hw-wizard',
  });
  registerSettingsSearch({
    labelKey: 'plateTuning.title',
    labelFallback: 'Kamera einmessen & Leerbett-Prüfung',
    tab: 'general',
    route: '/maintenance?tab=hardware#hw-tuning',
    routeLabel: 'Wartung › Hardware & Optik',
    keywords: 'kamera einmessen leerbett 4 ecken referenzbild schwellwert spaghetti bauteil-wächter',
    anchor: 'ext-hw-tuning',
  });
  registerSettingsSearch({
    labelKey: 'assistant.title',
    labelFallback: 'Lokaler KI-Assistent (Ollama)',
    tab: 'general',
    route: '/maintenance?tab=assistant',
    routeLabel: 'Wartung › Assistent',
    keywords: 'ki assistent ollama sprachmodell lokal qwen gemma modell server fehler erklären',
    anchor: 'ext-assistant',
  });
  registerSettingsSearch({
    labelKey: 'quote.title',
    labelFallback: 'Angebote, Firmendaten & XRechnung',
    tab: 'general',
    route: '/finance',
    routeLabel: 'Finanzen (/finance)',
    keywords: 'angebot angebotskalkulator rechnung xrechnung zugferd firmendaten firmenprofil steuernummer iban ust',
    anchor: 'ext-finance-quotes',
  });
  registerSettingsSearch({
    labelKey: 'factoryReset.title',
    labelFallback: 'Werkseinstellungen',
    tab: 'general',
    route: '/einrichtung#setup-reset',
    routeLabel: 'Einrichtung › Werkseinstellungen',
    keywords: 'werkseinstellungen zurücksetzen factory reset auslieferungszustand neuinstallation',
    anchor: 'ext-factory-reset',
  });
}

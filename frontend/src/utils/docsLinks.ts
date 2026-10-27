// Hilfeseite im eigenen Repo (docs/HILFE.md); Anker sind die GitHub-Überschriften-Anker.
export const HELP_URL = 'https://github.com/Luk1236/printlab/blob/bambu-monitor-port/docs/HILFE.md';

export const helpLink = (anchor = '') => (anchor ? `${HELP_URL}#${anchor}` : HELP_URL);

export const HELP_ANCHORS = {
  externalStorage: 'schritt-4-gesendete-dateien-auf-externem-speicher-speichern',
  internalStorage: 'archiv-karte-hat-nur-einen-namen',
  internalHistory: 'druck-am-drucker-gestartet-kein-vorschaubild',
  ftpsTls: 'ftps-tls-fehler',
  ftpTimeout: 'ftp-uebertragung-zeitueberschreitung',
  virtualPrinter: 'virtueller-drucker',
  announcements: 'ankuendigungen',
  troubleshooting: 'fehlerbehebung-allgemein',
} as const;

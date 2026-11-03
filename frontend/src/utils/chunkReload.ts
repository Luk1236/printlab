const RELOAD_KEY = 'printlab-chunk-reload-at';
const GUARD_MS = 60_000;

// Wortlaut je Browser: Chrome „Failed to fetch dynamically imported module“, Firefox „error loading dynamically imported
// module“, Safari „Importing a module script failed“; „Unable to preload CSS“ kommt von Vite.
const CHUNK_ERROR = /dynamically imported module|importing a module script failed|unable to preload css/i;

/** Ist das Laden einer Seitendatei gescheitert (Neustart nach einem Update, Aussetzer im Netz)? */
export function isChunkLoadError(error: unknown): boolean {
  return error instanceof Error && CHUNK_ERROR.test(error.message);
}

export function reloadPage(): void {
  window.location.reload();
}

/**
 * Lädt nach einem gescheiterten Seitenladen einmal neu. Scheitert es innerhalb einer Minute wieder, bleibt der
 * Fehlerbildschirm stehen, sonst liefe die Seite bei einem ausgefallenen Server in einer Endlosschleife. Ist der
 * Speicher gesperrt (privates Fenster), lässt sich die Sperre nicht merken: dann lieber gar nicht von selbst neu laden.
 */
export function reloadOnceAfterChunkError(now: number = Date.now(), reload: () => void = reloadPage): boolean {
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY));
    if (last && now - last < GUARD_MS) return false;
    sessionStorage.setItem(RELOAD_KEY, String(now));
  } catch {
    return false;
  }
  reload();
  return true;
}

import { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';

import { api } from '../api/client';

const POLL_MS = 3000;
const GIVE_UP_MS = 5 * 60 * 1000;

/**
 * Nach einem Update mit automatischem Neustart: zeigt "startet neu" und lädt die Seite von selbst, sobald PrintLab wieder
 * antwortet (nachdem es kurz weg war, oder mit neuer Versionsnummer). Der erste Start dauert auf dem Pi gut eine Minute.
 */
export function UpdateRestartWatcher({ currentVersion, onReload }: { currentVersion?: string; onReload?: () => void }) {
  const { t } = useTranslation();
  const wasDown = useRef(false);
  const startedAt = useRef(Date.now());
  const reload = onReload ?? (() => window.location.reload());

  useEffect(() => {
    let stopped = false;
    const timer = window.setInterval(async () => {
      if (stopped) return;
      if (Date.now() - startedAt.current > GIVE_UP_MS) {
        window.clearInterval(timer);
        return;
      }
      try {
        const info = await api.getVersion();
        if (stopped) return;
        if (wasDown.current || (currentVersion && info.version !== currentVersion)) {
          window.clearInterval(timer);
          reload();
        }
      } catch {
        wasDown.current = true;
      }
    }, POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentVersion]);

  return (
    <div className="mt-3 flex items-center gap-2 p-2 bg-bambu-green/20 rounded text-sm text-bambu-green" role="status">
      <Loader2 className="w-4 h-4 animate-spin" />
      <span>{t('settings.updateRestarting')}</span>
    </div>
  );
}

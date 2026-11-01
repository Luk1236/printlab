import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type SlicerStatus } from '../api/client';

/**
 * Prüft das gespeicherte Slicer-Sidecar auf Knopfdruck.
 *
 * Die Slice-Maske fragt denselben Endpunkt vor dem Slicen ab; hier steht er
 * dort, wo die Adresse eingetragen wird. Wer auf dem Pi `localhost` stehen hat,
 * sieht so sofort, dass die Adresse auf den PC zeigen muss.
 */
export function SlicerConnectionCheck() {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<SlicerStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const check = async () => {
    setBusy(true);
    setStatus(null);
    setError(null);
    try {
      setStatus(await api.getSlicerStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={check}
        disabled={busy}
        className="px-3 py-1.5 text-sm rounded-md border border-bambu-dark-tertiary text-bambu-gray hover:text-white hover:border-bambu-gray transition-colors disabled:opacity-50"
      >
        {busy ? t('settings.slicerChecking', 'Checking…') : t('settings.slicerCheck', 'Check connection')}
      </button>
      <p className="text-xs text-bambu-gray mt-1">
        {t('settings.slicerCheckHint', 'Checks the saved address.')}
      </p>
      {status?.reachable && (
        <p className="text-xs text-bambu-green mt-1">
          {t('settings.slicerReachable', 'Sidecar reachable.')}
          {status.version ? ` · v${status.version}` : ''}
        </p>
      )}
      {status && !status.reachable && (
        <div className="mt-1">
          {status.url && (
            <p className="text-xs font-mono text-bambu-gray break-all">{status.url}</p>
          )}
          <p className="text-xs text-red-600 dark:text-red-400 break-words">
            {status.configured
              ? t('settings.slicerUnreachable', 'Sidecar unreachable: {{error}}', { error: status.error ?? '' })
              : t('settings.slicerNotConfigured', 'No address configured.')}
          </p>
        </div>
      )}
      {error && <p className="text-xs text-red-600 dark:text-red-400 mt-1 break-words">{error}</p>}
    </div>
  );
}

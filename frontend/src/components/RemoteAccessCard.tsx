import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Globe } from 'lucide-react';

import { api } from '../api/client';
import type { RemoteAccessStatus } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

/**
 * Fernzugriff über Tailscale (Userspace, ohne Root): Einrichten, Anmeldelink, Freigabe, Abschalten.
 * Nur mit eingeschalteter Anmeldung; der Server lehnt Einrichten/Freigeben sonst ab.
 */
export function RemoteAccessCard({ canControl }: { canControl: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const { data: status } = useQuery<RemoteAccessStatus>({
    queryKey: ['remoteAccess'],
    queryFn: () => api.getRemoteAccess(),
    refetchInterval: (query) => (query.state.data?.state === 'login' ? 4000 : 15000),
  });

  const update = (data: RemoteAccessStatus) => queryClient.setQueryData(['remoteAccess'], data);
  const fail = (error: Error) => showToast(error.message, 'error');
  const setup = useMutation({ mutationFn: () => api.setupRemoteAccess(), onSuccess: update, onError: fail });
  const share = useMutation({ mutationFn: () => api.shareRemoteAccess(), onSuccess: update, onError: fail });
  const disable = useMutation({ mutationFn: () => api.disableRemoteAccess(), onSuccess: update, onError: fail });

  if (!status) return null;

  const busy = setup.isPending || share.isPending || disable.isPending;
  const address = status.ips[0] ? `http://${status.ips[0]}:${window.location.port || 8000}` : '';
  const stateLabel = {
    off: t('remoteAccess.stateOff'),
    stopped: t('remoteAccess.stateStopped'),
    login: t('remoteAccess.stateLogin'),
    connected: t('remoteAccess.stateConnected'),
  }[status.state];

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Globe className="w-5 h-5 text-bambu-green" />
            {t('remoteAccess.title')}
          </h2>
          <span className={`text-xs ${status.state === 'connected' ? 'text-bambu-green' : 'text-bambu-gray'}`}>
            {stateLabel}
          </span>
        </div>
        <p className="text-xs text-bambu-gray">{t('remoteAccess.description')}</p>

        {!status.supported && <p className="text-xs text-amber-700 dark:text-amber-400">{t('remoteAccess.unsupported')}</p>}
        {status.supported && !status.auth_enabled && (
          <p className="text-xs text-amber-700 dark:text-amber-400" role="alert">
            {t('remoteAccess.needAuth')}
          </p>
        )}
        {status.error && <p className="text-xs text-red-700 dark:text-red-400">{status.error}</p>}

        {status.state === 'login' && status.login_url && (
          <div className="space-y-1">
            <a
              href={status.login_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-block rounded-lg bg-bambu-green px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >
              {t('remoteAccess.openLogin')}
            </a>
            <p className="text-xs text-bambu-gray">{t('remoteAccess.loginHint')}</p>
          </div>
        )}

        {status.state === 'connected' && (
          <div className="space-y-1 text-xs text-bambu-gray">
            {address && (
              <p>
                {t('remoteAccess.address')}: <span className="font-mono text-white">{address}</span>
              </p>
            )}
            {status.dns_name && (
              <p>
                {t('remoteAccess.name')}: <span className="font-mono text-white">{status.dns_name}</span>
              </p>
            )}
            <p>{status.serving ? t('remoteAccess.shared') : t('remoteAccess.notShared')}</p>
            <p>{t('remoteAccess.deviceHint')}</p>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {status.state !== 'connected' && (
            <Button
              size="sm"
              disabled={!canControl || busy || !status.supported || !status.auth_enabled}
              onClick={() => setup.mutate()}
            >
              {status.state === 'login' ? t('remoteAccess.retry') : t('remoteAccess.setup')}
            </Button>
          )}
          {status.state === 'connected' && !status.serving && (
            <Button size="sm" disabled={!canControl || busy || !status.auth_enabled} onClick={() => share.mutate()}>
              {t('remoteAccess.share')}
            </Button>
          )}
          {(status.state !== 'off' || status.enabled) && (
            <Button size="sm" variant="secondary" disabled={!canControl || busy} onClick={() => disable.mutate()}>
              {t('remoteAccess.disable')}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

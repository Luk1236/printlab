import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { BellRing, Send } from 'lucide-react';

import { api } from '../api/client';
import { useToast } from '../contexts/ToastContext';
import { Button } from './Button';
import { Card, CardContent } from './Card';

function urlBase64ToUint8Array(value: string): Uint8Array {
  const padded = value + '='.repeat((4 - (value.length % 4)) % 4);
  const raw = window.atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (char) => char.charCodeAt(0));
}

/**
 * Browser-Meldungen (Web Push) für dieses Gerät. Das Abo lebt im Browser; der Server merkt sich nur den Endpunkt
 * und verschlüsselt jede Meldung dafür. Beim Öffnen der Seite wird ein vorhandenes Abo erneut gemeldet — so
 * findet ein Gerät nach einem Datenbank-Reset oder auf einem zweiten Browser von selbst wieder Anschluss.
 */
export function PushNotificationsCard() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState(false);

  const supported =
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    window.isSecureContext;

  // Hält die Anzahl der Abos aktuell; die Karte selbst entscheidet über das Abo dieses Browsers.
  useQuery({
    queryKey: ['pushStatus'],
    queryFn: api.getPushStatus,
    enabled: supported,
    retry: false,
  });

  useEffect(() => {
    if (!supported) return;
    let cancelled = false;
    navigator.serviceWorker
      .getRegistration('/')
      .then(async (registration) => {
        const subscription = await registration?.pushManager.getSubscription();
        if (cancelled) return;
        setEnabled(Boolean(subscription));
        if (subscription) {
          await api.subscribePush(subscription.toJSON());
          await queryClient.invalidateQueries({ queryKey: ['pushStatus'] });
        }
      })
      .catch(() => {
        // Kein Service Worker (z. B. unsicherer Zugriff) — die Karte zeigt dann den Hinweis.
      });
    return () => {
      cancelled = true;
    };
  }, [queryClient, supported]);

  const enable = async () => {
    setBusy(true);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') {
        showToast(t('push.denied'), 'error');
        return;
      }
      const registration = await navigator.serviceWorker.register('/sw.js');
      await navigator.serviceWorker.ready;
      const { public_key } = await api.getPushKey();
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key) as BufferSource,
      });
      await api.subscribePush(subscription.toJSON());
      setEnabled(true);
      await queryClient.invalidateQueries({ queryKey: ['pushStatus'] });
      showToast(t('push.enabled'), 'success');
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('push.error'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      const registration = await navigator.serviceWorker.getRegistration('/');
      const subscription = await registration?.pushManager.getSubscription();
      if (subscription) {
        await api.unsubscribePush(subscription.endpoint);
        await subscription.unsubscribe();
      }
      setEnabled(false);
      await queryClient.invalidateQueries({ queryKey: ['pushStatus'] });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('push.error'), 'error');
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    setBusy(true);
    try {
      const result = await api.sendTestPush();
      showToast(
        result.sent > 0 ? t('push.testSent') : t('push.testNone'),
        result.sent > 0 ? 'success' : 'error',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('push.error'), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="push-notifications-card">
      <Card>
        <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <BellRing className="h-5 w-5 text-bambu-green" />
          <h2 className="text-lg font-semibold text-white">{t('push.title')}</h2>
        </div>
        <p className="text-sm text-bambu-gray">{t('push.description')}</p>

        {!supported ? (
          <p className="text-xs text-amber-700 dark:text-amber-400">{t('push.unsupported')}</p>
        ) : (
          <>
            <p className="text-xs text-bambu-gray">
              {enabled ? t('push.stateOn') : t('push.stateOff')}
            </p>
            <div className="flex flex-wrap gap-2">
              {enabled ? (
                <Button size="sm" variant="secondary" disabled={busy} onClick={disable}>
                  {t('push.disable')}
                </Button>
              ) : (
                <Button size="sm" disabled={busy} onClick={enable}>
                  {t('push.enable')}
                </Button>
              )}
              <Button size="sm" variant="secondary" disabled={busy || !enabled} onClick={sendTest}>
                <Send className="h-4 w-4" />
                {t('push.test')}
              </Button>
            </div>
            <p className="text-xs text-bambu-gray">{t('push.hint')}</p>
          </>
        )}
        </CardContent>
      </Card>
    </div>
  );
}

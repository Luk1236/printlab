import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BellRing } from 'lucide-react';

import { api } from '../api/client';
import type { AlertChannelsStatus } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

const inputClass =
  'mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm';

/**
 * Meldewege für Ausfälle (Telegram, ntfy): eintragen, speichern, Testmeldung senden. Token und Adressen werden nur
 * geschrieben, nie vom Server zurückgegeben; hier steht nur, ob sie gesetzt sind.
 */
export function AlertChannelsCard({ canControl }: { canControl: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [token, setToken] = useState('');
  const [chat, setChat] = useState('');
  const [ntfy, setNtfy] = useState('');

  const { data: status } = useQuery<AlertChannelsStatus>({ queryKey: ['alertChannels'], queryFn: api.getAlertChannels });

  const save = useMutation({
    mutationFn: (update: Record<string, string>) => api.saveAlertChannels(update),
    onSuccess: (saved) => {
      queryClient.setQueryData(['alertChannels'], saved);
      setToken('');
      setNtfy('');
      setChat('');
      showToast(t('alertChannels.saved'));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const test = useMutation({
    mutationFn: () => api.testAlertChannels(),
    onSuccess: (result) => {
      if (result.errors.length > 0) showToast(t('alertChannels.testFailed', { errors: result.errors.join(', ') }), 'error');
      else showToast(t('alertChannels.testSent', { channels: result.sent.join(', ') }));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  if (!status) return null;
  const busy = save.isPending || test.isPending;
  const typed: Record<string, string> = {};
  if (token.trim()) typed.telegram_token = token.trim();
  if (chat.trim()) typed.telegram_chat = chat.trim();
  if (ntfy.trim()) typed.ntfy_url = ntfy.trim();
  const anyConfigured = status.telegram || status.ntfy;

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <BellRing className="w-5 h-5 text-bambu-green" />
          {t('alertChannels.title')}
        </h2>
        <p className="text-xs text-bambu-gray">{t('alertChannels.description')}</p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-2">
            <p className="text-sm text-white">
              Telegram{' '}
              <span className={`text-xs ${status.telegram ? 'text-bambu-green' : 'text-bambu-gray'}`}>
                {status.telegram ? t('alertChannels.configured') : t('alertChannels.notConfigured')}
              </span>
            </p>
            <label className="text-xs text-bambu-gray block">
              {t('alertChannels.telegramToken')}
              <input
                type="password"
                autoComplete="off"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder={status.telegram ? '••••••••' : '123456789:ABC…'}
                className={inputClass}
              />
            </label>
            <label className="text-xs text-bambu-gray block">
              {t('alertChannels.telegramChat')}
              <input
                value={chat}
                onChange={(event) => setChat(event.target.value)}
                placeholder={status.telegram_chat || '123456789'}
                className={inputClass}
              />
            </label>
          </div>
          <div className="space-y-2">
            <p className="text-sm text-white">
              ntfy{' '}
              <span className={`text-xs ${status.ntfy ? 'text-bambu-green' : 'text-bambu-gray'}`}>
                {status.ntfy ? `${t('alertChannels.configured')} (${status.ntfy_host})` : t('alertChannels.notConfigured')}
              </span>
            </p>
            <label className="text-xs text-bambu-gray block">
              {t('alertChannels.ntfyUrl')}
              <input
                type="password"
                autoComplete="off"
                value={ntfy}
                onChange={(event) => setNtfy(event.target.value)}
                placeholder={status.ntfy ? '••••••••' : 'https://ntfy.sh/…'}
                className={inputClass}
              />
            </label>
            <p className="text-xs text-bambu-gray">{t('alertChannels.ntfyHint')}</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={!canControl || busy || Object.keys(typed).length === 0}
            onClick={() => save.mutate(typed)}
          >
            {t('common.save')}
          </Button>
          <Button size="sm" variant="secondary" disabled={!canControl || busy || !anyConfigured} onClick={() => test.mutate()}>
            {t('alertChannels.test')}
          </Button>
          {anyConfigured && (
            <Button
              size="sm"
              variant="ghost"
              disabled={!canControl || busy}
              onClick={() => save.mutate({ telegram_token: '', telegram_chat: '', ntfy_url: '' })}
            >
              {t('alertChannels.clear')}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

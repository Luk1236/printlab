import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Wand2 } from 'lucide-react';

import { api } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';

/**
 * Auto-Einrichtung: zeigt, was PrintLab ohne Zugangsdaten selbst einrichten kann, und erledigt es mit einem Knopf.
 * Was danach noch dem Benutzer gehört (Passwort, Zugangscode, Token), bleibt im Assistenten darunter.
 */
export function AutoSetupCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ['autoSetup'], queryFn: () => api.getAutoSetup() });
  const run = useMutation({
    mutationFn: () => api.runAutoSetup(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['autoSetup'] });
      void queryClient.invalidateQueries({ queryKey: ['setupStatus'] });
    },
  });

  const result = run.data;
  const open = data?.items.filter((item) => item.state === 'todo') ?? [];
  if (!result && open.length === 0 && !run.isError) return null;

  return (
    <Card>
      <CardContent className="space-y-3">
        <div data-testid="auto-setup" className="space-y-3">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white flex items-center gap-2">
            <Wand2 className="w-5 h-5 text-bambu-green" />
            {t('autoSetup.title')}
          </h2>
          {open.length > 0 && !result && (
            <>
              <p className="text-xs text-bambu-gray">{t('autoSetup.intro')}</p>
              <ul className="list-disc pl-5 text-sm text-gray-900 dark:text-white space-y-1">
                {open.map((item) => (
                  <li key={item.id}>{t(`autoSetup.item.${item.id}`)}</li>
                ))}
              </ul>
              <Button size="sm" disabled={run.isPending} onClick={() => run.mutate()}>
                {run.isPending ? t('autoSetup.running') : t('autoSetup.run', { count: open.length })}
              </Button>
            </>
          )}
          {run.isError && (
            <p className="text-xs text-red-700 dark:text-red-400" role="alert">
              {t('autoSetup.error')}
            </p>
          )}
          {result && (
            <ul className="space-y-2" data-testid="auto-setup-result">
              {result.items
                .filter((item) => item.state !== 'manual')
                .map((item) => (
                  <li key={item.id} className="text-sm text-gray-900 dark:text-white" data-testid={`auto-setup-${item.id}`}>
                    {t(`autoSetup.item.${item.id}`)}: {t(`autoSetup.result.${item.state}`)}
                    {item.state === 'needs_user' && item.detail.startsWith('https://') && (
                      <>
                        {' '}
                        <a
                          href={item.detail}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-bambu-green underline"
                        >
                          {t('autoSetup.login')}
                        </a>
                      </>
                    )}
                  </li>
                ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

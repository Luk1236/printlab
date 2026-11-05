import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Circle, ListChecks, MinusCircle } from 'lucide-react';

import { api } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';

const ITEM_ACTIONS: Record<string, { to?: string; anchor?: string; fallbackTo?: string }> = {
  auth: { to: '/settings?tab=users' },
  printer: { to: '/' },
  alerts: { anchor: 'setup-alerts', fallbackTo: '/settings?tab=setup#setup-alerts' },
  external_backup: { to: '/settings?tab=backup#card-backup' },
  remote: { anchor: 'setup-remote', fallbackTo: '/settings?tab=setup#setup-remote' },
  https: { anchor: 'setup-remote', fallbackTo: '/settings?tab=setup#setup-remote' },
};

/**
 * Inbetriebnahme-Checkliste: zeigt aus dem vorhandenen Zustand, was für einen sicheren Dauerbetrieb noch fehlt
 * (Anmeldung, Drucker, Meldeweg, Sicherung nach außen, signierte Updates, SSD …). Ändert nichts; jeder offene Punkt nennt,
 * wo er erledigt wird, und bietet — sofern in der Oberfläche einstellbar — einen direkten Sprungknopf.
 */
export function SetupChecklistCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data } = useQuery({ queryKey: ['setupStatus'], queryFn: () => api.getSetupStatus(), refetchInterval: 60000 });

  if (!data) return null;
  const allDone = data.done === data.total;

  const openTarget = (id: string) => {
    const action = ITEM_ACTIONS[id];
    if (!action) return;
    if (action.anchor) {
      const el = document.getElementById(action.anchor);
      if (el) {
        el.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
        el.classList.add('ring-2', 'ring-bambu-green');
        window.setTimeout(() => el.classList.remove('ring-2', 'ring-bambu-green'), 1500);
        return;
      }
      if (action.fallbackTo) {
        navigate(action.fallbackTo);
        return;
      }
    }
    if (action.to) {
      navigate(action.to);
    }
  };

  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <ListChecks className="w-5 h-5 text-bambu-green" />
            {t('setupChecklist.title')}
          </h2>
          <span className={`text-xs ${allDone ? 'text-bambu-green' : 'text-bambu-gray'}`} data-testid="setup-progress">
            {t('setupChecklist.progress', { done: data.done, total: data.total })}
          </span>
        </div>
        {data.required_open > 0 && (
          <p className="text-xs text-red-700 dark:text-red-400" role="alert">
            {t('setupChecklist.requiredOpen', { count: data.required_open })}
          </p>
        )}
        {allDone && <p className="text-xs text-bambu-green">{t('setupChecklist.allDone')}</p>}
        <ul className="space-y-2">
          {data.items.map((item) => {
            const action = ITEM_ACTIONS[item.id];
            return (
              <li
                key={item.id}
                className="flex items-start justify-between gap-3 text-xs rounded-lg border border-bambu-dark-tertiary/60 bg-bambu-dark/40 px-3 py-2"
                data-testid={`setup-item-${item.id}`}
              >
                <div className="flex items-start gap-2 min-w-0">
                  {item.done === null ? (
                    <MinusCircle className="w-4 h-4 shrink-0 mt-0.5 text-bambu-gray" aria-label={t('setupChecklist.notApplicable')} />
                  ) : item.done ? (
                    <CheckCircle2 className="w-4 h-4 shrink-0 mt-0.5 text-bambu-green" aria-label={t('setupChecklist.done')} />
                  ) : (
                    <Circle
                      className={`w-4 h-4 shrink-0 mt-0.5 ${item.level === 'required' ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}`}
                      aria-label={t('setupChecklist.open')}
                    />
                  )}
                  <div className="min-w-0">
                    <p className={item.done ? 'text-bambu-gray' : 'text-white font-medium'}>
                      {t(`setupChecklist.item.${item.id}`)}
                      <span className="ml-2 font-normal text-bambu-gray">({t(`setupChecklist.level.${item.level}`)})</span>
                    </p>
                    {item.done === false && <p className="text-bambu-gray mt-0.5">{t(`setupChecklist.how.${item.id}`)}</p>}
                  </div>
                </div>
                {item.done === false && action && (
                  <Button size="sm" variant="secondary" className="shrink-0" onClick={() => openTarget(item.id)}>
                    {action.anchor ? t('setupWizard.showCard') : t('setupWizard.openPage')}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

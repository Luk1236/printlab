import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Circle, ListChecks, MinusCircle } from 'lucide-react';

import { api } from '../api/client';
import { Card, CardContent } from './Card';

/**
 * Inbetriebnahme-Checkliste: zeigt aus dem vorhandenen Zustand, was für einen sicheren Dauerbetrieb noch fehlt
 * (Anmeldung, Drucker, Meldeweg, Sicherung nach außen, signierte Updates, SSD …). Ändert nichts; jeder offene Punkt nennt,
 * wo er erledigt wird.
 */
export function SetupChecklistCard() {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ['setupStatus'], queryFn: () => api.getSetupStatus(), refetchInterval: 60000 });

  if (!data) return null;
  const allDone = data.done === data.total;

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
          {data.items.map((item) => (
            <li key={item.id} className="flex items-start gap-2 text-xs" data-testid={`setup-item-${item.id}`}>
              {item.done === null ? (
                <MinusCircle className="w-4 h-4 shrink-0 text-bambu-gray" aria-label={t('setupChecklist.notApplicable')} />
              ) : item.done ? (
                <CheckCircle2 className="w-4 h-4 shrink-0 text-bambu-green" aria-label={t('setupChecklist.done')} />
              ) : (
                <Circle
                  className={`w-4 h-4 shrink-0 ${item.level === 'required' ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}`}
                  aria-label={t('setupChecklist.open')}
                />
              )}
              <div>
                <p className={item.done ? 'text-bambu-gray' : 'text-white'}>
                  {t(`setupChecklist.item.${item.id}`)}
                  <span className="ml-2 text-bambu-gray">({t(`setupChecklist.level.${item.level}`)})</span>
                </p>
                {item.done === false && <p className="text-bambu-gray">{t(`setupChecklist.how.${item.id}`)}</p>}
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

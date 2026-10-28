import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Compass } from 'lucide-react';

import { api } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { openSteps } from '../utils/setupSteps';

/** Wohin ein Schritt führt: Seite der App oder Karte auf derselben Seite (Anker). Alles andere passiert am Pi selbst. */
const ACTIONS: Record<string, { to?: string; anchor?: string }> = {
  printer: { to: '/' },
  alerts: { anchor: 'setup-alerts' },
  remote: { anchor: 'setup-remote' },
  https: { anchor: 'setup-remote' },
};

/**
 * Geführte Einrichtung: zeigt die offenen Punkte der Checkliste einzeln, mit Erklärung und – wo es in der App geht – einem
 * Knopf zur passenden Stelle. Ändert nichts selbst; erledigte Punkte verschwinden von allein.
 */
export function SetupWizardCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [index, setIndex] = useState(0);
  const { data } = useQuery({ queryKey: ['setupStatus'], queryFn: () => api.getSetupStatus(), refetchInterval: 60000 });

  if (!data) return null;
  const steps = openSteps(data);
  if (steps.length === 0) return null;
  const current = steps[Math.min(index, steps.length - 1)];
  const position = Math.min(index, steps.length - 1);
  const action = ACTIONS[current.id];

  const go = () => {
    if (action?.to) navigate(action.to);
    else if (action?.anchor) document.getElementById(action.anchor)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  };

  return (
    <Card>
      <CardContent className="space-y-3">
        <div data-testid="setup-wizard" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Compass className="w-5 h-5 text-bambu-green" />
            {t('setupWizard.title')}
          </h2>
          <span className="text-xs text-bambu-gray" data-testid="wizard-step">
            {t('setupWizard.step', { current: position + 1, total: steps.length })}
          </span>
        </div>
        <div>
          <p className="text-sm text-white">
            {t(`setupChecklist.item.${current.id}`)}
            <span className="ml-2 text-xs text-bambu-gray">({t(`setupChecklist.level.${current.level}`)})</span>
          </p>
          <p className="text-xs text-bambu-gray mt-1">{t(`setupChecklist.how.${current.id}`)}</p>
          {!action && <p className="text-xs text-bambu-gray mt-1">{t('setupWizard.onThePi')}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" disabled={position === 0} onClick={() => setIndex(position - 1)}>
            {t('setupWizard.back')}
          </Button>
          {action && (
            <Button size="sm" onClick={go}>
              {action.to ? t('setupWizard.openPage') : t('setupWizard.showCard')}
            </Button>
          )}
          <Button size="sm" variant="secondary" disabled={position >= steps.length - 1} onClick={() => setIndex(position + 1)}>
            {t('setupWizard.next')}
          </Button>
        </div>
        </div>
      </CardContent>
    </Card>
  );
}

/** Hinweis über dem Status-Reiter, solange Pflichtpunkte offen sind. */
export function SetupBanner({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  const { data } = useQuery({ queryKey: ['setupStatus'], queryFn: () => api.getSetupStatus(), refetchInterval: 60000 });
  if (!data || data.required_open === 0) return null;
  return (
    <div
      className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-400"
      role="alert"
    >
      <span>{t('setupWizard.banner', { count: data.required_open })}</span>
      <Button size="sm" variant="secondary" onClick={onOpen}>
        {t('setupWizard.openAssistant')}
      </Button>
    </div>
  );
}

import { useTranslation } from 'react-i18next';
import { Compass } from 'lucide-react';

import { useAuth } from '../contexts/AuthContext';
import { SetupChecklistCard } from '../components/SetupChecklistCard';
import { SetupWizardCard } from '../components/SetupWizardCard';
import { FactoryResetCard } from '../components/FactoryResetCard';

/**
 * Einrichtung an einem Ort: der Assistent führt Punkt für Punkt durch die offenen Schritte, die Checkliste zeigt den
 * Gesamtstand, und ganz unten steht der Weg zurück auf den Auslieferungszustand. Vorher lag das nur im Status-Reiter
 * der Wartung — wer frisch installiert, findet es so direkt in der Seitenleiste.
 */
export function SetupGuidePage() {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Compass className="w-6 h-6 text-bambu-green" />
        <h1 className="text-2xl font-bold text-white">{t('setupWizard.title')}</h1>
      </div>
      <SetupWizardCard />
      <SetupChecklistCard />
      <FactoryResetCard canControl={hasPermission('settings:update')} />
    </div>
  );
}

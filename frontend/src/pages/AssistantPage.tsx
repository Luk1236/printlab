import React from 'react';
import { useTranslation } from 'react-i18next';
import { Bot, Sparkles } from 'lucide-react';
import { AssistantPanel } from '../components/AssistantPanel';

export function AssistantPage() {
  const { t } = useTranslation();

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-bambu-green/10 text-bambu-green">
              <Bot className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white flex items-center gap-2">
                {t('assistant.title', 'KI-Assistent')}
                <span className="text-xs font-normal px-2 py-0.5 rounded-full bg-bambu-green/10 text-bambu-green border border-bambu-green/20">
                  Lokal &amp; Privat
                </span>
              </h1>
              <p className="text-sm text-bambu-gray mt-0.5">
                {t(
                  'assistant.pageSubtitle',
                  'Direkter Chat für Drucker-Status, Fehlerdiagnose, Slicer-Hilfe und Betriebsfragen'
                )}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Pure Chat Interface (No config, no setup forms) */}
      <AssistantPanel canConfigure={false} chatOnly={true} />
    </div>
  );
}

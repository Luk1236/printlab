import React from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Compass, ExternalLink, CheckSquare, Stethoscope, Sliders } from 'lucide-react';
import { QuickSetupHubCard } from '../QuickSetupHubCard';
import { SetupChecklistCard } from '../SetupChecklistCard';
import { SelfTestCard } from '../SelfTestCard';
import { SlicerConnectionCheck } from '../SlicerConnectionCheck';
import { Card, CardHeader, CardContent } from '../Card';
import { Button } from '../Button';

export interface SetupSettingsSectionProps {
  printersCount?: number;
  authEnabled?: boolean;
  slicerApiEnabled?: boolean;
  canUpdate?: boolean;
}

export function SetupSettingsSection({
  printersCount = 0,
  authEnabled = false,
  slicerApiEnabled = false,
  canUpdate = true,
}: SetupSettingsSectionProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      {/* Intro Header Card with Deep-Link to full setup guide */}
      <Card>
        <CardHeader>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-bambu-green/10 text-bambu-green shrink-0">
                <Compass className="w-6 h-6" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-white">
                  {t('setupWizard.title', 'Einrichtungsassistent & Schnellstart')}
                </h2>
                <p className="text-sm text-bambu-gray">
                  {t(
                    'setupWizard.subtitle',
                    'Konfigurieren Sie Drucker, Slicer, Benachrichtigungen und Systemdienste'
                  )}
                </p>
              </div>
            </div>
            <Link to="/einrichtung">
              <Button variant="secondary" className="gap-2 shrink-0 w-full sm:w-auto">
                <Compass className="w-4 h-4 text-bambu-green" />
                <span>{t('setupWizard.openFullGuide', 'Vollständigen Assistenten öffnen')}</span>
                <ExternalLink className="w-3.5 h-3.5 text-bambu-gray" />
              </Button>
            </Link>
          </div>
        </CardHeader>
      </Card>

      {/* Quick Setup Hub */}
      <QuickSetupHubCard
        mode="settings"
        printersCount={printersCount}
        authEnabled={authEnabled}
        slicerApiEnabled={slicerApiEnabled}
      />

      {/* Two-column setup checklist and system diagnostics */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Step-by-Step Checklist */}
        <SetupChecklistCard />

        {/* Slicer Connection & Direct Slicer Check */}
        <div className="space-y-6">
          <SlicerConnectionCheck />
          <SelfTestCard canRun={canUpdate} />
        </div>
      </div>
    </div>
  );
}

import { useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ScanEye } from 'lucide-react';

import { api } from '../api/client';
import { Card, CardContent, CardHeader } from './Card';
import { Toggle } from './Toggle';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';

function CheckRow({
  id,
  label,
  hint,
  link,
  linkLabel,
  children,
}: {
  id: string;
  label: string;
  hint: string;
  link?: string;
  linkLabel?: string;
  children: ReactNode;
}) {
  return (
    <div
      data-testid={`check-${id}`}
      className="flex items-start justify-between gap-3 border-t border-bambu-dark-tertiary pt-3 first:border-t-0 first:pt-0"
    >
      <div className="min-w-0">
        <p className="text-sm font-medium text-white">{label}</p>
        <p className="text-xs text-bambu-gray">
          {hint}
          {link && (
            <>
              {' '}
              <Link to={link} className="text-bambu-green hover:underline">
                {linkLabel}
              </Link>
            </>
          )}
        </p>
      </div>
      {children}
    </div>
  );
}

/**
 * Alle KI- und Kameraprüfungen an einem Ort: Schalter hier, Feineinstellungen an der verlinkten Stelle.
 * Die Erkennung des Druckers selbst und Obico werden nur angezeigt: Erstere stellt man am Drucker ein,
 * Obico direkt unter dieser Karte.
 */
export function AiChecksCard() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const { hasPermission } = useAuth();
  const [pickedId, setPickedId] = useState<number | null>(null);

  const { data: printers } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters });
  const printer = printers?.find((entry) => entry.id === pickedId) ?? printers?.[0];
  const printerId = printer?.id ?? 0;

  const { data: assistant } = useQuery({ queryKey: ['ai-checks-assistant'], queryFn: api.getAssistantStatus });
  const { data: aiScan } = useQuery({ queryKey: ['ai-scan'], queryFn: () => api.getAiScan() });
  const { data: aiWatch } = useQuery({ queryKey: ['ai-watch'], queryFn: () => api.getAiWatch() });
  const { data: obico } = useQuery({ queryKey: ['obico-status'], queryFn: api.getObicoStatus });
  const { data: firstLayer } = useQuery({
    queryKey: ['firstLayerInspector', printerId],
    queryFn: () => api.getFirstLayerInspector(printerId),
    enabled: printerId > 0,
  });
  const { data: partWatcher } = useQuery({
    queryKey: ['partWatcher', printerId],
    queryFn: () => api.getPartWatcher(printerId),
    enabled: printerId > 0,
  });
  const { data: status } = useQuery({
    queryKey: ['printerStatus', printerId],
    queryFn: () => api.getPrinterStatus(printerId),
    enabled: printerId > 0,
  });

  const toggle = useMutation({
    mutationFn: ({ run }: { run: () => Promise<unknown>; queryKey: unknown[] }) => run(),
    onSuccess: (_result, { queryKey }) => {
      showToast(t('common.success'));
      queryClient.invalidateQueries({ queryKey });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const canSettings = hasPermission('settings:update') && !toggle.isPending;
  const canControl = hasPermission('printers:control') && !toggle.isPending && printerId > 0;
  const canUpdatePrinter = hasPermission('printers:update') && !toggle.isPending && printerId > 0;

  return (
    <Card id="card-ai-checks">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ScanEye className="w-5 h-5 text-bambu-green" />
            <h2 className="text-lg font-semibold text-white">{t('aiChecks.title')}</h2>
          </div>
          {printers && printers.length > 1 && (
            <select
              aria-label={t('aiChecks.printer')}
              value={printerId}
              onChange={(event) => setPickedId(Number(event.target.value))}
              className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
            >
              {printers.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <p className="text-sm text-bambu-gray mt-2">{t('aiChecks.subtitle')}</p>
      </CardHeader>
      <CardContent className="space-y-3">
        <CheckRow
          id="assistant"
          label={t('aiChecks.assistant')}
          hint={t('aiChecks.assistantHint')}
          link="/maintenance?tab=assistant"
          linkLabel={t('aiChecks.settingsLink')}
        >
          <Toggle
            checked={Boolean(assistant?.config.enabled)}
            disabled={!canSettings || !assistant}
            onChange={(enabled) =>
              toggle.mutate({
                run: () => api.saveAssistantConfig({ enabled }),
                queryKey: ['ai-checks-assistant'],
              })
            }
          />
        </CheckRow>
        <CheckRow
          id="error-scan"
          label={t('aiChecks.errorScan')}
          hint={t('aiChecks.errorScanHint')}
          link="/error-help"
          linkLabel={t('aiChecks.settingsLink')}
        >
          <Toggle
            checked={Boolean(aiScan?.config.error_scan_enabled)}
            disabled={!canSettings || !aiScan}
            onChange={(enabled) =>
              toggle.mutate({
                run: () => api.saveAiScan({ error_scan_enabled: enabled }),
                queryKey: ['ai-scan'],
              })
            }
          />
        </CheckRow>
        <CheckRow
          id="ai-watch"
          label={t('aiChecks.aiWatch')}
          hint={t('aiChecks.aiWatchHint')}
          link="/error-help"
          linkLabel={t('aiChecks.settingsLink')}
        >
          <Toggle
            checked={Boolean(aiWatch?.config.enabled)}
            disabled={!canSettings || !aiWatch}
            onChange={(enabled) =>
              toggle.mutate({
                run: () => api.saveAiWatch({ enabled }),
                queryKey: ['ai-watch'],
              })
            }
          />
        </CheckRow>
        <CheckRow
          id="plate-detection"
          label={t('aiChecks.plateDetection')}
          hint={t('aiChecks.plateDetectionHint')}
          link="/maintenance?tab=hardware#hw-tuning"
          linkLabel={t('aiChecks.settingsLink')}
        >
          <Toggle
            checked={Boolean(printer?.plate_detection_enabled)}
            disabled={!canUpdatePrinter}
            onChange={(enabled) =>
              toggle.mutate({
                run: () => api.updatePrinter(printerId, { plate_detection_enabled: enabled }),
                queryKey: ['printers'],
              })
            }
          />
        </CheckRow>
        <CheckRow
          id="first-layer"
          label={t('aiChecks.firstLayer')}
          hint={t('aiChecks.firstLayerHint')}
          link="/maintenance?tab=hardware#hw-programs"
          linkLabel={t('aiChecks.settingsLink')}
        >
          <Toggle
            checked={Boolean(firstLayer?.enabled)}
            disabled={!canControl || !firstLayer}
            onChange={(enabled) =>
              toggle.mutate({
                run: () => api.setFirstLayerInspector(printerId, enabled),
                queryKey: ['firstLayerInspector', printerId],
              })
            }
          />
        </CheckRow>
        <CheckRow
          id="part-watcher"
          label={t('aiChecks.partWatcher')}
          hint={t('aiChecks.partWatcherHint')}
          link="/maintenance?tab=hardware#hw-programs"
          linkLabel={t('aiChecks.settingsLink')}
        >
          <Toggle
            checked={Boolean(partWatcher?.enabled)}
            disabled={!canControl || !partWatcher}
            onChange={(enabled) =>
              toggle.mutate({
                run: () =>
                  api.setPartWatcher(printerId, {
                    enabled,
                    threshold: partWatcher?.threshold,
                    overrides: partWatcher?.overrides,
                  }),
                queryKey: ['partWatcher', printerId],
              })
            }
          />
        </CheckRow>
        <CheckRow
          id="obico"
          label={t('aiChecks.obico')}
          hint={obico?.enabled && !obico.ml_url ? t('aiChecks.obicoNoServer') : t('aiChecks.obicoHint')}
        >
          <Toggle checked={Boolean(obico?.enabled && obico.ml_url)} disabled onChange={() => {}} />
        </CheckRow>
        <CheckRow
          id="firmware-spaghetti"
          label={t('aiChecks.firmwareSpaghetti')}
          hint={t('aiChecks.firmwareHint')}
        >
          <Toggle checked={Boolean(status?.print_options?.spaghetti_detector)} disabled onChange={() => {}} />
        </CheckRow>
        <CheckRow
          id="firmware-first-layer"
          label={t('aiChecks.firmwareFirstLayer')}
          hint={t('aiChecks.firmwareHint')}
        >
          <Toggle checked={Boolean(status?.print_options?.first_layer_inspector)} disabled onChange={() => {}} />
        </CheckRow>
      </CardContent>
    </Card>
  );
}

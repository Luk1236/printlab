import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertOctagon,
  AlertTriangle,
  Camera,
  CheckCircle2,
  Eye,
  Loader2,
  RefreshCw,
  Save,
  Sliders,
  Upload,
} from 'lucide-react';

import { api } from '../api/client';
import type {
  LayerInspectionConfig,
  LayerInspectionStatus,
  LayerInspectionTestResult,
} from '../api/client';
import { Button } from './Button';
import { Card, CardContent, CardHeader } from './Card';
import { Toggle } from './Toggle';
import { useToast } from '../contexts/ToastContext';

interface LayerInspectionCardProps {
  canControl: boolean;
  printerId?: number;
}

export function LayerInspectionCard({ canControl, printerId: propPrinterId }: LayerInspectionCardProps) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const [selectedPrinterId, setSelectedPrinterId] = useState<number | null>(null);
  const [testResult, setTestResult] = useState<LayerInspectionTestResult | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  // Druckerliste abfragen
  const { data: printers } = useQuery({
    queryKey: ['printers'],
    queryFn: api.getPrinters,
  });

  const activePrinterId = propPrinterId ?? selectedPrinterId ?? printers?.[0]?.id ?? 1;

  // Status & Konfiguration für den gewählten Drucker
  const { data: statusData, isLoading: isLoadingStatus } = useQuery<LayerInspectionStatus>({
    queryKey: ['layerInspection', activePrinterId],
    queryFn: () => api.getLayerInspection(activePrinterId),
    enabled: activePrinterId > 0,
    refetchInterval: 10000,
  });

  // Lokaler State für Formular
  const [formConfig, setFormConfig] = useState<Partial<LayerInspectionConfig>>({});

  const currentConfig: LayerInspectionConfig = {
    enabled: false,
    layer_interval: 2,
    sensitivity_threshold: 0.65,
    consecutive_alerts: 2,
    auto_pause: true,
    save_debug_snapshots: true,
    min_layer: 3,
    ...(statusData?.config || {}),
    ...formConfig,
  };

  // Speichern Mutation
  const saveMutation = useMutation({
    mutationFn: (cfg: Partial<LayerInspectionConfig>) =>
      api.updateLayerInspection(activePrinterId, cfg),
    onSuccess: () => {
      showToast(t('common.saved', 'Einstellungen erfolgreich gespeichert'));
      queryClient.invalidateQueries({ queryKey: ['layerInspection', activePrinterId] });
      setFormConfig({});
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  // Zähler zurücksetzen Mutation
  const resetMutation = useMutation({
    mutationFn: () => api.resetLayerInspection(activePrinterId),
    onSuccess: () => {
      showToast(t('layerInspection.resetSuccess', 'Fehlerzähler zurückgesetzt'));
      queryClient.invalidateQueries({ queryKey: ['layerInspection', activePrinterId] });
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  // Sofort-Test Mutation
  const testMutation = useMutation({
    mutationFn: () => api.testLayerInspection(activePrinterId, uploadFile || undefined),
    onSuccess: (data) => {
      setTestResult(data);
      if (data.result.is_failure) {
        showToast(
          `Fehldruck erkannt! Chaos-Score: ${(data.result.chaos_score * 100).toFixed(0)}%`,
          'error',
        );
      } else {
        showToast(
          `Schichtbild in Ordnung (Chaos-Score: ${(data.result.chaos_score * 100).toFixed(0)}%)`,
        );
      }
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  const handleToggleEnabled = (val: boolean) => {
    setFormConfig((prev) => ({ ...prev, enabled: val }));
    saveMutation.mutate({ enabled: val });
  };

  const handleToggleAutoPause = (val: boolean) => {
    setFormConfig((prev) => ({ ...prev, auto_pause: val }));
  };

  const handleSave = () => {
    saveMutation.mutate(currentConfig);
  };

  return (
    <Card id="hw-layer-inspection" className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Eye className="w-5 h-5 text-bambu-green" />
            <div>
              <h2 className="text-lg font-semibold text-white">
                {t('layerInspection.title', 'KI-Schichtanalyse & Edge-Spaghetti-Detektor')}
              </h2>
              <p className="text-xs text-bambu-gray mt-0.5">
                {t(
                  'layerInspection.subtitle',
                  'Lokale OpenCV-Echtzeitanalyse (CLAHE & Entropie) alle N Schichten mit automatischem Not-Stopp',
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {printers && printers.length > 1 && !propPrinterId && (
              <select
                aria-label={t('common.printer', 'Drucker')}
                value={activePrinterId}
                onChange={(e) => {
                  setSelectedPrinterId(Number(e.target.value));
                  setTestResult(null);
                  setFormConfig({});
                }}
                className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2.5 py-1.5 text-white text-xs"
              >
                {printers.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            )}

            <div
              className={`px-2.5 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 ${
                currentConfig.enabled
                  ? (statusData?.consecutive_alerts || 0) > 0
                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  currentConfig.enabled
                    ? (statusData?.consecutive_alerts || 0) > 0
                      ? 'bg-amber-400 animate-pulse'
                      : 'bg-emerald-400'
                    : 'bg-zinc-500'
                }`}
              />
              {currentConfig.enabled
                ? (statusData?.consecutive_alerts || 0) > 0
                  ? `Warnung (${statusData?.consecutive_alerts}/${currentConfig.consecutive_alerts})`
                  : t('common.active', 'Aktiv')
                : t('common.disabled', 'Deaktiviert')}
            </div>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-6 pt-2">
        {isLoadingStatus ? (
          <div className="py-8 flex justify-center items-center text-bambu-gray gap-2">
            <Loader2 className="w-5 h-5 animate-spin text-bambu-green" />
            <span className="text-sm">Lade Schichtanalyse-Status...</span>
          </div>
        ) : (
          <>
            {/* Status-Dashboard */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="p-3 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary">
                <div className="text-xs text-bambu-gray">Laufender Fehlerzähler</div>
                <div className="text-xl font-bold text-white mt-1 flex items-center justify-between">
                  <span>
                    {statusData?.consecutive_alerts || 0} / {currentConfig.consecutive_alerts}
                  </span>
                  {(statusData?.consecutive_alerts || 0) > 0 && (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => resetMutation.mutate()}
                      disabled={!canControl || resetMutation.isPending}
                      className="text-xs h-7 px-2"
                      title="Zähler zurücksetzen"
                    >
                      <RefreshCw className="w-3.5 h-3.5" />
                    </Button>
                  )}
                </div>
                <div className="text-[11px] text-bambu-gray mt-1">
                  {(statusData?.consecutive_alerts || 0) >= currentConfig.consecutive_alerts
                    ? 'Not-Pause Bedingung erfüllt!'
                    : 'Fehler in Folge bis Pause'}
                </div>
              </div>

              <div className="p-3 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary">
                <div className="text-xs text-bambu-gray">Letzte Schichtprüfung</div>
                <div className="text-xl font-bold text-white mt-1">
                  {statusData?.last_layer ? `Schicht ${statusData.last_layer}` : '—'}
                </div>
                <div className="text-[11px] text-bambu-gray mt-1">
                  Prüfintervall: alle {currentConfig.layer_interval} Schichten
                </div>
              </div>

              <div className="p-3 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary">
                <div className="text-xs text-bambu-gray">Empfindlichkeit (Schwelle)</div>
                <div className="text-xl font-bold text-white mt-1">
                  {(currentConfig.sensitivity_threshold * 100).toFixed(0)}%
                </div>
                <div className="text-[11px] text-bambu-gray mt-1">
                  {currentConfig.auto_pause ? 'Auto-Pause aktiviert' : 'Nur Warnung / Benachrichtigung'}
                </div>
              </div>
            </div>

            {/* Einstellungen Formular */}
            <div className="p-4 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary space-y-4">
              <div className="flex items-center justify-between border-b border-bambu-dark-tertiary pb-3">
                <div>
                  <div className="text-sm font-medium text-white">Automatische Schichtüberwachung</div>
                  <div className="text-xs text-bambu-gray">
                    Prüft automatisch beim Schichtwechsel das Druckbett auf Filament-Salat
                  </div>
                </div>
                <Toggle
                  checked={currentConfig.enabled}
                  onChange={handleToggleEnabled}
                  disabled={!canControl || saveMutation.isPending}
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
                <div>
                  <label className="text-xs font-medium text-bambu-gray block mb-1">
                    Prüfintervall (alle N Schichten)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={currentConfig.layer_interval}
                    onChange={(e) =>
                      setFormConfig((prev) => ({
                        ...prev,
                        layer_interval: Math.max(1, parseInt(e.target.value) || 1),
                      }))
                    }
                    disabled={!canControl}
                    className="w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                  />
                  <span className="text-[11px] text-bambu-gray">Empfohlen: alle 2–3 Schichten</span>
                </div>

                <div>
                  <label className="text-xs font-medium text-bambu-gray block mb-1">
                    Empfindlichkeitsschwelle ({(currentConfig.sensitivity_threshold * 100).toFixed(0)}%)
                  </label>
                  <input
                    type="range"
                    min={40}
                    max={90}
                    step={1}
                    value={Math.round(currentConfig.sensitivity_threshold * 100)}
                    onChange={(e) =>
                      setFormConfig((prev) => ({
                        ...prev,
                        sensitivity_threshold: Number(e.target.value) / 100.0,
                      }))
                    }
                    disabled={!canControl}
                    className="w-full accent-bambu-green mt-2 cursor-pointer"
                  />
                  <div className="flex justify-between text-[11px] text-bambu-gray">
                    <span>40% (Sehr sensibel)</span>
                    <span>65% (Standard)</span>
                    <span>90% (Tolerant)</span>
                  </div>
                </div>

                <div>
                  <label className="text-xs font-medium text-bambu-gray block mb-1">
                    Bestätigte Fehlschläge in Folge vor Pause
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={5}
                    value={currentConfig.consecutive_alerts}
                    onChange={(e) =>
                      setFormConfig((prev) => ({
                        ...prev,
                        consecutive_alerts: Math.max(1, parseInt(e.target.value) || 1),
                      }))
                    }
                    disabled={!canControl}
                    className="w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                  />
                  <span className="text-[11px] text-bambu-gray">Verhindert Fehlalarme durch Druckkopf</span>
                </div>

                <div>
                  <label className="text-xs font-medium text-bambu-gray block mb-1">
                    Erste Schichten ignorieren (ab Schicht)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={currentConfig.min_layer}
                    onChange={(e) =>
                      setFormConfig((prev) => ({
                        ...prev,
                        min_layer: Math.max(1, parseInt(e.target.value) || 1),
                      }))
                    }
                    disabled={!canControl}
                    className="w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                  />
                  <span className="text-[11px] text-bambu-gray">Schichten 1–2 prüft der Erste-Schicht-Inspektor</span>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-bambu-dark-tertiary">
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 cursor-pointer text-xs text-white">
                    <input
                      type="checkbox"
                      checked={currentConfig.auto_pause}
                      onChange={(e) => handleToggleAutoPause(e.target.checked)}
                      disabled={!canControl}
                      className="rounded accent-bambu-green w-4 h-4 cursor-pointer"
                    />
                    <span>Druck bei bestätigtem Fehldruck automatisch pausieren</span>
                  </label>
                </div>

                {canControl && Object.keys(formConfig).length > 0 && (
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={handleSave}
                    disabled={saveMutation.isPending}
                    className="flex items-center gap-1.5"
                  >
                    <Save className="w-3.5 h-3.5" />
                    <span>Änderungen speichern</span>
                  </Button>
                )}
              </div>
            </div>

            {/* Sofort-Test & Live-Prüfung */}
            <div className="p-4 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                    <Camera className="w-4 h-4 text-bambu-green" />
                    <span>Sofort-Prüfung & Diagnose</span>
                  </h3>
                  <p className="text-xs text-bambu-gray mt-0.5">
                    Live-Kamerabild abrufen oder Foto hochladen zur sofortigen Edge-Entropie-Analyse
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <label className="cursor-pointer">
                    <input
                      type="file"
                      accept="image/*"
                      onChange={(e) => {
                        if (e.target.files?.[0]) {
                          setUploadFile(e.target.files[0]);
                        }
                      }}
                      className="hidden"
                    />
                    <div className="px-3 py-1.5 bg-bambu-dark-tertiary hover:bg-zinc-700 text-white rounded-lg text-xs flex items-center gap-1.5 transition-colors">
                      <Upload className="w-3.5 h-3.5 text-bambu-gray" />
                      <span>{uploadFile ? uploadFile.name : 'Testbild wählen'}</span>
                    </div>
                  </label>

                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => testMutation.mutate()}
                    disabled={!canControl || testMutation.isPending}
                    className="flex items-center gap-1.5"
                  >
                    {testMutation.isPending ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin text-bambu-green" />
                    ) : (
                      <Eye className="w-3.5 h-3.5 text-bambu-green" />
                    )}
                    <span>Jetzt analysieren</span>
                  </Button>
                </div>
              </div>

              {testResult && (
                <div className="p-4 bg-bambu-dark rounded-xl border border-bambu-dark-tertiary space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {testResult.result.is_failure ? (
                        <AlertOctagon className="w-5 h-5 text-red-500" />
                      ) : (
                        <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                      )}
                      <span className="font-semibold text-sm text-white">
                        {testResult.result.is_failure
                          ? 'Fehldruck / Spaghetti erkannt!'
                          : 'Schichtstruktur unauffällig'}
                      </span>
                    </div>
                    <span
                      className={`text-xs px-2 py-0.5 rounded font-mono font-bold ${
                        testResult.result.is_failure
                          ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                          : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      }`}
                    >
                      Chaos-Score: {(testResult.result.chaos_score * 100).toFixed(0)}%
                    </span>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                    <div className="p-2 bg-bambu-dark-secondary rounded-lg">
                      <div className="text-bambu-gray">Orientierungs-Entropie</div>
                      <div className="font-bold text-white mt-0.5">
                        {testResult.result.orientation_entropy.toFixed(3)}
                      </div>
                    </div>
                    <div className="p-2 bg-bambu-dark-secondary rounded-lg">
                      <div className="text-bambu-gray">Kantendichte</div>
                      <div className="font-bold text-white mt-0.5">
                        {(testResult.result.edge_density * 100).toFixed(2)}%
                      </div>
                    </div>
                    <div className="p-2 bg-bambu-dark-secondary rounded-lg">
                      <div className="text-bambu-gray">Fragment-Cluster</div>
                      <div className="font-bold text-white mt-0.5">
                        {testResult.result.fragment_count} Fragmente
                      </div>
                    </div>
                    <div className="p-2 bg-bambu-dark-secondary rounded-lg">
                      <div className="text-bambu-gray">Konfidenz</div>
                      <div className="font-bold text-white mt-0.5">
                        {(testResult.result.confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  </div>

                  {testResult.result.debug_image_b64 && (
                    <div className="mt-3">
                      <div className="text-xs text-bambu-gray mb-1.5 flex items-center justify-between">
                        <span>Annotierte Bildvorschau (Druckbett-ROI & Bounding-Box):</span>
                        {testResult.result.bounding_box && (
                          <span className="text-red-400 font-mono">
                            Cluster: [{testResult.result.bounding_box.join(', ')}]
                          </span>
                        )}
                      </div>
                      <div className="rounded-lg overflow-hidden border border-bambu-dark-tertiary max-h-96 flex items-center justify-center bg-black">
                        <img
                          src={testResult.result.debug_image_b64}
                          alt="Schichtanalyse Annotiert"
                          className="max-h-96 w-auto object-contain"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Prüfhistorie */}
            {statusData?.history && statusData.history.length > 0 && (
              <div className="space-y-2">
                <div className="text-xs font-semibold text-bambu-gray uppercase tracking-wider">
                  Letzte Schichtprüfungen ({statusData.history.length})
                </div>
                <div className="overflow-x-auto rounded-xl border border-bambu-dark-tertiary">
                  <table className="w-full text-xs text-left text-zinc-300">
                    <thead className="bg-bambu-dark-secondary text-bambu-gray border-b border-bambu-dark-tertiary">
                      <tr>
                        <th className="px-3 py-2">Zeit</th>
                        <th className="px-3 py-2">Schicht</th>
                        <th className="px-3 py-2">Chaos-Score</th>
                        <th className="px-3 py-2">Entropie</th>
                        <th className="px-3 py-2">Kanten</th>
                        <th className="px-3 py-2">Status / Aktion</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-bambu-dark-tertiary bg-bambu-dark">
                      {statusData.history
                        .slice()
                        .reverse()
                        .map((entry, idx) => (
                          <tr key={idx} className="hover:bg-bambu-dark-secondary/50">
                            <td className="px-3 py-2 text-bambu-gray">
                              {new Date(entry.timestamp).toLocaleTimeString([], {
                                hour: '2-digit',
                                minute: '2-digit',
                                second: '2-digit',
                              })}
                            </td>
                            <td className="px-3 py-2 font-semibold text-white">
                              #{entry.layer_num}
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={`font-mono font-bold ${
                                  entry.is_failure ? 'text-red-400' : 'text-emerald-400'
                                }`}
                              >
                                {(entry.chaos_score * 100).toFixed(0)}%
                              </span>
                            </td>
                            <td className="px-3 py-2 text-bambu-gray">
                              {entry.orientation_entropy.toFixed(2)}
                            </td>
                            <td className="px-3 py-2 text-bambu-gray">
                              {(entry.edge_density * 100).toFixed(1)}%
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={`px-2 py-0.5 rounded text-[10px] font-medium ${
                                  entry.action_taken === 'paused'
                                    ? 'bg-red-500/20 text-red-300 border border-red-500/30'
                                    : entry.is_failure
                                    ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                    : 'bg-emerald-500/10 text-emerald-400'
                                }`}
                              >
                                {entry.action_taken}
                              </span>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

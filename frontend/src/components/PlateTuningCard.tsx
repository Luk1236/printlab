import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ScanSearch } from 'lucide-react';

import { api } from '../api/client';
import type { PlateTuningAnalysis } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

/**
 * Leerbett-Prüfung einmessen: Fotos mit leerem und mit belegtem Bett hochladen, Messwerte ansehen und den vorgeschlagenen
 * Schwellwert übernehmen. Die Bilder werden nur ausgewertet, nicht gespeichert.
 */
export function PlateTuningCard({ canControl }: { canControl: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [printerId, setPrinterId] = useState<number | null>(null);
  const [empty, setEmpty] = useState<File[]>([]);
  const [occupied, setOccupied] = useState<File[]>([]);
  const [analysis, setAnalysis] = useState<PlateTuningAnalysis | null>(null);

  const { data: printers } = useQuery({ queryKey: ['printers'], queryFn: api.getPrinters });
  const selected = printerId ?? printers?.[0]?.id ?? null;
  const { data: tuning } = useQuery({
    queryKey: ['plateTuning', selected],
    queryFn: () => api.getPlateTuning(selected as number),
    enabled: selected !== null,
  });

  const analyze = useMutation({
    mutationFn: () => api.analyzePlateTuning(selected as number, empty, occupied),
    onSuccess: setAnalysis,
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const apply = useMutation({
    mutationFn: (threshold: number) => api.savePlateTuning(selected as number, threshold),
    onSuccess: () => {
      showToast(t('plateTuning.applied'));
      queryClient.invalidateQueries({ queryKey: ['plateTuning'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const reset = useMutation({
    mutationFn: () => api.resetPlateTuning(selected as number),
    onSuccess: () => {
      showToast(t('plateTuning.resetDone'));
      queryClient.invalidateQueries({ queryKey: ['plateTuning'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  if (!printers || printers.length === 0) return null;
  const busy = analyze.isPending || apply.isPending || reset.isPending;
  const suggestion = analysis?.suggestion;

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <ScanSearch className="w-5 h-5 text-bambu-green" />
          {t('plateTuning.title')}
        </h2>
        <p className="text-xs text-bambu-gray">{t('plateTuning.description')}</p>
        {tuning && (
          <p className="text-xs text-bambu-gray">
            {t('plateTuning.current', { value: tuning.effective })}
            {tuning.saved === null ? ` (${t('plateTuning.default')})` : ''}
          </p>
        )}

        <label className="text-xs text-bambu-gray block">
          {t('plateTuning.printer')}
          <select
            value={selected ?? ''}
            onChange={(event) => {
              setPrinterId(Number(event.target.value));
              setAnalysis(null);
            }}
            className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
          >
            {printers.map((printer) => (
              <option key={printer.id} value={printer.id}>
                {printer.name}
              </option>
            ))}
          </select>
        </label>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <label className="text-xs text-bambu-gray block">
            {t('plateTuning.emptyImages')}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              onChange={(event) => setEmpty(Array.from(event.target.files ?? []))}
              className="mt-1 block w-full text-xs text-white"
            />
          </label>
          <label className="text-xs text-bambu-gray block">
            {t('plateTuning.occupiedImages')}
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              onChange={(event) => setOccupied(Array.from(event.target.files ?? []))}
              className="mt-1 block w-full text-xs text-white"
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={!canControl || busy || selected === null || empty.length === 0 || occupied.length === 0}
            onClick={() => analyze.mutate()}
          >
            {t('plateTuning.analyze')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={!canControl || busy || selected === null || tuning?.saved === null}
            onClick={() => reset.mutate()}
          >
            {t('plateTuning.reset')}
          </Button>
        </div>

        {analysis && suggestion && (
          <div className="space-y-2 border-t border-bambu-dark-tertiary pt-3" data-testid="plate-tuning-result">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              {[
                [t('plateTuning.emptyImages'), analysis.empty],
                [t('plateTuning.occupiedImages'), analysis.occupied],
              ].map(([label, rows]) => (
                <div key={label as string}>
                  <p className="text-bambu-gray mb-1">{label as string}</p>
                  <ul className="space-y-0.5">
                    {(rows as PlateTuningAnalysis['empty']).map((row, index) => (
                      <li key={`${row.name}-${index}`} className="flex justify-between gap-2">
                        <span className="text-white truncate">{row.name}</span>
                        <span className="font-mono text-white">{row.score.toFixed(2)} %</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
            <p className={`text-sm ${suggestion.quality === 'good' ? 'text-bambu-green' : 'text-amber-700 dark:text-amber-400'}`}>
              {t(`plateTuning.quality.${suggestion.quality}`)}
            </p>
            <p className="text-xs text-bambu-gray">
              {t('plateTuning.suggestion', { threshold: suggestion.threshold, confidence: suggestion.min_confidence })}
              {' · '}
              {t('plateTuning.errors', { missed: suggestion.missed_objects, alarms: suggestion.false_alarms })}
            </p>
            <Button
              size="sm"
              disabled={!canControl || busy || suggestion.missed_objects > 0}
              onClick={() => apply.mutate(suggestion.threshold)}
            >
              {t('plateTuning.apply', { threshold: suggestion.threshold })}
            </Button>
            {suggestion.missed_objects > 0 && <p className="text-xs text-red-700 dark:text-red-400">{t('plateTuning.blocked')}</p>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

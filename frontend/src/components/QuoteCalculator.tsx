import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Calculator, Settings } from 'lucide-react';

import { api } from '../api/client';
import type { QuoteResponse } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

const fmt = (value: number, currency: string) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value || 0);

/**
 * Angebotskalkulator: Material, Energie, Arbeit und Aufschlag zu einem
 * Angebotspreis zusammenrechnen. Die Raten kommen aus den Einstellungen und
 * sind hier direkt einstellbar; die Materialrate ist zusätzlich als
 * Auftrags-Override möglich (z. B. teures TPU).
 */
export function QuoteCalculator() {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const [grams, setGrams] = useState('');
  const [durationMinutes, setDurationMinutes] = useState('');
  const [laborMinutes, setLaborMinutes] = useState('');
  const [rateOverride, setRateOverride] = useState<string | null>(null);
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [showRates, setShowRates] = useState(false);

  const { data: settings } = useQuery({ queryKey: ['quoteSettings'], queryFn: api.getSettings });
  const currency = settings?.currency ?? 'EUR';
  const defaultRate = settings?.default_filament_cost ?? '';

  const [laborRate, setLaborRate] = useState('');
  const [markupPercent, setMarkupPercent] = useState('');
  const [powerWatts, setPowerWatts] = useState('');
  const ratesLoaded = settings?.labor_rate_per_hour !== undefined;
  const settingsMutation = useMutation({
    mutationFn: () =>
      api.updateSettings({
        labor_rate_per_hour: Number(laborRate) || 0,
        quote_markup_percent: Number(markupPercent) || 0,
        printer_power_watts: Number(powerWatts) || 120,
      } as any),
    onSuccess: async () => {
      showToast(t('common.success'));
      setShowRates(false);
      await queryClient.invalidateQueries({ queryKey: ['quoteSettings'] });
    },
    onError: (error: Error) => showToast(error.message),
  });

  const rate = rateOverride === null ? String(defaultRate) : rateOverride;
  const canCompute = Number(grams) >= 0 && Number(durationMinutes) >= 0;

  const compute = () => {
    api
      .getQuote({
        grams: Number(grams) || 0,
        duration_minutes: Number(durationMinutes) || 0,
        labor_minutes: Number(laborMinutes) || 0,
        filament_cost_per_kg: rate === '' ? undefined : Number(rate),
        currency,
      })
      .then(setQuote)
      .catch(() => setQuote(null));
  };

  const row = (key: string, value: number) => (
    <div className="flex justify-between text-sm">
      <span className="text-bambu-gray">{t(key)}</span>
      <span className="text-bambu-gray-light font-medium">{fmt(value, currency)}</span>
    </div>
  );

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Calculator className="w-5 h-5 text-bambu-green" />
          {t('quote.title')}
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <label className="text-xs text-bambu-gray">
            {t('quote.grams')} (g)
            <input
              type="number"
              min={0}
              value={grams}
              onChange={(event) => setGrams(event.target.value)}
              className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              aria-label={t('quote.grams')}
            />
          </label>
          <label className="text-xs text-bambu-gray">
            {t('quote.duration')} ({t('quote.minutes')})
            <input
              type="number"
              min={0}
              value={durationMinutes}
              onChange={(event) => setDurationMinutes(event.target.value)}
              className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              aria-label={t('quote.duration')}
            />
          </label>
          <label className="text-xs text-bambu-gray">
            {t('quote.labor')} ({t('quote.minutes')})
            <input
              type="number"
              min={0}
              value={laborMinutes}
              onChange={(event) => setLaborMinutes(event.target.value)}
              className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              aria-label={t('quote.labor')}
            />
          </label>
          <label className="text-xs text-bambu-gray">
            {t('quote.rate')} ({currency}/kg)
            <input
              type="number"
              step="0.01"
              min={0}
              value={rate}
              onChange={(event) => setRateOverride(event.target.value)}
              placeholder={String(defaultRate)}
              className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              aria-label={t('quote.rate')}
            />
          </label>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" disabled={!canCompute} onClick={compute}>
            <Calculator className="w-4 h-4" />
            {t('quote.compute')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (!showRates && ratesLoaded) {
                setLaborRate(String(settings?.labor_rate_per_hour ?? 0));
                setMarkupPercent(String(settings?.quote_markup_percent ?? 0));
                setPowerWatts(String(settings?.printer_power_watts ?? 120));
              }
              setShowRates((open) => !open);
            }}
            title={t('quote.ratesToggle')}
          >
            <Settings className="w-4 h-4" />
            {t('quote.rates')}
          </Button>
        </div>
        {showRates && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 border border-bambu-dark-tertiary rounded-lg p-3">
            <label className="text-xs text-bambu-gray">
              {t('quote.laborRate')} ({currency}/h)
              <input
                type="number"
                step="0.5"
                min={0}
                value={laborRate}
                onChange={(event) => setLaborRate(event.target.value)}
                className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                aria-label={t('quote.laborRate')}
              />
            </label>
            <label className="text-xs text-bambu-gray">
              {t('quote.markupPercent')} (%)
              <input
                type="number"
                step="0.5"
                min={0}
                value={markupPercent}
                onChange={(event) => setMarkupPercent(event.target.value)}
                className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                aria-label={t('quote.markupPercent')}
              />
            </label>
            <label className="text-xs text-bambu-gray">
              {t('quote.power')} (W)
              <input
                type="number"
                step="10"
                min={0}
                value={powerWatts}
                onChange={(event) => setPowerWatts(event.target.value)}
                className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                aria-label={t('quote.power')}
              />
            </label>
            <div className="flex items-end">
              <Button size="sm" disabled={settingsMutation.isPending} onClick={() => settingsMutation.mutate()}>
                {t('common.save')}
              </Button>
            </div>
          </div>
        )}
        {quote && (
          <div className="border-t border-bambu-dark-tertiary pt-3 space-y-1.5">
            {row('quote.material', quote.material)}
            {row('quote.energy', quote.energy)}
            {row('quote.labor', quote.labor)}
            {row('quote.subtotal', quote.subtotal)}
            {row('quote.markup', quote.markup)}
            <div className="flex justify-between text-base font-semibold text-white pt-1">
              <span>{t('quote.total')}</span>
              <span>{fmt(quote.total, quote.currency)}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
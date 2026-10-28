import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Calculator, Printer, Settings } from 'lucide-react';

import { api } from '../api/client';
import type { PriceListEntry, QuoteResponse } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';
import { buildQuoteDocument } from '../utils/quoteDocument';

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
  const [priceListOpen, setPriceListOpen] = useState(false);
  const [priceListDraft, setPriceListDraft] = useState<PriceListEntry[] | null>(null);
  const [customer, setCustomer] = useState('');
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyFilter, setHistoryFilter] = useState('');

  const { data: history } = useQuery({
    queryKey: ['quoteHistory', historyFilter],
    queryFn: () => api.getQuoteHistory(historyFilter.trim() || undefined),
    enabled: historyOpen,
  });
  const saveMutation = useMutation({
    mutationFn: (data: QuoteResponse) =>
      api.saveQuote({
        customer,
        currency: data.currency,
        material: data.material,
        energy: data.energy,
        labor: data.labor,
        subtotal: data.subtotal,
        markup: data.markup,
        total: data.total,
        inputs: data.inputs,
      }),
    onSuccess: () => {
      showToast(t('quote.saved'));
      queryClient.invalidateQueries({ queryKey: ['quoteHistory'] });
    },
    onError: (error: Error) => showToast(error.message),
  });
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteQuote(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['quoteHistory'] }),
    onError: (error: Error) => showToast(error.message),
  });

  const { data: priceList } = useQuery({
    queryKey: ['priceList'],
    queryFn: () => api.getPriceList(),
  });
  const priceListMutation = useMutation({
    mutationFn: () => api.setPriceList(priceListDraft ?? []),
    onSuccess: () => {
      showToast(t('common.success'));
      setPriceListOpen(false);
      setPriceListDraft(null);
      queryClient.invalidateQueries({ queryKey: ['priceList'] });
    },
    onError: (error: Error) => showToast(error.message),
  });

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
      }),
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

  // Angebot als eigenes Druckfenster öffnen; „Als PDF speichern“ im Druckdialog erzeugt das PDF.
  const printQuote = (data: QuoteResponse) => {
    const html = buildQuoteDocument(
      data,
      {
        title: t('quote.title'),
        material: t('quote.material'),
        energy: t('quote.energy'),
        labor: t('quote.labor'),
        subtotal: t('quote.subtotal'),
        markup: t('quote.markup'),
        total: t('quote.total'),
      },
      new Date(),
    );
    const win = window.open('', '_blank', 'width=800,height=900');
    if (!win) {
      showToast(t('common.error'));
      return;
    }
    win.document.open();
    win.document.write(html);
    win.document.close();
    win.focus();
    win.print();
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
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (!priceListOpen && priceListDraft === null) {
                setPriceListDraft((priceList?.entries ?? []).map((entry) => ({ ...entry })));
              }
              setPriceListOpen((open) => !open);
            }}
            title={t('quote.priceList')}
          >
            {t('quote.priceList')}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setHistoryOpen((open) => !open)}>
            {t('quote.history')}
          </Button>
        </div>
        {historyOpen && (
          <div className="border border-bambu-dark-tertiary rounded-lg p-3 space-y-2">
            <input
              value={historyFilter}
              onChange={(event) => setHistoryFilter(event.target.value)}
              placeholder={t('quote.customer')}
              className="w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              aria-label={t('quote.historyFilter')}
            />
            {(history?.customers ?? []).length > 0 && (
              <div className="flex flex-wrap gap-2 text-xs text-bambu-gray" aria-label={t('quote.byCustomer')}>
                {(history?.customers ?? []).map((row) => (
                  <span key={`${row.customer}-${row.currency}`} className="rounded bg-bambu-dark-tertiary px-2 py-1">
                    {row.customer}: {fmt(row.total, row.currency)} ({row.count})
                  </span>
                ))}
              </div>
            )}
            {(history?.entries ?? []).length === 0 ? (
              <p className="text-xs text-bambu-gray">{t('quote.historyEmpty')}</p>
            ) : (
              <div className="space-y-1 max-h-60 overflow-y-auto">
                {(history?.entries ?? []).map((entry) => (
                  <div key={entry.id} className="flex items-center gap-2 text-xs">
                    <span className="text-bambu-gray whitespace-nowrap">{new Date(entry.ts).toLocaleDateString()}</span>
                    <span className="font-medium text-white truncate">{entry.customer}</span>
                    <span className="ml-auto text-bambu-gray-light">{fmt(entry.total, entry.currency)}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${t('common.delete')} ${entry.customer}`}
                      disabled={deleteMutation.isPending}
                      onClick={() => deleteMutation.mutate(entry.id)}
                    >
                      ✕
                    </Button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {priceListOpen && priceListDraft && (
          <div className="border border-bambu-dark-tertiary rounded-lg p-3 space-y-2">
            {priceListDraft.map((entry, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  value={entry.material}
                  onChange={(event) =>
                    setPriceListDraft(
                      (rows) =>
                        rows?.map((r, i) => (i === index ? { ...r, material: event.target.value } : r)) ?? null,
                    )
                  }
                  placeholder="PLA"
                  className="w-28 bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                  aria-label={t('quote.materialName', { index: index + 1 })}
                />
                <input
                  type="number"
                  step="0.5"
                  min={0}
                  value={entry.rate_per_kg}
                  onChange={(event) =>
                    setPriceListDraft(
                      (rows) =>
                        rows?.map((r, i) => (i === index ? { ...r, rate_per_kg: Number(event.target.value) } : r)) ??
                        null,
                    )
                  }
                  className="w-24 bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                  aria-label={`${t('quote.rate')} ${index + 1}`}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setPriceListDraft((rows) => rows?.filter((_, i) => i !== index) ?? null)}
                >
                  ✕
                </Button>
              </div>
            ))}
            <div className="flex justify-between gap-2">
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  setPriceListDraft((rows) => [...(rows ?? []), { material: '', rate_per_kg: Number(defaultRate) || 22 }])
                }
              >
                +
              </Button>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => { setPriceListOpen(false); setPriceListDraft(null); }}>
                  {t('common.cancel')}
                </Button>
                <Button size="sm" disabled={priceListMutation.isPending} onClick={() => priceListMutation.mutate()}>
                  {t('common.save')}
                </Button>
              </div>
            </div>
          </div>
        )}
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
            <div className="flex flex-wrap items-end justify-between gap-2 pt-1">
              <label className="text-xs text-bambu-gray flex-1 min-w-40">
                {t('quote.customer')}
                <input
                  value={customer}
                  maxLength={80}
                  onChange={(event) => setCustomer(event.target.value)}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                  aria-label={t('quote.customer')}
                />
              </label>
              <Button
                size="sm"
                disabled={!customer.trim() || saveMutation.isPending}
                onClick={() => saveMutation.mutate(quote)}
              >
                {t('quote.saveQuote')}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => printQuote(quote)}>
                <Printer className="w-4 h-4" />
                {t('quote.print')}
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
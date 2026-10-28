import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Calculator, Printer, Settings } from 'lucide-react';

import { api } from '../api/client';
import type { CompanyProfile, PriceListEntry, QuoteResponse } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';
import { buildQuoteDocument } from '../utils/quoteDocument';
import { InvoicesPanel } from './InvoicesPanel';

const fmt = (value: number, currency: string) =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value || 0);

/**
 * Angebotskalkulator: Material, Energie, Arbeit und Aufschlag zu einem
 * Angebotspreis zusammenrechnen. Die Raten kommen aus den Einstellungen und
 * sind hier direkt einstellbar; die Materialrate ist zusätzlich als
 * Auftrags-Override möglich (z. B. teures TPU).
 */
export function QuoteCalculator() {
  const { t, i18n } = useTranslation();
  const { showToast } = useToast();
  const pdfLanguage = i18n.language.startsWith('de') ? 'de' : 'en';
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
  const [description, setDescription] = useState('');
  const [customerAddress, setCustomerAddress] = useState('');
  const [companyOpen, setCompanyOpen] = useState(false);
  const [companyDraft, setCompanyDraft] = useState<CompanyProfile | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [invoicesOpen, setInvoicesOpen] = useState(false);
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
        description: description.trim(),
        customer_address: customerAddress.trim(),
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
  const { data: company } = useQuery({ queryKey: ['quoteCompany'], queryFn: api.getCompanyProfile, enabled: companyOpen });
  const draft = companyDraft ?? company ?? null;
  const companyMutation = useMutation({
    mutationFn: (data: CompanyProfile) => api.saveCompanyProfile(data),
    onSuccess: (saved) => {
      showToast(t('common.success'));
      setCompanyDraft(saved);
      queryClient.invalidateQueries({ queryKey: ['quoteCompany'] });
    },
    onError: (error: Error) => showToast(error.message),
  });
  const invoiceMutation = useMutation({
    mutationFn: (quoteId: string) => api.createInvoice(quoteId),
    onSuccess: (invoice) => {
      showToast(t('quote.invoiceCreated', { number: invoice.number }));
      setInvoicesOpen(true);
      queryClient.invalidateQueries({ queryKey: ['invoices'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const logoMutation = useMutation({
    mutationFn: (file: File) => api.uploadCompanyLogo(file),
    onSuccess: () => {
      showToast(t('common.success'));
      setCompanyDraft(null);
      queryClient.invalidateQueries({ queryKey: ['quoteCompany'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const logoDelete = useMutation({
    mutationFn: () => api.deleteCompanyLogo(),
    onSuccess: () => {
      setCompanyDraft(null);
      queryClient.invalidateQueries({ queryKey: ['quoteCompany'] });
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const downloadPdf = async (id: string) => {
    try {
      const { blob, filename } = await api.downloadQuotePdf(id, pdfLanguage);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('common.error'));
    }
  };
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
          <Button size="sm" variant="ghost" onClick={() => setInvoicesOpen((open) => !open)}>
            {t('quote.invoices')}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setCompanyOpen((open) => !open)}
          >
            {t('quote.company')}
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
                    {entry.number && <span className="text-bambu-gray whitespace-nowrap">{entry.number}</span>}
                    <span className="font-medium text-white truncate">{entry.customer}</span>
                    <span className="ml-auto text-bambu-gray-light">{fmt(entry.total, entry.currency)}</span>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${t('quote.createInvoice')} ${entry.customer}`}
                      disabled={invoiceMutation.isPending}
                      onClick={() => invoiceMutation.mutate(entry.id)}
                    >
                      {t('quote.createInvoice')}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${t('quote.pdf')} ${entry.customer}`}
                      onClick={() => downloadPdf(entry.id)}
                    >
                      {t('quote.pdf')}
                    </Button>
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
        {invoicesOpen && <InvoicesPanel canEdit />}
        {companyOpen && (
          <div className="border border-bambu-dark-tertiary rounded-lg p-3 space-y-2">
            {draft !== null && (
              <>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyName')}
                    <input
                      type="text"
                      value={draft.name}
                      onChange={(event) => setCompanyDraft({ ...draft, name: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyAddress')}
                    <input
                      type="text"
                      value={draft.address}
                      onChange={(event) => setCompanyDraft({ ...draft, address: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyEmail')}
                    <input
                      type="text"
                      value={draft.email}
                      onChange={(event) => setCompanyDraft({ ...draft, email: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyPhone')}
                    <input
                      type="text"
                      value={draft.phone}
                      onChange={(event) => setCompanyDraft({ ...draft, phone: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyTaxId')}
                    <input
                      type="text"
                      value={draft.tax_id}
                      onChange={(event) => setCompanyDraft({ ...draft, tax_id: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyIban')}
                    <input
                      type="text"
                      value={draft.iban}
                      onChange={(event) => setCompanyDraft({ ...draft, iban: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyBic')}
                    <input
                      type="text"
                      value={draft.bic}
                      onChange={(event) => setCompanyDraft({ ...draft, bic: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyVat')}
                    <input
                      type="number"
                      step="0.5"
                      min={0}
                      max={30}
                      value={draft.vat_percent}
                      onChange={(event) => setCompanyDraft({ ...draft, vat_percent: Number(event.target.value) })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyValidDays')}
                    <input
                      type="number"
                      min={0}
                      max={365}
                      value={draft.valid_days}
                      onChange={(event) => setCompanyDraft({ ...draft, valid_days: Number(event.target.value) })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyPrefix')}
                    <input
                      type="text"
                      value={draft.number_prefix}
                      onChange={(event) => setCompanyDraft({ ...draft, number_prefix: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyVatNote')}
                    <input
                      type="text"
                      value={draft.vat_note}
                      onChange={(event) => setCompanyDraft({ ...draft, vat_note: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyFooter')}
                    <input
                      type="text"
                      value={draft.footer}
                      onChange={(event) => setCompanyDraft({ ...draft, footer: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                </div>
                <label className="text-xs text-bambu-gray block">
                  {t('quote.companyNumberFormat')}
                  <input
                    type="text"
                    value={draft.number_format}
                    onChange={(event) => setCompanyDraft({ ...draft, number_format: event.target.value })}
                    className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm font-mono"
                  />
                  <span className="block mt-1">{t('quote.companyNumberFormatHint')}</span>
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyInvoicePrefix')}
                    <input
                      type="text"
                      value={draft.invoice_prefix}
                      onChange={(event) => setCompanyDraft({ ...draft, invoice_prefix: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyInvoiceFormat')}
                    <input
                      type="text"
                      value={draft.invoice_format}
                      onChange={(event) => setCompanyDraft({ ...draft, invoice_format: event.target.value })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm font-mono"
                    />
                  </label>
                  <label className="text-xs text-bambu-gray">
                    {t('quote.companyPaymentDays')}
                    <input
                      type="number"
                      min={0}
                      max={365}
                      value={draft.payment_days}
                      onChange={(event) => setCompanyDraft({ ...draft, payment_days: Number(event.target.value) })}
                      className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                    />
                  </label>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-bambu-gray">
                  <span>
                    {t('quote.companyLogo')}: {draft.has_logo ? t('quote.companyLogoSet') : t('quote.companyLogoNone')}
                  </span>
                  <label className="cursor-pointer rounded-lg bg-bambu-dark-tertiary px-2 py-1 text-white hover:opacity-90">
                    {t('quote.companyLogoUpload')}
                    <input
                      type="file"
                      accept="image/png,image/jpeg"
                      className="sr-only"
                      aria-label={t('quote.companyLogoUpload')}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) logoMutation.mutate(file);
                        event.target.value = '';
                      }}
                    />
                  </label>
                  {draft.has_logo && (
                    <Button size="sm" variant="ghost" onClick={() => logoDelete.mutate()}>
                      {t('quote.companyLogoRemove')}
                    </Button>
                  )}
                </div>
                <Button size="sm" disabled={companyMutation.isPending} onClick={() => companyMutation.mutate(draft)}>
                  {t('common.save')}
                </Button>
              </>
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
              <label className="text-xs text-bambu-gray w-full">
                {t('quote.customerAddress')}
                <textarea
                  value={customerAddress}
                  maxLength={240}
                  rows={2}
                  onChange={(event) => setCustomerAddress(event.target.value)}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                  aria-label={t('quote.customerAddress')}
                />
              </label>
              <label className="text-xs text-bambu-gray flex-1 min-w-40">
                {t('quote.description')}
                <input
                  value={description}
                  maxLength={200}
                  onChange={(event) => setDescription(event.target.value)}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                  aria-label={t('quote.description')}
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
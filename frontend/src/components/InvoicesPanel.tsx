import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '../api/client';
import type { Invoice } from '../api/client';
import { Button } from './Button';
import { ConfirmModal } from './ConfirmModal';
import { useToast } from '../contexts/ToastContext';

function fmt(value: number, currency: string): string {
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency}`;
  }
}

/**
 * Rechnungen aus Angeboten: Liste, als bezahlt markieren, stornieren, PDF. Rechnungen lassen sich nicht löschen, nur
 * stornieren (lückenlose Nummern). Enthält keine elektronischen Rechnungsformate; Pflichtangaben klärt die Steuerberatung.
 */
export function InvoicesPanel({ canEdit }: { canEdit: boolean }) {
  const { t, i18n } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [toCancel, setToCancel] = useState<Invoice | null>(null);
  const lang = i18n.language.startsWith('de') ? 'de' : 'en';

  const { data } = useQuery({ queryKey: ['invoices'], queryFn: () => api.getInvoices() });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['invoices'] });
  const fail = (error: Error) => showToast(error.message, 'error');
  const pay = useMutation({ mutationFn: (id: string) => api.markInvoicePaid(id), onSuccess: refresh, onError: fail });
  const reopen = useMutation({ mutationFn: (id: string) => api.reopenInvoice(id), onSuccess: refresh, onError: fail });
  const cancel = useMutation({
    mutationFn: (id: string) => api.cancelInvoice(id),
    onSuccess: () => {
      setToCancel(null);
      refresh();
    },
    onError: (error: Error) => {
      setToCancel(null);
      showToast(error.message, 'error');
    },
  });

  const saveBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  const download = async (invoice: Invoice) => {
    try {
      const { blob, filename } = await api.downloadInvoicePdf(invoice.id, lang);
      saveBlob(blob, filename);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('common.error'), 'error');
    }
  };

  // XRechnung-XML: fehlende Pflichtangaben kommen als lesbare Liste zurück, kein leeres XML.
  const downloadXml = async (invoice: Invoice) => {
    try {
      const { blob, filename } = await api.downloadEInvoiceXml(invoice.id);
      saveBlob(blob, filename);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t('common.error'), 'error');
    }
  };

  if (!data) return null;
  const overdue = new Set(data.overdue_ids);
  const busy = pay.isPending || reopen.isPending || cancel.isPending;

  return (
    <div className="border border-bambu-dark-tertiary rounded-lg p-3 space-y-2" data-testid="invoices-panel">
      <h3 className="text-sm font-medium text-white">{t('invoices.title')}</h3>
      <p className="text-xs text-bambu-gray">{t('invoices.hint')}</p>
      {Object.entries(data.totals).map(([currency, row]) => (
        <p key={currency} className="text-xs text-bambu-gray">
          {t('invoices.totals', {
            open: fmt(row.open, currency),
            overdue: fmt(row.overdue, currency),
            paid: fmt(row.paid, currency),
          })}
        </p>
      ))}
      {data.invoices.length === 0 ? (
        <p className="text-xs text-bambu-gray">{t('invoices.empty')}</p>
      ) : (
        <ul className="space-y-1 max-h-72 overflow-y-auto">
          {data.invoices.map((invoice) => {
            const status = invoice.status === 'open' && overdue.has(invoice.id) ? 'overdue' : invoice.status;
            return (
              <li key={invoice.id} className="flex flex-wrap items-center gap-2 text-xs" data-testid={`invoice-${invoice.id}`}>
                <span className="font-mono text-white">{invoice.number}</span>
                <span className="text-white truncate">{invoice.customer}</span>
                <span className="text-bambu-gray-light">{fmt(invoice.total, invoice.currency)}</span>
                <span className="text-bambu-gray">{t('invoices.due', { date: invoice.due })}</span>
                <span
                  className={
                    status === 'paid'
                      ? 'text-bambu-green'
                      : status === 'overdue'
                        ? 'text-red-700 dark:text-red-400'
                        : status === 'cancelled'
                          ? 'text-bambu-gray line-through'
                          : 'text-amber-700 dark:text-amber-400'
                  }
                >
                  {t(`invoices.status.${status}`)}
                </span>
                <span className="ml-auto flex gap-1">
                  <Button size="sm" variant="ghost" aria-label={`${t('invoices.pdf')} ${invoice.number}`} onClick={() => download(invoice)}>
                    {t('invoices.pdf')}
                  </Button>
                  {invoice.status !== 'cancelled' && (
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`E-Rechnung ${invoice.number}`}
                      title="XRechnung-XML (Pflichtangaben werden vorher geprüft)"
                      onClick={() => downloadXml(invoice)}
                    >
                      E-Rechnung
                    </Button>
                  )}
                  {canEdit && invoice.status === 'open' && (
                    <>
                      <Button size="sm" variant="secondary" disabled={busy} onClick={() => pay.mutate(invoice.id)} aria-label={`${t('invoices.markPaid')} ${invoice.number}`}>
                        {t('invoices.markPaid')}
                      </Button>
                      <Button size="sm" variant="ghost" disabled={busy} onClick={() => setToCancel(invoice)} aria-label={`${t('invoices.cancel')} ${invoice.number}`}>
                        {t('invoices.cancel')}
                      </Button>
                    </>
                  )}
                  {canEdit && invoice.status === 'paid' && (
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => reopen.mutate(invoice.id)} aria-label={`${t('invoices.reopen')} ${invoice.number}`}>
                      {t('invoices.reopen')}
                    </Button>
                  )}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {toCancel && (
        <ConfirmModal
          title={t('invoices.cancelConfirmTitle')}
          message={t('invoices.cancelConfirmMessage', { number: toCancel.number })}
          confirmText={t('invoices.cancelConfirmButton')}
          cancelText={t('common.cancel')}
          variant="danger"
          isLoading={cancel.isPending}
          onCancel={() => setToCancel(null)}
          onConfirm={() => cancel.mutate(toCancel.id)}
        />
      )}
    </div>
  );
}

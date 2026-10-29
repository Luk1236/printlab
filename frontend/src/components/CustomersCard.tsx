import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Loader2, Trash2, UserPlus, Users } from 'lucide-react';

import { api } from '../api/client';
import type { Customer } from '../api/forkApi';
import { Button } from './Button';
import { ConfirmModal } from './ConfirmModal';
import { useToast } from '../contexts/ToastContext';

/**
 * Kunden-Stamm (leichtgewichtig): Adressbuch für Angebote und Rechnungen.
 * Belege behalten ihre Kopie von Kunde und Anschrift — hier liegt nur das
 * Adressbuch darunter, Löschen ändert frühere Belege nicht.
 */
export function CustomersCard({ canEdit }: { canEdit: boolean }) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [toDelete, setToDelete] = useState<Customer | null>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({ name: '', address: '', email: '', phone: '' });

  const { data: customers, isLoading } = useQuery({ queryKey: ['customers'], queryFn: api.listCustomers });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['customers'] });
  const create = useMutation({
    mutationFn: () => api.createCustomer(draft),
    onSuccess: () => {
      setDraft({ name: '', address: '', email: '', phone: '' });
      setOpen(false);
      invalidate();
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });
  const remove = useMutation({
    mutationFn: (id: number) => api.deleteCustomer(id),
    onSuccess: () => {
      setToDelete(null);
      invalidate();
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  return (
    <div className="border border-bambu-dark-tertiary rounded-lg p-3 space-y-2" data-testid="customers-card">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-white">
          <Users className="w-4 h-4" />
          {t('customers.title')}
        </h3>
        {canEdit && (
          <Button size="sm" variant="ghost" onClick={() => setOpen((value) => !value)} aria-label={t('customers.add')}>
            <UserPlus className="w-4 h-4" />
          </Button>
        )}
      </div>
      <p className="text-xs text-bambu-gray">{t('customers.hint')}</p>
      {open && canEdit && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2" data-testid="customers-form">
          <input
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            placeholder={t('customers.name')}
            aria-label={t('customers.name')}
            className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
          />
          <input
            value={draft.address}
            onChange={(event) => setDraft({ ...draft, address: event.target.value })}
            placeholder={t('customers.address')}
            aria-label={t('customers.address')}
            className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
          />
          <input
            value={draft.email}
            onChange={(event) => setDraft({ ...draft, email: event.target.value })}
            placeholder={t('customers.email')}
            aria-label={t('customers.email')}
            className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
          />
          <input
            value={draft.phone}
            onChange={(event) => setDraft({ ...draft, phone: event.target.value })}
            placeholder={t('customers.phone')}
            aria-label={t('customers.phone')}
            className="bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
          />
          <Button
            size="sm"
            disabled={!draft.name.trim() || create.isPending}
            onClick={() => create.mutate()}
            className="sm:col-span-2"
          >
            {t('customers.save')}
          </Button>
        </div>
      )}
      {isLoading ? (
        <Loader2 className="w-4 h-4 animate-spin text-bambu-gray" />
      ) : !customers || customers.length === 0 ? (
        <div className="text-sm text-bambu-gray">{t('customers.empty')}</div>
      ) : (
        <ul className="space-y-1">
          {customers.map((customer) => (
            <li key={customer.id} className="flex items-center gap-2 text-xs" data-testid={`customer-${customer.id}`}>
              <span className="text-white font-medium">{customer.name}</span>
              {customer.address && <span className="text-bambu-gray truncate max-w-48">{customer.address}</span>}
              {customer.email && <span className="text-bambu-gray truncate max-w-40">{customer.email}</span>}
              {canEdit && (
                <button
                  onClick={() => setToDelete(customer)}
                  className="ml-auto text-bambu-gray hover:text-red-400"
                  aria-label={`${t('common.delete')} ${customer.name}`}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {toDelete && (
        <ConfirmModal
          title={t('customers.deleteTitle', { name: toDelete.name })}
          message={t('customers.deleteText')}
          confirmText={t('common.delete')}
          cancelText={t('common.cancel')}
          variant="danger"
          isLoading={remove.isPending}
          onCancel={() => setToDelete(null)}
          onConfirm={() => remove.mutate(toDelete.id)}
        />
      )}
    </div>
  );
}
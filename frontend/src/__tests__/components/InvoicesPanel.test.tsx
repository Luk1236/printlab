import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { InvoicesPanel } from '../../components/InvoicesPanel';

const base = {
  quote_id: 'q',
  quote_number: 'A-1',
  issued: '2026-10-01',
  service_date: '2026-10-01',
  paid_at: null,
  customer_address: '',
  description: 'Teil',
  currency: 'EUR',
};
const open = { ...base, id: 'i1', number: 'R-2026-0001', status: 'open', due: '2026-10-15', customer: 'Alpha', total: 10 };
const paid = { ...base, id: 'i2', number: 'R-2026-0002', status: 'paid', due: '2026-10-20', customer: 'Beta', total: 5 };

function use(invoices: object[], overdue: string[] = []) {
  server.use(
    http.get('/api/v1/quote/invoices', () =>
      HttpResponse.json({ invoices, totals: { EUR: { open: 10, overdue: overdue.length ? 10 : 0, paid: 5 } }, overdue_ids: overdue }),
    ),
  );
}

describe('InvoicesPanel', () => {
  it('lists invoices with totals and marks an overdue one', async () => {
    use([open, paid], ['i1']);
    render(<InvoicesPanel canEdit />);
    expect(await screen.findByTestId('invoice-i1')).toHaveTextContent('R-2026-0001');
    expect(screen.getByTestId('invoice-i1')).toHaveTextContent('overdue');
    expect(screen.getByTestId('invoice-i2')).toHaveTextContent('paid');
    expect(screen.getByText(/Electronic invoice formats/)).toBeInTheDocument();
  });

  it('shows an empty hint', async () => {
    use([]);
    render(<InvoicesPanel canEdit />);
    expect(await screen.findByText(/No invoices yet/)).toBeInTheDocument();
  });

  it('marks an invoice as paid', async () => {
    use([open]);
    let called = false;
    server.use(
      http.post('/api/v1/quote/invoices/i1/paid', () => {
        called = true;
        return HttpResponse.json({ ...open, status: 'paid' });
      }),
    );
    render(<InvoicesPanel canEdit />);
    await userEvent.click(await screen.findByRole('button', { name: 'Paid R-2026-0001' }));
    await waitFor(() => expect(called).toBe(true));
  });

  it('asks before cancelling and cancels on confirm', async () => {
    use([open]);
    let called = false;
    server.use(
      http.post('/api/v1/quote/invoices/i1/cancel', () => {
        called = true;
        return HttpResponse.json({ ...open, status: 'cancelled' });
      }),
    );
    render(<InvoicesPanel canEdit />);
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel R-2026-0001' }));
    expect(await screen.findByText('Cancel invoice?')).toBeInTheDocument();
    expect(called).toBe(false);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel invoice' }));
    await waitFor(() => expect(called).toBe(true));
  });

  it('reopens a paid invoice and hides edit buttons without permission', async () => {
    use([paid]);
    const { unmount } = render(<InvoicesPanel canEdit />);
    expect(await screen.findByRole('button', { name: 'Reopen R-2026-0002' })).toBeInTheDocument();
    unmount();
    render(<InvoicesPanel canEdit={false} />);
    await screen.findByTestId('invoice-i2');
    expect(screen.queryByRole('button', { name: /Reopen/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'PDF R-2026-0002' })).toBeInTheDocument();
  });
});

import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { QuoteCalculator } from '../../components/QuoteCalculator';

const quoteBody = {
  currency: 'EUR',
  inputs: {},
  material: 2.2,
  energy: 0.5,
  labor: 5,
  subtotal: 7.7,
  markup: 1.54,
  total: 9.24,
};

function setup(calls: { quote: string[]; prices: unknown[] } = { quote: [], prices: [] }) {
  server.use(
    http.get('/api/v1/settings/', () =>
      HttpResponse.json({
        currency: 'EUR',
        default_filament_cost: 22,
        labor_rate_per_hour: 30,
        quote_markup_percent: 20,
        printer_power_watts: 120,
      }),
    ),
    http.get('/api/v1/quote/price-list', () =>
      HttpResponse.json({ entries: [{ material: 'PLA', rate_per_kg: 22 }, { material: 'TPU', rate_per_kg: 45 }] }),
    ),
    http.get('/api/v1/quote', ({ request }) => {
      calls.quote.push(new URL(request.url).search);
      return HttpResponse.json(quoteBody);
    }),
    http.put('/api/v1/quote/price-list', async ({ request }) => {
      const body = await request.json();
      calls.prices.push(body);
      return HttpResponse.json({ entries: body });
    }),
  );
  return calls;
}

describe('QuoteCalculator', () => {
  it('sends the inputs to the quote endpoint and shows the total', async () => {
    const calls = setup();
    render(<QuoteCalculator />);
    await userEvent.type(await screen.findByLabelText('Filament'), '100');
    await userEvent.type(screen.getByLabelText('Print time'), '120');
    await userEvent.click(screen.getByRole('button', { name: /Calculate/i }));
    await waitFor(() => expect(calls.quote.length).toBe(1));
    expect(calls.quote[0]).toContain('grams=100');
    expect(calls.quote[0]).toContain('duration_minutes=120');
    expect(await screen.findByText(/9[.,]24/)).toBeInTheDocument();
  });

  it('uses a rate override for the material', async () => {
    const calls = setup();
    render(<QuoteCalculator />);
    const rate = await screen.findByLabelText('Material rate');
    await waitFor(() => expect(rate).toHaveValue(22));
    await userEvent.clear(rate);
    await userEvent.type(rate, '45');
    await userEvent.type(screen.getByLabelText('Filament'), '50');
    await userEvent.type(screen.getByLabelText('Print time'), '30');
    await userEvent.click(screen.getByRole('button', { name: /Calculate/i }));
    await waitFor(() => expect(calls.quote.length).toBe(1));
    expect(calls.quote[0]).toContain('filament_cost_per_kg=45');
  });

  it('edits and saves the price list', async () => {
    const calls = setup();
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'Price list' }));
    const material = await screen.findByDisplayValue('TPU');
    await userEvent.clear(material);
    await userEvent.type(material, 'PETG');
    await userEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() => expect(calls.prices.length).toBe(1));
    expect(calls.prices[0]).toEqual([
      { material: 'PLA', rate_per_kg: 22 },
      { material: 'PETG', rate_per_kg: 45 },
    ]);
  });

  it('removes a price list row', async () => {
    const calls = setup();
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'Price list' }));
    await screen.findByDisplayValue('TPU');
    await userEvent.click(screen.getAllByRole('button', { name: '✕' })[1]);
    await userEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() => expect(calls.prices.length).toBe(1));
    expect(calls.prices[0]).toEqual([{ material: 'PLA', rate_per_kg: 22 }]);
  });
});

describe('QuoteCalculator history', () => {
  const entry = { id: 'a1', ts: '2026-10-27T10:00:00+00:00', customer: 'Müller GmbH', description: '', currency: 'EUR', material: 2.2, energy: 0.5, labor: 5, subtotal: 7.7, markup: 1.54, total: 9.24 };

  function setupHistory(calls: { saved: unknown[]; deleted: string[] }) {
    setup();
    server.use(
      http.get('/api/v1/quote/history', () =>
        HttpResponse.json({ entries: [entry], customers: [{ customer: 'Müller GmbH', currency: 'EUR', count: 1, total: 9.24 }] }),
      ),
      http.post('/api/v1/quote/history', async ({ request }) => {
        calls.saved.push(await request.json());
        return HttpResponse.json(entry);
      }),
      http.delete('/api/v1/quote/history/:id', ({ params }) => {
        calls.deleted.push(String(params.id));
        return HttpResponse.json({ success: true });
      }),
    );
  }

  it('saves a computed quote under a customer name', async () => {
    const calls = { saved: [] as unknown[], deleted: [] as string[] };
    setupHistory(calls);
    render(<QuoteCalculator />);
    await userEvent.type(await screen.findByLabelText('Filament'), '100');
    await userEvent.type(screen.getByLabelText('Print time'), '60');
    await userEvent.click(screen.getByRole('button', { name: /Calculate/i }));
    const save = await screen.findByRole('button', { name: 'Save quote' });
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText('Customer'), 'Müller GmbH');
    await userEvent.click(save);
    await waitFor(() => expect(calls.saved.length).toBe(1));
    expect(calls.saved[0]).toMatchObject({ customer: 'Müller GmbH', total: 9.24, currency: 'EUR' });
  });

  it('shows the history with totals per customer and deletes an entry', async () => {
    const calls = { saved: [] as unknown[], deleted: [] as string[] };
    setupHistory(calls);
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    expect(await screen.findByText(/Müller GmbH: .*9[.,]24.*\(1\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Delete Müller GmbH/ }));
    await waitFor(() => expect(calls.deleted).toEqual(['a1']));
  });
});

describe('QuoteCalculator company data and PDF', () => {
  const company = {
    name: 'PrintLab Muster',
    address: '',
    tax_id: '',
    email: '',
    phone: '',
    iban: '',
    bic: '',
    footer: '',
    vat_percent: 0,
    vat_note: '',
    valid_days: 14,
    number_prefix: 'A',
  };

  function setupCompany(calls: { saved: unknown[]; pdf: string[]; description: unknown[] }) {
    server.use(
      http.get('/api/v1/settings/', () => HttpResponse.json({ currency: 'EUR' })),
      http.get('/api/v1/quote/price-list', () => HttpResponse.json({ entries: [] })),
      http.get('/api/v1/quote/company', () => HttpResponse.json(company)),
      http.put('/api/v1/quote/company', async ({ request }) => {
        const body = await request.json();
        calls.saved.push(body);
        return HttpResponse.json(body);
      }),
      http.get('/api/v1/quote/history', () =>
        HttpResponse.json({
          entries: [
            { id: 'a1', ts: '2026-10-28T10:00:00Z', customer: 'Müller GmbH', number: 'A-2026-0001', description: '', currency: 'EUR', material: 1, energy: 1, labor: 1, subtotal: 3, markup: 0.6, total: 3.6 },
          ],
          customers: [],
        }),
      ),
      http.get('/api/v1/quote/history/:id/pdf', ({ params, request }) => {
        calls.pdf.push(`${String(params.id)}${new URL(request.url).search}`);
        return new HttpResponse('%PDF-1.4', {
          headers: { 'Content-Type': 'application/pdf', 'Content-Disposition': 'attachment; filename="Angebot-A-2026-0001.pdf"' },
        });
      }),
    );
  }

  it('shows the quote number and downloads the PDF', async () => {
    const calls = { saved: [] as unknown[], pdf: [] as string[], description: [] as unknown[] };
    setupCompany(calls);
    URL.createObjectURL = () => 'blob:test';
    URL.revokeObjectURL = () => undefined;
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    expect(await screen.findByText('A-2026-0001')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /PDF Müller GmbH/ }));
    await waitFor(() => expect(calls.pdf).toEqual(['a1?lang=en']));
  });

  it('creates an invoice from a quote and opens the invoice list', async () => {
    const calls = { saved: [] as unknown[], pdf: [] as string[], description: [] as unknown[] };
    setupCompany(calls);
    const created: string[] = [];
    server.use(
      http.post('/api/v1/quote/history/:id/invoice', ({ params }) => {
        created.push(String(params.id));
        return HttpResponse.json({ id: 'i1', number: 'R-2026-0001', status: 'open', customer: 'Müller GmbH', total: 3.6, currency: 'EUR', due: '2026-11-11' });
      }),
      http.get('/api/v1/quote/invoices', () =>
        HttpResponse.json({
          invoices: [{ id: 'i1', number: 'R-2026-0001', status: 'open', customer: 'Müller GmbH', total: 3.6, currency: 'EUR', due: '2026-11-11' }],
          totals: { EUR: { open: 3.6, overdue: 0, paid: 0 } },
          overdue_ids: [],
        }),
      ),
    );
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    await userEvent.click(await screen.findByRole('button', { name: /Invoice Müller GmbH/ }));
    await waitFor(() => expect(created).toEqual(['a1']));
    expect(await screen.findByTestId('invoices-panel')).toHaveTextContent('R-2026-0001');
  });

  it('loads, edits and saves the company data', async () => {
    const calls = { saved: [] as unknown[], pdf: [] as string[], description: [] as unknown[] };
    setupCompany(calls);
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'Company details' }));
    const name = await screen.findByLabelText('Company name');
    expect(name).toHaveValue('PrintLab Muster');
    await userEvent.clear(name);
    await userEvent.type(name, 'PrintLab Neu');
    await userEvent.clear(screen.getByLabelText('VAT (%)'));
    await userEvent.type(screen.getByLabelText('VAT (%)'), '19');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.saved.length).toBe(1));
    expect(calls.saved[0]).toMatchObject({ name: 'PrintLab Neu', vat_percent: 19, number_prefix: 'A' });
  });
});

describe('QuoteCalculator number format, logo and customer address', () => {
  const company = {
    name: 'PrintLab Muster',
    address: '',
    tax_id: '',
    email: '',
    phone: '',
    iban: '',
    bic: '',
    footer: '',
    vat_percent: 0,
    vat_note: '',
    valid_days: 14,
    number_prefix: 'A',
    number_format: '{prefix}-{year}-{seq4}',
    has_logo: false,
  };

  function setupExtras(calls: { saved: unknown[]; logo: string[]; quote: unknown[] }, hasLogo = false) {
    server.use(
      http.get('/api/v1/settings/', () => HttpResponse.json({ currency: 'EUR' })),
      http.get('/api/v1/quote/price-list', () => HttpResponse.json({ entries: [] })),
      http.get('/api/v1/quote/company', () => HttpResponse.json({ ...company, has_logo: hasLogo })),
      http.put('/api/v1/quote/company', async ({ request }) => {
        const body = await request.json();
        calls.saved.push(body);
        return HttpResponse.json(body);
      }),
      http.put('/api/v1/quote/company/logo', () => {
        calls.logo.push('upload');
        return HttpResponse.json({ has_logo: true });
      }),
      http.delete('/api/v1/quote/company/logo', () => {
        calls.logo.push('delete');
        return HttpResponse.json({ deleted: true });
      }),
      http.get('/api/v1/quote', () =>
        HttpResponse.json({ currency: 'EUR', inputs: {}, material: 1, energy: 1, labor: 1, subtotal: 3, markup: 0.6, total: 3.6 }),
      ),
      http.post('/api/v1/quote/history', async ({ request }) => {
        calls.quote.push(await request.json());
        return HttpResponse.json({ id: 'a1', number: 'A-2026-0001' });
      }),
    );
  }

  it('edits and saves the number format', async () => {
    const calls = { saved: [] as unknown[], logo: [] as string[], quote: [] as unknown[] };
    setupExtras(calls);
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'Company details' }));
    const format = await screen.findByLabelText(/Number format/);
    expect(format).toHaveValue('{prefix}-{year}-{seq4}');
    await userEvent.clear(format);
    await userEvent.type(format, '{{prefix}{{yy}/{{seq}');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.saved.length).toBe(1));
    expect(calls.saved[0]).toMatchObject({ number_format: '{prefix}{yy}/{seq}' });
  });

  it('uploads a logo', async () => {
    const calls = { saved: [] as unknown[], logo: [] as string[], quote: [] as unknown[] };
    setupExtras(calls);
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'Company details' }));
    expect(await screen.findByText(/^Logo: none$/)).toBeInTheDocument();
    await userEvent.upload(
      screen.getByLabelText('Upload logo (PNG/JPEG)'),
      new File(['x'], 'logo.png', { type: 'image/png' }),
    );
    await waitFor(() => expect(calls.logo).toEqual(['upload']));
  });

  it('shows a stored logo and can remove it', async () => {
    const calls = { saved: [] as unknown[], logo: [] as string[], quote: [] as unknown[] };
    setupExtras(calls, true);
    render(<QuoteCalculator />);
    await userEvent.click(await screen.findByRole('button', { name: 'Company details' }));
    expect(await screen.findByText(/^Logo: stored$/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Remove logo' }));
    await waitFor(() => expect(calls.logo).toEqual(['delete']));
  });

  it('sends the customer address with a saved quote', async () => {
    const calls = { saved: [] as unknown[], logo: [] as string[], quote: [] as unknown[] };
    setupExtras(calls);
    render(<QuoteCalculator />);
    await userEvent.type(await screen.findByLabelText('Filament'), '100');
    await userEvent.type(screen.getByLabelText('Print time'), '60');
    await userEvent.click(screen.getByRole('button', { name: /Calculate/i }));
    await userEvent.type(await screen.findByLabelText('Customer'), 'Müller GmbH');
    await userEvent.type(screen.getByLabelText('Customer address (optional)'), 'Musterweg 3');
    await userEvent.click(screen.getByRole('button', { name: 'Save quote' }));
    await waitFor(() => expect(calls.quote.length).toBe(1));
    expect(calls.quote[0]).toMatchObject({ customer: 'Müller GmbH', customer_address: 'Musterweg 3' });
  });
});

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

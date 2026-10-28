import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { QuoteActualsPanel } from '../../components/QuoteActualsPanel';

const empty = {
  quote_id: 'q1', currency: 'EUR', linked: 0, lines: [], grams: 0, minutes: 0, material: 0, energy: 0, labor: 5,
  actual_cost: 5, quoted_cost: 8, deviation: -3, revenue: 9.6, profit: 4.6, missing_ids: [],
};
const linked = {
  ...empty,
  linked: 1,
  lines: [{ archive_id: 7, filename: 'Gehaeuse', status: 'completed', grams: 100, minutes: 60, material: 3, energy: 0.5, estimated: true }],
  material: 3, energy: 0.5, actual_cost: 8.5, deviation: 0.5, profit: 1.1,
};

function use(actuals: object, calls: number[][] = []) {
  server.use(
    http.get('/api/v1/quote/history/q1/actuals', () => HttpResponse.json(actuals)),
    http.get('/api/v1/archives/', () => HttpResponse.json([{ id: 7, filename: 'a.3mf', print_name: 'Gehaeuse' }, { id: 9, filename: 'b.3mf', print_name: 'Deckel' }])),
    http.put('/api/v1/quote/history/q1/archives', async ({ request }) => {
      const body = (await request.json()) as { archive_ids: number[] };
      calls.push(body.archive_ids);
      return HttpResponse.json({ archive_ids: body.archive_ids });
    }),
  );
}

describe('QuoteActualsPanel', () => {
  it('shows a hint and no summary when nothing is linked, and links a print', async () => {
    const calls: number[][] = [];
    use(empty, calls);
    render(<QuoteActualsPanel quoteId="q1" />);
    expect(await screen.findByText('No print linked yet.')).toBeInTheDocument();
    expect(screen.queryByTestId('quote-actuals-summary')).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Choose a print'), '9');
    await userEvent.click(screen.getByRole('button', { name: 'Link' }));
    await waitFor(() => expect(calls).toEqual([[9]]));
  });

  it('shows actual versus quoted cost, marks estimates and flags an overrun', async () => {
    use(linked);
    render(<QuoteActualsPanel quoteId="q1" />);
    const summary = await screen.findByTestId('quote-actuals-summary');
    expect(summary).toHaveTextContent(/8[.,]50/);
    expect(summary).toHaveTextContent(/\+.*0[.,]50/);
    expect(screen.getByText('Gehaeuse')).toBeInTheDocument();
    expect(screen.getByText(/\(estimated\)/)).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Deckel/ })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: /Gehaeuse/ })).not.toBeInTheDocument();
  });

  it('unlinks a print and warns about prints missing from the archive', async () => {
    const calls: number[][] = [];
    use({ ...linked, missing_ids: [42] }, calls);
    render(<QuoteActualsPanel quoteId="q1" />);
    expect(await screen.findByText(/No longer in the archive: 42/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Unlink #7' }));
    await waitFor(() => expect(calls).toEqual([[42]]));
  });
});

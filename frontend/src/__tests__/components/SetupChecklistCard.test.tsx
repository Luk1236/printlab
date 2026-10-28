import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, within } from '@testing-library/react';
import { server } from '../mocks/server';
import { render } from '../utils';
import { SetupChecklistCard } from '../../components/SetupChecklistCard';

const ids = ['auth', 'printer', 'alerts', 'external_backup', 'guard', 'signature', 'storage', 'remote', 'https'];
const levels: Record<string, string> = {
  auth: 'required',
  printer: 'required',
  alerts: 'recommended',
  external_backup: 'recommended',
  guard: 'recommended',
  signature: 'recommended',
  storage: 'recommended',
  remote: 'optional',
  https: 'optional',
};

function use(done: Record<string, boolean | null>) {
  const items = ids.map((id) => ({ id, level: levels[id], done: id in done ? done[id] : false }));
  const applicable = items.filter((i) => i.done !== null);
  server.use(
    http.get('/api/v1/system/setup-status', () =>
      HttpResponse.json({
        items,
        done: applicable.filter((i) => i.done).length,
        total: applicable.length,
        required_open: applicable.filter((i) => i.level === 'required' && !i.done).length,
      }),
    ),
  );
}

describe('SetupChecklistCard', () => {
  it('shows progress, the open items with how to fix them, and a warning for required ones', async () => {
    use({ auth: true, printer: false, alerts: false });
    render(<SetupChecklistCard />);
    expect(await screen.findByTestId('setup-progress')).toHaveTextContent('1 of 9 done');
    expect(screen.getByRole('alert')).toHaveTextContent('1 required item(s) open');
    const printer = screen.getByTestId('setup-item-printer');
    expect(within(printer).getByText('Printer added')).toBeInTheDocument();
    expect(within(printer).getByText(/Add it under "Printers"/)).toBeInTheDocument();
    expect(within(screen.getByTestId('setup-item-auth')).queryByText(/Finish the setup/)).not.toBeInTheDocument();
  });

  it('does not count items that do not apply here', async () => {
    use({ auth: true, printer: true, guard: null, https: null, remote: null });
    render(<SetupChecklistCard />);
    expect(await screen.findByTestId('setup-progress')).toHaveTextContent('2 of 6 done');
    expect(within(screen.getByTestId('setup-item-guard')).queryByText(/Run the installer/)).not.toBeInTheDocument();
  });

  it('says so when everything is set up', async () => {
    use(Object.fromEntries(ids.map((id) => [id, true])));
    render(<SetupChecklistCard />);
    expect(await screen.findByText('Everything is set up.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('labels the level of every item', async () => {
    use({});
    render(<SetupChecklistCard />);
    await screen.findByTestId('setup-progress');
    expect(within(screen.getByTestId('setup-item-auth')).getByText('(required)')).toBeInTheDocument();
    expect(within(screen.getByTestId('setup-item-alerts')).getByText('(recommended)')).toBeInTheDocument();
    expect(within(screen.getByTestId('setup-item-remote')).getByText('(optional)')).toBeInTheDocument();
  });
});

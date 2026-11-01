import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { server } from '../mocks/server';
import { render } from '../utils';
import { FactoryResetCard } from '../../components/FactoryResetCard';

function preview(supported = true) {
  server.use(
    http.get('/api/v1/system/factory-reset', () =>
      HttpResponse.json({
        supported,
        data_dir: '/srv/printlab/data',
        items: ['archive', 'library', 'company.json'],
        kept: ['backups', 'logs'],
        pending: false,
      }),
    ),
  );
}

describe('FactoryResetCard', () => {
  it('asks for the confirmation phrase before the reset button becomes usable', async () => {
    preview();
    render(<FactoryResetCard canControl />);

    await userEvent.click(await screen.findByTestId('factory-reset-arm'));

    const run = screen.getByTestId('factory-reset-run');
    expect(run).toBeDisabled();

    await userEvent.type(screen.getByTestId('factory-reset-confirm'), 'zurücksetzen');
    expect(run).toBeEnabled();
  });

  it('runs the reset and shows the result', async () => {
    preview();
    let body: { confirm?: string } = {};
    server.use(
      http.post('/api/v1/system/factory-reset', async ({ request }) => {
        body = (await request.json()) as { confirm?: string };
        return HttpResponse.json({
          ok: true,
          backup: 'backups/factory-reset-20260101-120000.zip',
          moved_to: 'reset-20260101-120000',
          message: 'PrintLab wurde zurückgesetzt.',
        });
      }),
    );
    render(<FactoryResetCard canControl />);

    await userEvent.click(await screen.findByTestId('factory-reset-arm'));
    await userEvent.type(screen.getByTestId('factory-reset-confirm'), 'ZURÜCKSETZEN');
    await userEvent.click(screen.getByTestId('factory-reset-run'));

    await waitFor(() => expect(body.confirm).toBe('ZURÜCKSETZEN'));
    expect(await screen.findByText('PrintLab wurde zurückgesetzt.')).toBeInTheDocument();
  });

  it('stays disabled when the server reports no local database', async () => {
    preview(false);
    render(<FactoryResetCard canControl />);

    expect(await screen.findByText(/local database and authentication/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('factory-reset-arm')).toBeDisabled());
  });

  it('stays disabled without the settings permission', async () => {
    preview();
    render(<FactoryResetCard canControl={false} />);

    await screen.findByTestId('factory-reset-arm');
    expect(screen.getByTestId('factory-reset-arm')).toBeDisabled();
  });
});

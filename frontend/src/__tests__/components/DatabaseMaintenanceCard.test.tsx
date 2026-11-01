import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { server } from '../mocks/server';
import { render } from '../utils';
import { DatabaseMaintenanceCard } from '../../components/DatabaseMaintenanceCard';

function status(supported = true) {
  server.use(
    http.get('/api/v1/system/database', () =>
      HttpResponse.json({
        supported,
        dialect: 'sqlite',
        path: '/srv/printlab/data/printlab.db',
        size_bytes: 5 * 1024 * 1024,
      }),
    ),
  );
}

describe('DatabaseMaintenanceCard', () => {
  it('shows the database size and frees space', async () => {
    status();
    let body: { action?: string } = {};
    server.use(
      http.post('/api/v1/system/database/maintenance', async ({ request }) => {
        body = (await request.json()) as { action?: string };
        return HttpResponse.json({
          ok: true,
          action: 'vacuum',
          detail: [],
          size_bytes: 3 * 1024 * 1024,
          saved_bytes: 2 * 1024 * 1024,
        });
      }),
    );
    render(<DatabaseMaintenanceCard canControl />);

    await waitFor(() => expect(screen.getByTestId('database-size')).toHaveTextContent('5.0 MB'));
    await userEvent.click(screen.getByTestId('database-vacuum'));

    await waitFor(() => expect(body.action).toBe('vacuum'));
    expect(await screen.findByText('2.0 MB freed.')).toBeInTheDocument();
  });

  it('reports a healthy database after a check', async () => {
    status();
    server.use(
      http.post('/api/v1/system/database/maintenance', () =>
        HttpResponse.json({
          ok: true,
          action: 'check',
          detail: ['ok'],
          size_bytes: 5 * 1024 * 1024,
          saved_bytes: 0,
        }),
      ),
    );
    render(<DatabaseMaintenanceCard canControl />);

    await userEvent.click(await screen.findByTestId('database-check'));

    expect(await screen.findByText('Database is healthy.')).toBeInTheDocument();
  });

  it('explains when only an external database is in use', async () => {
    status(false);
    render(<DatabaseMaintenanceCard canControl />);

    expect(await screen.findByText(/local SQLite database/)).toBeInTheDocument();
    expect(screen.queryByTestId('database-check')).not.toBeInTheDocument();
  });
});

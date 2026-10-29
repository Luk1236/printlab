import { describe, it, expect, afterEach, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { NotificationProviderCard } from '../../components/NotificationProviderCard';
import type { NotificationProvider } from '../../api/client';

afterEach(() => {
  server.resetHandlers();
  vi.restoreAllMocks();
});

const provider = (over: Partial<NotificationProvider> = {}) =>
  ({ id: 1, name: 'Handy', provider_type: 'ntfy', enabled: true, config: { server: 'https://ntfy.sh', topic: 't' }, printer_id: null, ...over }) as NotificationProvider;

async function openEvents(p: NotificationProvider) {
  const user = userEvent.setup();
  render(<NotificationProviderCard provider={p} onEdit={vi.fn()} />);
  await user.click(await screen.findByText(/event settings/i));
  const row = (await screen.findByText('Due date at risk')).closest('div.flex.items-center.justify-between') as HTMLElement;
  return { user, row };
}

describe('NotificationProviderCard — due date at risk', () => {
  it('shows the toggle on by default (also for providers saved before the event existed)', async () => {
    const { row } = await openEvents(provider());
    expect(within(row).getByText('A queued job will miss its due date')).toBeInTheDocument();
    expect(within(row).getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });

  it('reflects an explicit off setting', async () => {
    const { row } = await openEvents(provider({ on_queue_due_risk: false }));
    expect(within(row).getByRole('switch')).toHaveAttribute('aria-checked', 'false');
  });

  it('sends the field when toggled', async () => {
    let captured: unknown = null;
    server.use(
      http.patch('/api/v1/notifications/1', async ({ request }) => {
        captured = await request.json();
        return HttpResponse.json(provider({ on_queue_due_risk: false }));
      }),
    );
    const { user, row } = await openEvents(provider({ on_queue_due_risk: true }));
    await user.click(within(row).getByRole('switch'));
    await waitFor(() => expect(captured).toEqual({ on_queue_due_risk: false }));
  });
});

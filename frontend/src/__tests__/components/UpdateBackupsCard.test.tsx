import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { UpdateBackupsCard } from '../../components/UpdateBackupsCard';

const backups = [
  { name: '20260301-120000', created: '2026-03-01T12:00:00', files: ['hardware.json', 'printlab.db'], size_bytes: 5_200_000 },
  { name: '20260101-120000', created: '2026-01-01T12:00:00', files: ['printlab.db'], size_bytes: 4_000_000 },
];

function use(body: Record<string, unknown>, calls: string[] = []) {
  server.use(
    http.get('/api/v1/updates/backups', () =>
      HttpResponse.json({ backups, restore_pending: null, restored: null, can_restore: true, ...body }),
    ),
    http.post('/api/v1/updates/backups/:name/restore', ({ params }) => {
      calls.push(`restore:${String(params.name)}`);
      return HttpResponse.json({ success: true, name: params.name });
    }),
    http.post('/api/v1/updates/restore-notice/dismiss', () => {
      calls.push('dismiss');
      return HttpResponse.json({ ok: true });
    }),
  );
}

describe('UpdateBackupsCard', () => {
  it('lists the backups with size and files', async () => {
    use({});
    render(<UpdateBackupsCard canRestore />);
    expect(await screen.findByText('20260301-120000')).toBeInTheDocument();
    expect(screen.getByText('5.2 MB')).toBeInTheDocument();
    expect(screen.getByText('hardware.json, printlab.db')).toBeInTheDocument();
    expect(screen.getByText('20260101-120000')).toBeInTheDocument();
  });

  it('asks for confirmation before restoring and then queues it', async () => {
    const calls: string[] = [];
    use({}, calls);
    render(<UpdateBackupsCard canRestore />);
    await userEvent.click(await screen.findByRole('button', { name: 'Restore 20260101-120000' }));
    expect(await screen.findByText('Restore backup?')).toBeInTheDocument();
    expect(calls).toEqual([]); // noch nichts ausgelöst
    await userEvent.click(screen.getAllByRole('button', { name: 'Restore' }).at(-1)!);
    await waitFor(() => expect(calls).toEqual(['restore:20260101-120000']));
  });

  it('can be cancelled', async () => {
    const calls: string[] = [];
    use({}, calls);
    render(<UpdateBackupsCard canRestore />);
    await userEvent.click(await screen.findByRole('button', { name: 'Restore 20260301-120000' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(calls).toEqual([]);
    expect(screen.queryByText('Restore backup?')).not.toBeInTheDocument();
  });

  it('disables restoring without permission and explains a missing update guard', async () => {
    use({ can_restore: false });
    render(<UpdateBackupsCard canRestore />);
    expect(await screen.findByText(/needs the update guard/i)).toBeInTheDocument();
    for (const button of screen.getAllByRole('button', { name: /^Restore / })) expect(button).toBeDisabled();
  });

  it('is disabled for users without the settings permission', async () => {
    use({});
    render(<UpdateBackupsCard canRestore={false} />);
    for (const button of await screen.findAllByRole('button', { name: /^Restore / })) expect(button).toBeDisabled();
  });

  it('shows a pending restore and blocks a second one', async () => {
    use({ restore_pending: '20260101-120000' });
    render(<UpdateBackupsCard canRestore />);
    expect(await screen.findByText(/will be restored at the next start/i)).toBeInTheDocument();
    for (const button of screen.getAllByRole('button', { name: /^Restore / })) expect(button).toBeDisabled();
  });

  it('shows the result of a restore and lets you dismiss it', async () => {
    const calls: string[] = [];
    use({ restored: { name: '20260101-120000', restored: ['printlab.db'], at: '2026-03-02T01:00:00' } }, calls);
    render(<UpdateBackupsCard canRestore />);
    expect(await screen.findByText('The backup 20260101-120000 was restored.')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Got it' }));
    await waitFor(() => expect(calls).toContain('dismiss'));
  });

  it('stays hidden when there is nothing to show', async () => {
    use({ backups: [] });
    const { container } = render(<UpdateBackupsCard canRestore />);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(container.querySelector('[data-testid="update-backups"]')).toBeNull();
  });
});

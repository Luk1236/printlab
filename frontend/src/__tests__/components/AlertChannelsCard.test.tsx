import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { AlertChannelsCard } from '../../components/AlertChannelsCard';

const empty = { telegram: false, telegram_chat: '', ntfy: false, ntfy_host: '' };

function use(status: Record<string, unknown>, calls: unknown[] = [], testResult = { sent: ['ntfy'], errors: [] as string[] }) {
  server.use(
    http.get('/api/v1/system/alerts', () => HttpResponse.json({ ...empty, ...status })),
    http.put('/api/v1/system/alerts', async ({ request }) => {
      const body = await request.json();
      calls.push(body);
      return HttpResponse.json({ ...empty, ntfy: true, ntfy_host: 'ntfy.sh' });
    }),
    http.post('/api/v1/system/alerts/test', () => {
      calls.push('test');
      return HttpResponse.json(testResult);
    }),
  );
}

describe('AlertChannelsCard', () => {
  it('shows what is set up without ever showing a secret', async () => {
    use({ telegram: true, telegram_chat: '42', ntfy: true, ntfy_host: 'ntfy.sh' });
    render(<AlertChannelsCard canControl />);
    expect((await screen.findAllByText(/set up/)).length).toBe(2);
    expect(screen.getByText(/ntfy\.sh/)).toBeInTheDocument();
    const secretFields = screen.getAllByDisplayValue('');
    expect(secretFields.length).toBeGreaterThan(0);
    expect(document.body.innerHTML).not.toMatch(/\d{9}:[A-Za-z0-9_-]{30,}/);
  });

  it('keeps the token and address in password fields', async () => {
    use({});
    render(<AlertChannelsCard canControl />);
    await screen.findByText('Outage alerts');
    expect(screen.getByLabelText('Bot token (from @BotFather)')).toHaveAttribute('type', 'password');
    expect(screen.getByLabelText('ntfy address (topic)')).toHaveAttribute('type', 'password');
  });

  it('sends only what was typed and clears the fields afterwards', async () => {
    const calls: unknown[] = [];
    use({}, calls);
    render(<AlertChannelsCard canControl />);
    const ntfy = await screen.findByLabelText('ntfy address (topic)');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    await userEvent.type(ntfy, 'https://ntfy.sh/mein-geheimes-thema');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls).toEqual([{ ntfy_url: 'https://ntfy.sh/mein-geheimes-thema' }]));
    await waitFor(() => expect(ntfy).toHaveValue(''));
  });

  it('sends a test message and reports the result', async () => {
    const calls: unknown[] = [];
    use({ ntfy: true, ntfy_host: 'ntfy.sh' }, calls);
    render(<AlertChannelsCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send test message' }));
    await waitFor(() => expect(calls).toContain('test'));
    expect(await screen.findByText('Test message sent to: ntfy')).toBeInTheDocument();
  });

  it('shows a failed test with the reason', async () => {
    use({ ntfy: true, ntfy_host: 'ntfy.sh' }, [], { sent: [], errors: ['ntfy: HTTP 404'] });
    render(<AlertChannelsCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Send test message' }));
    expect(await screen.findByText('Test message failed: ntfy: HTTP 404')).toBeInTheDocument();
  });

  it('can remove everything', async () => {
    const calls: unknown[] = [];
    use({ ntfy: true, ntfy_host: 'ntfy.sh' }, calls);
    render(<AlertChannelsCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Remove' }));
    await waitFor(() => expect(calls).toEqual([{ telegram_token: '', telegram_chat: '', ntfy_url: '' }]));
  });

  it('is read-only without the settings permission and the test needs a channel', async () => {
    use({});
    render(<AlertChannelsCard canControl={false} />);
    await screen.findByText('Outage alerts');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Send test message' })).toBeDisabled();
  });
});

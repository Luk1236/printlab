import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { AutoSetupCard } from '../../components/AutoSetupCard';

type State = 'done' | 'todo' | 'changed' | 'needs_user' | 'manual' | 'failed';
const plan = (states: Record<string, State>) => {
  const items = Object.entries(states).map(([id, state]) => ({ id, state, detail: '' }));
  return { items, todo: items.filter((item) => item.state === 'todo').length };
};

describe('AutoSetupCard', () => {
  it('lists what the system can set up and runs it with one button', async () => {
    server.use(
      http.get('/api/v1/system/auto-setup', () => HttpResponse.json(plan({ guard: 'todo', assistant: 'manual', remote: 'todo' }))),
      http.post('/api/v1/system/auto-setup', () =>
        HttpResponse.json({
          items: [
            { id: 'guard', state: 'changed', detail: '' },
            { id: 'assistant', state: 'manual', detail: 'no_server' },
            { id: 'remote', state: 'needs_user', detail: 'https://login.tailscale.com/a/abc' },
          ],
          changed: 2,
        }),
      ),
    );
    render(<AutoSetupCard />);

    expect(await screen.findByText(/Add update protection/)).toBeInTheDocument();
    expect(screen.getByText(/Set up remote access/)).toBeInTheDocument();
    expect(screen.queryByText(/local assistant/)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Set up now (2)' }));

    expect(await screen.findByTestId('auto-setup-guard')).toHaveTextContent('Done');
    expect(screen.queryByTestId('auto-setup-assistant')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open the sign-in link' })).toHaveAttribute('href', 'https://login.tailscale.com/a/abc');
  });

  it('shows nothing when there is nothing left to set up', async () => {
    server.use(http.get('/api/v1/system/auto-setup', () => HttpResponse.json(plan({ guard: 'done', assistant: 'manual', remote: 'done' }))));
    render(<AutoSetupCard />);

    await screen.findByText('', { selector: 'body' });
    expect(screen.queryByTestId('auto-setup')).not.toBeInTheDocument();
  });

  it('does not turn a non-https login address into a link', async () => {
    server.use(
      http.get('/api/v1/system/auto-setup', () => HttpResponse.json(plan({ remote: 'todo' }))),
      http.post('/api/v1/system/auto-setup', () =>
        HttpResponse.json({ items: [{ id: 'remote', state: 'needs_user', detail: 'javascript:alert(1)' }], changed: 1 }),
      ),
    );
    render(<AutoSetupCard />);

    await userEvent.click(await screen.findByRole('button', { name: 'Set up now (1)' }));

    expect(await screen.findByTestId('auto-setup-remote')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('tells the user when the run fails', async () => {
    server.use(
      http.get('/api/v1/system/auto-setup', () => HttpResponse.json(plan({ guard: 'todo' }))),
      http.post('/api/v1/system/auto-setup', () => HttpResponse.json({ detail: 'boom' }, { status: 500 })),
    );
    render(<AutoSetupCard />);

    await userEvent.click(await screen.findByRole('button', { name: 'Set up now (1)' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Automatic setup failed.');
  });
});

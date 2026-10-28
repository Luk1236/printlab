import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { RemoteAccessCard } from '../../components/RemoteAccessCard';

const base = {
  supported: true,
  installed: false,
  managed: false,
  daemon_running: false,
  state: 'off',
  login_url: null,
  ips: [] as string[],
  dns_name: '',
  serving: false,
  enabled: false,
  error: null,
  auth_enabled: true,
};

function use(status: Record<string, unknown>, calls: string[] = []) {
  server.use(
    http.get('/api/v1/remote-access', () => HttpResponse.json({ ...base, ...status })),
    http.post('/api/v1/remote-access/setup', () => {
      calls.push('setup');
      return HttpResponse.json({ ...base, ...status, state: 'login', login_url: 'https://login.tailscale.com/a/abc' });
    }),
    http.post('/api/v1/remote-access/share', () => {
      calls.push('share');
      return HttpResponse.json({ ...base, ...status, serving: true });
    }),
    http.post('/api/v1/remote-access/disable', () => {
      calls.push('disable');
      return HttpResponse.json({ ...base, state: 'off' });
    }),
  );
}

describe('RemoteAccessCard', () => {
  it('asks for sign-in first and blocks setup while authentication is off', async () => {
    use({ auth_enabled: false });
    render(<RemoteAccessCard canControl />);
    expect(await screen.findByText(/only be switched on when sign-in is enabled/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set up remote access' })).toBeDisabled();
  });

  it('starts the setup and then shows the Tailscale sign-in link', async () => {
    const calls: string[] = [];
    use({}, calls);
    render(<RemoteAccessCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Set up remote access' }));
    await waitFor(() => expect(calls).toContain('setup'));
    const link = await screen.findByRole('link', { name: 'Sign in to Tailscale' });
    expect(link).toHaveAttribute('href', 'https://login.tailscale.com/a/abc');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
  });

  it('shows the address once connected and offers to share', async () => {
    const calls: string[] = [];
    use({ state: 'connected', ips: ['100.64.0.7'], dns_name: 'printlab.tail1234.ts.net', enabled: true }, calls);
    render(<RemoteAccessCard canControl />);
    expect(await screen.findByText(/:\d+$/, { selector: 'span' })).toHaveTextContent('http://100.64.0.7:');
    expect(screen.getByText('printlab.tail1234.ts.net')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Share' }));
    await waitFor(() => expect(calls).toContain('share'));
  });

  it('does not offer to share when it is already shared, and can turn everything off', async () => {
    const calls: string[] = [];
    use({ state: 'connected', ips: ['100.64.0.7'], serving: true, enabled: true }, calls);
    render(<RemoteAccessCard canControl />);
    await screen.findByText(/shared in the Tailscale network/i);
    expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Turn off' }));
    await waitFor(() => expect(calls).toContain('disable'));
  });

  it('explains that it is Linux only', async () => {
    use({ supported: false });
    render(<RemoteAccessCard canControl />);
    expect(await screen.findByText(/only available on Linux/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Set up remote access' })).toBeDisabled();
  });

  it('shows a server error text', async () => {
    use({ error: 'tailscaled exited' });
    render(<RemoteAccessCard canControl />);
    expect(await screen.findByText('tailscaled exited')).toBeInTheDocument();
  });

  it('disables the buttons without permission', async () => {
    use({ state: 'connected', ips: ['100.64.0.7'], enabled: true });
    render(<RemoteAccessCard canControl={false} />);
    expect(await screen.findByRole('button', { name: 'Turn off' })).toBeDisabled();
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { act, screen } from '@testing-library/react';
import { server } from '../mocks/server';
import { render } from '../utils';
import { UpdateRestartWatcher } from '../../components/UpdateRestartWatcher';

describe('UpdateRestartWatcher', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function tick(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it('shows that PrintLab is restarting', async () => {
    server.use(http.get('/api/v1/updates/version', () => HttpResponse.json({ version: '1.0.0' })));
    render(<UpdateRestartWatcher currentVersion="1.0.0" onReload={() => undefined} />);
    expect(await screen.findByRole('status')).toHaveTextContent(/restarting/i);
  });

  it('does not reload while the old version still answers', async () => {
    const reload = vi.fn();
    server.use(http.get('/api/v1/updates/version', () => HttpResponse.json({ version: '1.0.0' })));
    render(<UpdateRestartWatcher currentVersion="1.0.0" onReload={reload} />);
    await tick(9000);
    expect(reload).not.toHaveBeenCalled();
  });

  it('reloads when the service answers with a new version', async () => {
    const reload = vi.fn();
    server.use(http.get('/api/v1/updates/version', () => HttpResponse.json({ version: '1.1.0' })));
    render(<UpdateRestartWatcher currentVersion="1.0.0" onReload={reload} />);
    await tick(4000);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('reloads once the service came back after being down', async () => {
    const reload = vi.fn();
    let up = false;
    server.use(
      http.get('/api/v1/updates/version', () => (up ? HttpResponse.json({ version: '1.0.0' }) : HttpResponse.error())),
    );
    render(<UpdateRestartWatcher currentVersion="1.0.0" onReload={reload} />);
    await tick(4000);
    expect(reload).not.toHaveBeenCalled();
    up = true;
    await tick(4000);
    expect(reload).toHaveBeenCalledTimes(1);
  });
});

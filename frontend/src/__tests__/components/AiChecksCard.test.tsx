import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { AiChecksCard } from '../../components/AiChecksCard';

const toggleIn = (id: string) => within(screen.getByTestId(`check-${id}`)).getByRole('switch');

describe('AiChecksCard', () => {
  let patched: unknown;
  let partWatcherBody: unknown;

  beforeEach(() => {
    patched = undefined;
    partWatcherBody = undefined;
    server.use(
      http.get('/api/v1/printers/', () =>
        HttpResponse.json([{ id: 1, name: 'P2S', plate_detection_enabled: false }]),
      ),
      http.patch('/api/v1/printers/1', async ({ request }) => {
        patched = await request.json();
        return HttpResponse.json({ id: 1, name: 'P2S', plate_detection_enabled: true });
      }),
      http.get('/api/v1/printers/1/status', () =>
        HttpResponse.json({ print_options: { spaghetti_detector: true, first_layer_inspector: false } }),
      ),
      http.get('/api/v1/assistant/status', () =>
        HttpResponse.json({
          config: { enabled: true },
          server: { reachable: true, models: [], model_present: true, error: '' },
        }),
      ),
      http.get('/api/v1/error-help/ai-scan', () => HttpResponse.json({ config: { error_scan_enabled: true } })),
      http.get('/api/v1/error-help/ai-watch', () => HttpResponse.json({ config: { enabled: false } })),
      http.get('/api/v1/obico/status', () => HttpResponse.json({ enabled: true, ml_url: '' })),
      http.get('/api/v1/printers/1/first-layer-inspector', () => HttpResponse.json({ enabled: true })),
      http.get('/api/v1/printers/1/part-watcher', () =>
        HttpResponse.json({ enabled: false, threshold: 2.5, overrides: [] }),
      ),
      http.put('/api/v1/printers/1/part-watcher', async ({ request }) => {
        partWatcherBody = await request.json();
        return HttpResponse.json({ enabled: true, threshold: 2.5, overrides: [] });
      }),
    );
  });

  it('shows the state of every check', async () => {
    render(<AiChecksCard />);

    await waitFor(() => expect(toggleIn('assistant')).toBeChecked());
    await waitFor(() => expect(toggleIn('first-layer')).toBeChecked());
    await waitFor(() => expect(toggleIn('firmware-spaghetti')).toBeChecked());
    expect(toggleIn('ai-watch')).not.toBeChecked();
    expect(toggleIn('firmware-first-layer')).not.toBeChecked();
  });

  it('switches the plate detection of the printer', async () => {
    const user = userEvent.setup();
    render(<AiChecksCard />);

    await waitFor(() => expect(toggleIn('plate-detection')).toBeEnabled());
    await user.click(toggleIn('plate-detection'));

    await waitFor(() => expect(patched).toEqual({ plate_detection_enabled: true }));
  });

  it('keeps the threshold of the part watcher when switching it', async () => {
    const user = userEvent.setup();
    render(<AiChecksCard />);

    await waitFor(() => expect(toggleIn('part-watcher')).toBeEnabled());
    await user.click(toggleIn('part-watcher'));

    await waitFor(() => expect(partWatcherBody).toMatchObject({ enabled: true, threshold: 2.5 }));
  });

  it('shows a dead Obico as off and leaves the printer detection read-only', async () => {
    render(<AiChecksCard />);

    await waitFor(() => expect(toggleIn('firmware-spaghetti')).toBeChecked());
    expect(toggleIn('obico')).not.toBeChecked();
    expect(toggleIn('obico')).toBeDisabled();
    expect(toggleIn('firmware-spaghetti')).toBeDisabled();
  });
});

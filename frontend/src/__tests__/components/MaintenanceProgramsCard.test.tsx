import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { MaintenanceProgramsCard } from '../../components/MaintenanceProgramsCard';

const p2s = { id: 1, name: 'P2S Werkstatt', serial_number: '22E8AJ000000000', ip_address: '192.168.178.140', is_active: true, model: 'P2S', location: null, nozzle_count: 1 };

const hardware = (overrides: Record<string, unknown> = {}) => ({
  mode: 'simulated',
  door: 'closed',
  plate_on_bed: true,
  busy: false,
  error: null,
  slots: [
    { id: 1, type: 'supply', status: 'ready', label: 'PEI A' },
    { id: 2, type: 'supply', status: 'ready', label: 'PEI B' },
    { id: 3, type: 'supply', status: 'ready', label: 'PEI C' },
    { id: 4, type: 'storage', status: 'empty', label: 'Fach 1' },
    { id: 5, type: 'storage', status: 'empty', label: 'Fach 2' },
    { id: 6, type: 'storage', status: 'empty', label: 'Fach 3' },
  ],
  supply_ready: 3,
  storage_empty: 3,
  changes: 0,
  last_change: null,
  auto_plate_change: { enabled: false, cooldown_bed_temp: 45, max_wait_seconds: 1800, poll_seconds: 10, skip_if_offline: true, last_run: null },
  ...overrides,
});

function useHardware(body: unknown, calls: string[] = []) {
  server.use(
    http.get('/api/v1/printers/', () => HttpResponse.json([p2s])),
    http.get('/api/v1/printers/:id/hardware', () => HttpResponse.json(body)),
    http.put('/api/v1/printers/:id/hardware/auto-plate-change', async ({ request }) => {
      calls.push(`auto:${JSON.stringify(await request.json())}`);
      return HttpResponse.json({ auto_plate_change: (body as { auto_plate_change: unknown }).auto_plate_change });
    }),
    http.post('/api/v1/printers/:id/hardware/emergency-stop', () => {
      calls.push('stop');
      return HttpResponse.json({ success: true, message: 'Stopped', ...hardware() });
    }),
    http.post('/api/v1/printers/:id/hardware/door/open', () => {
      calls.push('open');
      return HttpResponse.json({ success: true, message: 'Opened', ...hardware({ door: 'open' }) });
    }),
  );
}

describe('MaintenanceProgramsCard hardware section', () => {
  it('shows the six magazine slots from the hardware status', async () => {
    useHardware(hardware());
    render(<MaintenanceProgramsCard canControl />);
    await waitFor(() => expect(screen.getByTitle(/supply 1 · ready/)).toBeInTheDocument());
    expect(screen.getByTitle(/storage 4 · empty/)).toBeInTheDocument();
  });

  it('turns the automation on with enabled=true', async () => {
    const calls: string[] = [];
    useHardware(hardware(), calls);
    render(<MaintenanceProgramsCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Enable automation' }));
    await waitFor(() => expect(calls).toContain('auto:{"enabled":true}'));
  });

  it('shows the last run message and the low-supply warning', async () => {
    useHardware(
      hardware({
        auto_plate_change: {
          enabled: true, cooldown_bed_temp: 45, max_wait_seconds: 1800, poll_seconds: 10, skip_if_offline: true,
          last_run: { printer_id: 1, job: 'x', ok: true, message: 'Platte aus Fach 2 eingesetzt.', warning: 'Magazin: nur noch 1 frische Platte(n) — bitte auffüllen bzw. leeren.' },
        },
      }),
    );
    render(<MaintenanceProgramsCard canControl />);
    expect(await screen.findByText('Platte aus Fach 2 eingesetzt.')).toBeInTheDocument();
    expect(screen.getByText(/nur noch 1 frische Platte/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Disable automation' })).toBeInTheDocument();
  });

  it('shows a hardware error from the server', async () => {
    useHardware(hardware({ error: 'Tür-Endschalter meldet UNKNOWN.' }));
    render(<MaintenanceProgramsCard canControl />);
    expect(await screen.findByText('Tür-Endschalter meldet UNKNOWN.')).toBeInTheDocument();
  });

  it('keeps the emergency stop usable while other hardware buttons are disabled when busy', async () => {
    const calls: string[] = [];
    useHardware(hardware({ busy: true }), calls);
    render(<MaintenanceProgramsCard canControl />);
    const open = await screen.findByRole('button', { name: 'Open door' });
    await waitFor(() => expect(open).toBeDisabled());
    const stop = screen.getByRole('button', { name: 'Emergency stop' });
    expect(stop).toBeEnabled();
    await userEvent.click(stop);
    await waitFor(() => expect(calls).toContain('stop'));
  });

  it('disables every hardware control without control permission', async () => {
    useHardware(hardware());
    render(<MaintenanceProgramsCard canControl={false} />);
    expect(await screen.findByRole('button', { name: 'Open door' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Emergency stop' })).toBeDisabled();
  });
});

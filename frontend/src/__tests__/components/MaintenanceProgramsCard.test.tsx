import { describe, it, expect, vi } from 'vitest';
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

describe('MaintenanceProgramsCard safety states and automation controls', () => {
  it('shows the emergency-stop latch and lifts it', async () => {
    const calls: string[] = [];
    useHardware(hardware({ estop: true }), calls);
    server.use(
      http.post('/api/v1/printers/:id/hardware/emergency-stop/reset', () => {
        calls.push('unlock');
        return HttpResponse.json({ success: true, message: 'ok', ...hardware() });
      }),
    );
    render(<MaintenanceProgramsCard canControl />);
    expect(await screen.findByText(/Emergency stop active/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Lift lock' }));
    await waitFor(() => expect(calls).toContain('unlock'));
  });

  it('shows an incomplete plate change and confirms it after checking', async () => {
    const calls: string[] = [];
    useHardware(hardware({ incomplete: { step: 'Tür schließen', plate_swapped: true, job: 'x' } }), calls);
    server.use(
      http.post('/api/v1/printers/:id/hardware/incomplete/resolve', () => {
        calls.push('resolve');
        return HttpResponse.json({ success: true, message: 'ok', ...hardware() });
      }),
    );
    render(<MaintenanceProgramsCard canControl />);
    expect(await screen.findByText(/Plate change incomplete \(Tür schließen\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Change checked' }));
    await waitFor(() => expect(calls).toContain('resolve'));
  });

  it('shows neither banner when everything is fine', async () => {
    useHardware(hardware());
    render(<MaintenanceProgramsCard canControl />);
    await screen.findByRole('button', { name: 'Enable automation' });
    expect(screen.queryByText(/Emergency stop active/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Plate change incomplete/)).not.toBeInTheDocument();
  });

  it('saves the queue gate and the camera confirmation as separate settings', async () => {
    const calls: string[] = [];
    useHardware(hardware(), calls);
    render(<MaintenanceProgramsCard canControl />);
    await userEvent.click(await screen.findByLabelText('Only when a job is waiting'));
    await waitFor(() => expect(calls).toContain('auto:{"only_with_queue":true}'));
    await userEvent.click(screen.getByLabelText('Confirm plate clear automatically (camera)'));
    await waitFor(() => expect(calls).toContain('auto:{"auto_confirm_plate_clear":true}'));
  });

  it('cancels a waiting automatic change', async () => {
    const calls: string[] = [];
    useHardware(hardware(), calls);
    server.use(
      http.post('/api/v1/printers/:id/hardware/auto-plate-change/cancel', () => {
        calls.push('cancel');
        return HttpResponse.json({ success: true, cancelled: 1 });
      }),
    );
    render(<MaintenanceProgramsCard canControl />);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel change' }));
    await waitFor(() => expect(calls).toContain('cancel'));
  });

  it('checks the door sensor via the configured status command', async () => {
    const calls: string[] = [];
    useHardware(hardware(), calls);
    server.use(
      http.post('/api/v1/printers/:id/hardware/door/status', () => {
        calls.push('door-status');
        return HttpResponse.json({ success: true, message: 'Tür: closed' });
      }),
    );
    render(<MaintenanceProgramsCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Check door sensor' }));
    await waitFor(() => expect(calls).toContain('door-status'));
  });

  it('does not cancel when the confirmation is dismissed', async () => {
    const calls: string[] = [];
    useHardware(hardware(), calls);
    render(<MaintenanceProgramsCard canControl />);
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel change' }));
    // A dismissed confirmation must not fire the request.
    await expect(waitFor(() => expect(calls).toContain('cancel'), { timeout: 500 })).rejects.toEqual(
      expect.anything(),
    );
  });

  it('deletes the camera calibration', async () => {
    const calls: string[] = [];
    useHardware(hardware(), calls);
    server.use(
      http.get('/api/v1/printers/:id/plate-calibration', () => HttpResponse.json({ calibrated: true, points: [] })),
      http.delete('/api/v1/printers/:id/plate-calibration', () => {
        calls.push('clear');
        return HttpResponse.json({ calibrated: false, points: [] });
      }),
    );
    render(<MaintenanceProgramsCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete calibration' }));
    await waitFor(() => expect(calls).toContain('clear'));
  });
});

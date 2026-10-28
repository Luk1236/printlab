import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { HardwareAdminCard } from '../../components/HardwareAdminCard';

const p2s = { id: 1, name: 'P2S Werkstatt', serial_number: 'SN1', ip_address: '192.168.178.140', is_active: true, model: 'P2S', location: null, nozzle_count: 1 };

const slots = [
  { id: 1, type: 'supply', status: 'ready', label: 'PEI A' },
  { id: 2, type: 'supply', status: 'used', label: 'PEI B' },
  { id: 3, type: 'supply', status: 'ready', label: 'PEI C' },
  { id: 4, type: 'storage', status: 'empty', label: 'Fach 1' },
  { id: 5, type: 'storage', status: 'occupied', label: 'Fach 2', print: 'Teil.3mf' },
  { id: 6, type: 'storage', status: 'empty', label: 'Fach 3' },
];

const config = {
  mode: 'command',
  timeout_seconds: 15,
  door_open_command: 'servo open',
  door_close_command: ['servo', 'close'],
  door_status_command: '',
  plate_change_command: '',
  emergency_stop_command: '',
};

function setup(calls: { slots: unknown[]; config: unknown[] } = { slots: [], config: [] }) {
  server.use(
    http.get('/api/v1/printers/', () => HttpResponse.json([p2s])),
    http.get('/api/v1/printers/:id/hardware', () =>
      HttpResponse.json({ mode: 'command', door: 'closed', plate_on_bed: true, busy: false, error: null, slots }),
    ),
    http.get('/api/v1/printers/:id/hardware/audit-log', () =>
      HttpResponse.json([
        { ts: '2026-10-27T10:00:00+00:00', action: 'door_open', ok: true, message: 'Tür geöffnet.', printer_id: 1, user: null },
        { ts: '2026-10-27T09:00:00+00:00', action: 'auto_plate_change', ok: false, message: 'Tür offen', printer_id: 1, user: null },
      ]),
    ),
    http.get('/api/v1/printers/:id/hardware/config', () => HttpResponse.json(config)),
    http.put('/api/v1/printers/:id/hardware/magazine', async ({ request }) => {
      calls.slots.push(await request.json());
      return HttpResponse.json({ success: true, message: 'ok', mode: 'command', slots });
    }),
    http.put('/api/v1/printers/:id/hardware/config', async ({ request }) => {
      calls.config.push(await request.json());
      return HttpResponse.json({ success: true, message: 'saved' });
    }),
  );
  return calls;
}

describe('HardwareAdminCard', () => {
  it('renders the six slots with translated status names (not raw keys)', async () => {
    setup();
    render(<HardwareAdminCard canControl />);
    expect(await screen.findByText('Teil.3mf')).toBeInTheDocument();
    expect(screen.getAllByText('ready').length).toBe(2);
    expect(screen.getByText('occupied')).toBeInTheDocument();
    expect(screen.queryByText(/hardwareAdmin\./)).not.toBeInTheDocument();
  });

  it('warns that command settings let a user run programs on the device', async () => {
    setup();
    render(<HardwareAdminCard canControl />);
    const warning = await screen.findByTestId('command-trust-warning');
    expect(warning).toHaveTextContent(/run programs on the device/i);
    expect(warning).toHaveTextContent(/only to people you trust/i);
  });

  it('cycles a slot status on click and saves it', async () => {
    const calls = setup();
    render(<HardwareAdminCard canControl />);
    const chips = await screen.findAllByRole('button', { name: 'ready' });
    await userEvent.click(chips[0]);
    await waitFor(() => expect(calls.slots).toContainEqual({ slots: [{ id: 1, status: 'used' }] }));
  });

  it('shows the audit log with translated action names', async () => {
    setup();
    render(<HardwareAdminCard canControl />);
    expect(await screen.findByText('Automatic plate change')).toBeInTheDocument();
    expect(screen.getByText('Tür geöffnet.')).toBeInTheDocument();
  });

  it('edits commands: a JSON list is sent as a list, text stays text', async () => {
    const calls = setup();
    render(<HardwareAdminCard canControl />);
    await userEvent.click(await screen.findByRole('button', { name: 'Edit commands' }));
    const closeInput = await screen.findByDisplayValue('["servo","close"]');
    expect(screen.getByDisplayValue('servo open')).toBeInTheDocument();
    await userEvent.clear(closeInput);
    await userEvent.click(closeInput);
    await userEvent.paste('["tool","--close","a b"]');
    await userEvent.click(screen.getByRole('button', { name: /Save/i }));
    await waitFor(() => expect(calls.config.length).toBe(1));
    const sent = calls.config[0] as Record<string, unknown>;
    expect(sent.door_close_command).toEqual(['tool', '--close', 'a b']);
    expect(sent.door_open_command).toBe('servo open');
  });

  it('hides the command editor without control permission', async () => {
    setup();
    render(<HardwareAdminCard canControl={false} />);
    await screen.findByText('Teil.3mf');
    expect(screen.queryByRole('button', { name: 'Edit commands' })).not.toBeInTheDocument();
  });
});

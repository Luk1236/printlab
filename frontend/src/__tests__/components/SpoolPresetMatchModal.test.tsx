import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { SpoolPresetMatchModal } from '../../components/SpoolPresetMatchModal';
import type { InventorySpool } from '../../api/client';

const spool = (over: Partial<InventorySpool>): InventorySpool =>
  ({
    id: 1, material: 'PLA', subtype: 'Basic', brand: 'Bambu Lab', color_name: 'Jade White',
    slicer_filament: null, slicer_filament_name: null, archived_at: null, ...over,
  }) as InventorySpool;

let updates: Array<{ ids: number[]; update: Record<string, unknown> }> = [];

function mock(builtin: Array<{ filament_id: string; name: string }>, cloud = false) {
  updates = [];
  server.use(
    http.get('/api/v1/cloud/status', () => HttpResponse.json({ is_authenticated: cloud })),
    http.get('/api/v1/cloud/filaments', () =>
      HttpResponse.json(cloud ? [{ setting_id: 'PFUS1', name: 'Bambu PLA Basic @BBL X1C', type: 'filament', version: null, user_id: null, updated_time: null, is_custom: false }] : []),
    ),
    http.get('/api/v1/orca-cloud/status', () => HttpResponse.json({ connected: false })),
    http.get('/api/v1/local-presets/', () => HttpResponse.json({ filament: [], process: [], printer: [] })),
    http.get('/api/v1/cloud/builtin-filaments', () => HttpResponse.json(builtin)),
    http.get('/api/v1/printers/', () => HttpResponse.json([{ id: 1, name: 'X', model: 'X1C' }])),
    http.post('/api/v1/inventory/spools/bulk-update', async ({ request }) => {
      const body = (await request.json()) as { ids: number[]; update: Record<string, unknown> };
      updates.push(body);
      return HttpResponse.json({ updated: body.ids.length, not_found: [] });
    }),
  );
}

describe('SpoolPresetMatchModal', () => {
  beforeEach(() => {
    updates = [];
  });

  it('proposes matching presets, leaves generic ones unchecked and applies the checked ones grouped by preset', async () => {
    mock([
      { filament_id: 'GFA00', name: 'Bambu PLA Basic' },
      { filament_id: 'GFL05', name: 'Generic PLA' },
    ]);
    const spools = [
      spool({ id: 1 }),
      spool({ id: 2, color_name: 'Black' }),
      spool({ id: 3, brand: 'Polymaker', subtype: 'Silk', color_name: 'Gold' }),
      spool({ id: 4, material: 'TPU', brand: 'Other', color_name: 'Clear' }),
      spool({ id: 5, slicer_filament: 'GFA00', color_name: 'Has preset' }),
    ];
    render(<SpoolPresetMatchModal spools={spools} onClose={() => undefined} />);
    expect(await screen.findByLabelText('Bambu Lab PLA Basic (Jade White)')).toBeChecked();
    expect(screen.getByLabelText('Bambu Lab PLA Basic (Black)')).toBeChecked();
    expect(screen.getByLabelText('Polymaker PLA Silk (Gold)')).not.toBeChecked();
    expect(screen.queryByLabelText(/Has preset/)).not.toBeInTheDocument();
    expect(screen.getByText('1 spool(s) without a matching preset')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Apply 2' }));
    await waitFor(() => expect(updates.length).toBe(1));
    expect(updates[0]).toEqual({ ids: [1, 2], update: { slicer_filament: 'GFA00', slicer_filament_name: 'Bambu PLA Basic' } });
  });

  it('lets the user tick a generic match and untick another', async () => {
    mock([{ filament_id: 'GFL05', name: 'Generic PLA' }]);
    render(<SpoolPresetMatchModal spools={[spool({ id: 3, brand: 'Polymaker' })]} onClose={() => undefined} />);
    const box = await screen.findByLabelText('Polymaker PLA Basic (Jade White)');
    expect(screen.getByRole('button', { name: 'Apply 0' })).toBeDisabled();
    await userEvent.click(box);
    await userEvent.click(screen.getByRole('button', { name: 'Apply 1' }));
    await waitFor(() => expect(updates.length).toBe(1));
    expect(updates[0].update).toMatchObject({ slicer_filament: 'GFL05' });
  });

  it('prefers the Bambu Cloud preset over the built-in one and names the printer variant', async () => {
    mock([{ filament_id: 'GFA00', name: 'Bambu PLA Basic' }], true);
    render(<SpoolPresetMatchModal spools={[spool({ id: 1 })]} onClose={() => undefined} />);
    await screen.findByLabelText('Bambu Lab PLA Basic (Jade White)');
    expect(screen.getByText('Bambu PLA Basic @BBL X1C')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Apply 1' }));
    await waitFor(() => expect(updates.length).toBe(1));
    expect(updates[0].update).toMatchObject({ slicer_filament: 'PFUS1' });
  });

  it('says so when only built-in presets exist and when nothing is left to match', async () => {
    mock([{ filament_id: 'GFA00', name: 'Bambu PLA Basic' }]);
    render(<SpoolPresetMatchModal spools={[spool({ id: 1, slicer_filament: 'GFA00' })]} onClose={() => undefined} />);
    expect(await screen.findByText(/only the built-in standard presets/)).toBeInTheDocument();
    expect(await screen.findByText(/every spool already has a preset/)).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('Also re-match spools that already have a preset'));
    expect(await screen.findByLabelText('Bambu Lab PLA Basic (Jade White)')).toBeInTheDocument();
  });
});

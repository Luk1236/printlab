import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { VirtualPrinterAddDialog } from '../../components/VirtualPrinterAddDialog';

let created: Array<Record<string, unknown>> = [];

describe('VirtualPrinterAddDialog', () => {
  beforeEach(() => {
    created = [];
    server.use(
      http.get('/api/v1/printers/', () =>
        HttpResponse.json([
          { id: 1, name: 'X1 Carbon', ip_address: '192.168.1.10' },
          { id: 2, name: 'P1S', ip_address: '192.168.1.11' },
        ]),
      ),
      http.post('/api/v1/virtual-printers', async ({ request }) => {
        created.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json({ id: 9 });
      }),
    );
  });

  it('offers an optional target printer for every mode and sends it', async () => {
    render(<VirtualPrinterAddDialog onClose={() => undefined} />);
    await userEvent.click(screen.getByRole('button', { name: /^queue/i }));
    expect(screen.getByText('(optional)')).toBeInTheDocument();
    await screen.findByRole('option', { name: /X1 Carbon/ });
    await userEvent.selectOptions(screen.getByRole('combobox'), '1');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(created.length).toBe(1));
    expect(created[0]).toMatchObject({ mode: 'queue', target_printer_id: 1 });
  });

  it('creates without a target in a non-proxy mode', async () => {
    render(<VirtualPrinterAddDialog onClose={() => undefined} />);
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(created.length).toBe(1));
    expect(created[0].target_printer_id).toBeUndefined();
  });

  it('requires a target for proxy mode', async () => {
    render(<VirtualPrinterAddDialog onClose={() => undefined} />);
    await userEvent.click(screen.getByRole('button', { name: /^proxy/i }));
    expect(screen.queryByText('(optional)')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create' })).toBeDisabled();
    await screen.findByRole('option', { name: /P1S/ });
    await userEvent.selectOptions(screen.getByRole('combobox'), '2');
    expect(screen.getByRole('button', { name: 'Create' })).toBeEnabled();
  });

  it('explains that several virtual printers need their own IP address', () => {
    render(<VirtualPrinterAddDialog onClose={() => undefined} />);
    expect(screen.getByText(/own IP address in the slicer/)).toBeInTheDocument();
  });
});

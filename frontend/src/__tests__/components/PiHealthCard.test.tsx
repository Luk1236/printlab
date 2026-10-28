import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import { server } from '../mocks/server';
import { render } from '../utils';
import { PiHealthCard } from '../../components/PiHealthCard';

const healthy = {
  cpu_temp_c: 52.3,
  throttled: { value: 0, flags: [] },
  disk: { total: 64e9, free: 40e9 },
  storage: { device: '/dev/nvme0n1p1', kind: 'nvme' },
  memory: { total: 8e9, available: 6e9, swap_total: 1e9, swap_free: 1e9 },
  uptime_seconds: 90000,
  backup: { path: '/x', age_days: 1.2 },
  external_backup: { ok: true, detail: '/usb', at: '2026-10-28T03:30:00' },
  warnings: [] as unknown[],
};

function use(body: Record<string, unknown>) {
  server.use(http.get('/api/v1/system/pi-health', () => HttpResponse.json(body)));
}

describe('PiHealthCard', () => {
  it('shows the readings and that everything is fine', async () => {
    use(healthy);
    render(<PiHealthCard />);
    expect(await screen.findByText('Everything looks fine.')).toBeInTheDocument();
    expect(screen.getByText('52.3 °C')).toBeInTheDocument();
    expect(screen.getByText(/NVMe SSD \(\/dev\/nvme0n1p1\)/)).toBeInTheDocument();
    expect(screen.getByText('1 d 1 h')).toBeInTheDocument();
    expect(screen.getByText('1.2 days ago')).toBeInTheDocument();
  });

  it('lists warnings with their level text in the interface language', async () => {
    use({
      ...healthy,
      cpu_temp_c: 85,
      storage: { device: '/dev/mmcblk0p2', kind: 'sd' },
      warnings: [
        { level: 'crit', code: 'temp_critical', text: 'Prozessor sehr heiß', params: { temp: 85 } },
        { level: 'warn', code: 'sd_card', text: 'SD-Karte', params: {} },
      ],
    });
    render(<PiHealthCard />);
    expect(await screen.findByText('Processor very hot (85 °C): check cooling.')).toBeInTheDocument();
    expect(screen.getByText(/stored on an SD card|on an SD card, which wears out/i)).toBeInTheDocument();
    expect(screen.queryByText('Everything looks fine.')).not.toBeInTheDocument();
  });

  it('falls back to the server text for an unknown warning code', async () => {
    use({ ...healthy, warnings: [{ level: 'warn', code: 'neu_und_unbekannt', text: 'Server-Hinweis', params: {} }] });
    render(<PiHealthCard />);
    expect(await screen.findByText('Server-Hinweis')).toBeInTheDocument();
  });

  it('is hidden when nothing can be measured (for example on Windows)', async () => {
    use({
      cpu_temp_c: null,
      throttled: null,
      disk: null,
      storage: null,
      memory: null,
      uptime_seconds: null,
      backup: null,
      external_backup: null,
      warnings: [],
    });
    const { container } = render(<PiHealthCard />);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(container.querySelector('h2')).toBeNull();
  });

  it('shows a failed external backup', async () => {
    use({ ...healthy, external_backup: { ok: false, detail: 'Stick fehlt', at: '2026-10-28T03:30:00' } });
    render(<PiHealthCard />);
    expect(await screen.findByText('External backup')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
  });
});

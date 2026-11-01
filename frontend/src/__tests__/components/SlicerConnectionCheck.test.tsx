import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { SlicerConnectionCheck } from '../../components/SlicerConnectionCheck';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: {
    getSlicerStatus: vi.fn(),
    // Die Test-Hülle bringt Auth- und Theme-Provider mit, die beim Start
    // Einstellungen lesen.
    getSettings: vi.fn().mockResolvedValue({}),
    getAuthStatus: vi.fn().mockResolvedValue({ auth_enabled: false, user: null }),
  },
}));

const mockApi = api as unknown as { getSlicerStatus: ReturnType<typeof vi.fn> };

describe('SlicerConnectionCheck', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows the version when the saved sidecar answers', async () => {
    mockApi.getSlicerStatus.mockResolvedValue({
      configured: true,
      reachable: true,
      url: 'http://192.168.1.20:3001',
      version: '2.4.0',
      error: null,
    });

    render(<SlicerConnectionCheck />);
    await userEvent.click(screen.getByRole('button', { name: 'Check connection' }));

    expect(await screen.findByText(/Sidecar reachable\./)).toBeDefined();
    expect(screen.getByText(/v2\.4\.0/)).toBeDefined();
  });

  it('names the address that failed, not just the transport error', async () => {
    mockApi.getSlicerStatus.mockResolvedValue({
      configured: true,
      reachable: false,
      url: 'http://localhost:3001',
      version: null,
      error: 'Slicer sidecar unreachable: All connection attempts failed',
    });

    render(<SlicerConnectionCheck />);
    await userEvent.click(screen.getByRole('button', { name: 'Check connection' }));

    await waitFor(() => expect(screen.getByText('http://localhost:3001')).toBeDefined());
    expect(screen.getByText(/All connection attempts failed/)).toBeDefined();
  });

  it('says so when no address is configured', async () => {
    mockApi.getSlicerStatus.mockResolvedValue({
      configured: false,
      reachable: false,
      url: null,
      version: null,
      error: null,
    });

    render(<SlicerConnectionCheck />);
    await userEvent.click(screen.getByRole('button', { name: 'Check connection' }));

    expect(await screen.findByText('No address configured.')).toBeDefined();
  });
});

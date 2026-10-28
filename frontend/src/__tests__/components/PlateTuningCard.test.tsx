import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { PlateTuningCard } from '../../components/PlateTuningCard';

const analysis = (over: Record<string, unknown> = {}) => ({
  empty: [{ name: 'leer1.jpg', score: 0.2 }],
  occupied: [{ name: 'belegt1.jpg', score: 4.5 }],
  suggestion: {
    threshold: 1.2,
    min_confidence: 0.7,
    separable: true,
    quality: 'good',
    missed_objects: 0,
    false_alarms: 0,
    empty_max: 0.2,
    occupied_min: 4.5,
    message: '',
    ...over,
  },
});

function use(opts: { saved?: number | null; analysis?: unknown } = {}, calls: unknown[] = []) {
  server.use(
    http.get('/api/v1/printers/', () => HttpResponse.json([{ id: 7, name: 'P2S Werkstatt' }])),
    http.get('/api/v1/printers/7/camera/plate-detection/tuning', () =>
      HttpResponse.json({ saved: opts.saved ?? null, default: 1.0, effective: opts.saved ?? 1.0 }),
    ),
    http.post('/api/v1/printers/7/camera/plate-detection/tuning/analyze', ({ request }) => {
      calls.push({ multipart: (request.headers.get('content-type') ?? '').startsWith('multipart/form-data') });
      return HttpResponse.json(opts.analysis ?? analysis());
    }),
    http.put('/api/v1/printers/7/camera/plate-detection/tuning', async ({ request }) => {
      calls.push({ saved: await request.json() });
      return HttpResponse.json({ saved: 1.2 });
    }),
    http.delete('/api/v1/printers/7/camera/plate-detection/tuning', () => {
      calls.push('reset');
      return HttpResponse.json({ reset: true });
    }),
  );
}

const png = (name: string) => new File(['x'], name, { type: 'image/png' });

async function upload(emptyNames: string[], occupiedNames: string[]) {
  const [emptyInput, occupiedInput] = screen.getAllByLabelText(/Images with/) as HTMLInputElement[];
  await userEvent.upload(emptyInput, emptyNames.map(png));
  await userEvent.upload(occupiedInput, occupiedNames.map(png));
}

describe('PlateTuningCard', () => {
  it('shows the current threshold and keeps analyzing disabled until both sets are chosen', async () => {
    use();
    render(<PlateTuningCard canControl />);
    expect(await screen.findByText(/Current threshold: 1 %/)).toBeInTheDocument();
    expect(screen.getByText(/Current threshold: 1 % \(default\)/)).toBeInTheDocument();
    const analyze = screen.getByRole('button', { name: 'Analyze' });
    expect(analyze).toBeDisabled();
    await upload(['a.png'], []);
    expect(analyze).toBeDisabled();
  });

  it('uploads both groups, shows the scores and the suggestion', async () => {
    const calls: unknown[] = [];
    use({}, calls);
    render(<PlateTuningCard canControl />);
    await screen.findByText('P2S Werkstatt');
    await upload(['a.png', 'b.png'], ['c.png']);
    await userEvent.click(screen.getByRole('button', { name: 'Analyze' }));
    expect(await screen.findByText('0.20 %')).toBeInTheDocument();
    expect(screen.getByText('4.50 %')).toBeInTheDocument();
    expect(screen.getByText(/Suggestion: threshold 1.2 %, minimum confidence 0.7/)).toBeInTheDocument();
    expect(screen.getByText(/Clearly separable/)).toBeInTheDocument();
    expect(calls).toEqual([{ multipart: true }]);
  });

  it('applies the suggested threshold', async () => {
    const calls: unknown[] = [];
    use({}, calls);
    render(<PlateTuningCard canControl />);
    await screen.findByText('P2S Werkstatt');
    await upload(['a.png'], ['c.png']);
    await userEvent.click(screen.getByRole('button', { name: 'Analyze' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Apply threshold 1.2 %' }));
    await waitFor(() => expect(calls).toContainEqual({ saved: { threshold: 1.2 } }));
  });

  it('refuses to apply a threshold that would miss objects', async () => {
    use({ analysis: analysis({ quality: 'overlap', missed_objects: 2, separable: false }) });
    render(<PlateTuningCard canControl />);
    await screen.findByText('P2S Werkstatt');
    await upload(['a.png'], ['c.png']);
    await userEvent.click(screen.getByRole('button', { name: 'Analyze' }));
    expect(await screen.findByText(/would count as empty/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply threshold 1.2 %' })).toBeDisabled();
  });

  it('can reset a saved threshold', async () => {
    const calls: unknown[] = [];
    use({ saved: 2.5 }, calls);
    render(<PlateTuningCard canControl />);
    expect(await screen.findByText(/Current threshold: 2.5 %/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reset to default' }));
    await waitFor(() => expect(calls).toContain('reset'));
  });

  it('is read-only without the settings permission', async () => {
    use({ saved: 2.5 });
    render(<PlateTuningCard canControl={false} />);
    await screen.findByText('P2S Werkstatt');
    await upload(['a.png'], ['c.png']);
    expect(screen.getByRole('button', { name: 'Analyze' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reset to default' })).toBeDisabled();
  });

  it('stays hidden without printers', async () => {
    server.use(http.get('/api/v1/printers/', () => HttpResponse.json([])));
    const { container } = render(<PlateTuningCard canControl />);
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(container.querySelector('h2')).toBeNull();
  });
});

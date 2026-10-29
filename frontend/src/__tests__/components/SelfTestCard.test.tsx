import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse, delay } from 'msw';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { SelfTestCard } from '../../components/SelfTestCard';

const report = (over: Partial<{ results: object[]; summary: object }> = {}) => ({
  checked_at: '2026-10-29T12:00:00+00:00',
  results: [
    { id: 'database', title: 'Database', status: 'ok', detail: 'The database is up to date.', fix: null },
    { id: 'printers', title: 'Printers', status: 'warn', detail: 'Not connected: P1S.', fix: 'Switch the printer on.' },
    { id: 'scheduler', title: 'Print scheduler', status: 'fail', detail: 'The print scheduler is not running.', fix: 'Restart PrintLab.' },
    { id: 'probe_assistant', title: 'Test question to the model', status: 'skip', detail: 'Skipped.', fix: null },
  ],
  summary: { ok: 1, warn: 1, fail: 1, skip: 1 },
  ...over,
});

let calls = 0;

function use(answer: object | (() => Response | Promise<Response>) = report()) {
  calls = 0;
  server.use(
    http.post('/api/v1/selftest', async () => {
      calls += 1;
      return typeof answer === 'function' ? answer() : HttpResponse.json(answer);
    }),
  );
}

describe('SelfTestCard', () => {
  beforeEach(() => {
    calls = 0;
  });

  it('explains the check, including the two probes, and shows no result before the first run', () => {
    use();
    render(<SelfTestCard canRun />);
    expect(screen.getByRole('button', { name: 'Check now' })).toBeEnabled();
    expect(screen.getByText(/sends a test message through your notification channels and asks the model a test question/)).toBeInTheDocument();
    expect(screen.queryByTestId('selftest-summary')).not.toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it('runs on a click and lists every check with its state, detail and — for non-ok ones — what to do', async () => {
    use();
    render(<SelfTestCard canRun />);
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));
    expect(await screen.findByTestId('selftest-summary')).toHaveTextContent('1 fine, 1 notices, 1 errors, 1 skipped');
    const ok = screen.getByTestId('selftest-database');
    expect(within(ok).getByRole('img', { name: 'Fine' })).toBeInTheDocument();
    expect(within(ok).getByText('The database is up to date.')).toBeInTheDocument();
    const warn = screen.getByTestId('selftest-printers');
    expect(within(warn).getByRole('img', { name: 'Notice' })).toBeInTheDocument();
    expect(within(warn).getByText('Switch the printer on.')).toBeInTheDocument();
    const fail = screen.getByTestId('selftest-scheduler');
    expect(within(fail).getByRole('img', { name: 'Error' })).toBeInTheDocument();
    expect(within(fail).getByText('Restart PrintLab.')).toBeInTheDocument();
    expect(within(screen.getByTestId('selftest-probe_assistant')).getByRole('img', { name: 'Skipped' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Check again' })).toBeInTheDocument();
    expect(screen.getByText(/Checked at/)).toBeInTheDocument();
  });

  it('does not show a fix for a check that is fine', async () => {
    use(report({ results: [{ id: 'database', title: 'Database', status: 'ok', detail: 'Fine.', fix: 'Das sollte man nicht sehen.' }], summary: { ok: 1, warn: 0, fail: 0, skip: 0 } }));
    render(<SelfTestCard canRun />);
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));
    await screen.findByTestId('selftest-database');
    expect(screen.queryByText('Das sollte man nicht sehen.')).not.toBeInTheDocument();
    expect(screen.getByTestId('selftest-summary').className).toContain('text-bambu-green');
  });

  it('colours the summary by the worst result', async () => {
    use();
    render(<SelfTestCard canRun />);
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));
    expect((await screen.findByTestId('selftest-summary')).className).toContain('red');
  });

  it('shows that it is working, warns that a slow model takes time and blocks a second run meanwhile', async () => {
    use(async () => {
      await delay(300);
      return HttpResponse.json(report());
    });
    render(<SelfTestCard canRun />);
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));
    expect(await screen.findByRole('button', { name: 'Checking …' })).toBeDisabled();
    expect(screen.getByRole('status')).toHaveTextContent('up to two minutes');
    await screen.findByTestId('selftest-summary');
    expect(calls).toBe(1);
  });

  it('is disabled without permission', () => {
    use();
    render(<SelfTestCard canRun={false} />);
    expect(screen.getByRole('button', { name: 'Check now' })).toBeDisabled();
  });

  it('shows the server message when a run is refused and keeps the earlier result', async () => {
    use();
    render(<SelfTestCard canRun />);
    await userEvent.click(screen.getByRole('button', { name: 'Check now' }));
    await screen.findByTestId('selftest-summary');
    server.use(http.post('/api/v1/selftest', () => HttpResponse.json({ detail: 'The system check is already running.' }, { status: 429 })));
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }));
    expect(await screen.findByText('The system check is already running.')).toBeInTheDocument();
  });
});

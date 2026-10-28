import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { SetupBanner, SetupWizardCard } from '../../components/SetupWizardCard';
import { openSteps } from '../../utils/setupSteps';

const items = (done: Record<string, boolean | null>) => {
  const levels: Record<string, 'required' | 'recommended' | 'optional'> = {
    auth: 'required', printer: 'required', alerts: 'recommended', external_backup: 'recommended',
    guard: 'recommended', signature: 'recommended', storage: 'recommended', remote: 'optional', https: 'optional',
  };
  return Object.keys(levels).map((id) => ({ id, level: levels[id], done: id in done ? done[id] : true }));
};

function use(done: Record<string, boolean | null>) {
  const list = items(done);
  const applicable = list.filter((i) => i.done !== null);
  server.use(
    http.get('/api/v1/system/setup-status', () =>
      HttpResponse.json({
        items: list,
        done: applicable.filter((i) => i.done).length,
        total: applicable.length,
        required_open: applicable.filter((i) => i.level === 'required' && !i.done).length,
      }),
    ),
  );
}

describe('openSteps', () => {
  it('lists only open items, required first, and skips not-applicable ones', () => {
    const steps = openSteps({ items: items({ https: false, alerts: false, printer: false, guard: null }), done: 0, total: 0, required_open: 1 });
    expect(steps.map((s) => s.id)).toEqual(['printer', 'alerts', 'https']);
  });
});

describe('SetupWizardCard', () => {
  it('walks through the open items in order', async () => {
    use({ printer: false, alerts: false, storage: false });
    render(<SetupWizardCard />);
    expect(await screen.findByTestId('wizard-step')).toHaveTextContent('Step 1 of 3');
    expect(screen.getByText('Printer added')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByTestId('wizard-step')).toHaveTextContent('Step 2 of 3');
    expect(screen.getByRole('button', { name: 'Show card' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(screen.getByText(/done on the Pi itself/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Show card' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });

  it('shows nothing when everything is done', async () => {
    use({});
    const { container } = render(<SetupWizardCard />);
    await new Promise((r) => setTimeout(r, 100));
    expect(container.querySelector('[data-testid="setup-wizard"]')).toBeNull();
  });
});

describe('SetupBanner', () => {
  it('warns while required items are open and opens the assistant', async () => {
    use({ auth: false });
    let opened = 0;
    render(<SetupBanner onOpen={() => (opened += 1)} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('1 required item(s) open');
    await userEvent.click(screen.getByRole('button', { name: 'Open assistant' }));
    expect(opened).toBe(1);
  });

  it('is hidden when only recommended items are open', async () => {
    use({ alerts: false });
    render(<SetupBanner onOpen={() => undefined} />);
    await new Promise((r) => setTimeout(r, 100));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});

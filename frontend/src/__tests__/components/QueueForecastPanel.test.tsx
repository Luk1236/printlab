import { describe, it, expect } from 'vitest';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { QueueForecastPanel } from '../../components/QueueForecastPanel';
import { QueueItemFlags } from '../../components/QueuePriority';
import type { PrintQueueItem, Printer } from '../../api/client';

const printer = (id: number, name: string, model = 'X1C'): Printer => ({ id, name, model, location: null, is_active: true }) as Printer;
const job = (id: number, over: Partial<PrintQueueItem> = {}): PrintQueueItem =>
  ({
    id, status: 'pending', printer_id: null, target_model: 'X1C', target_location: null, waiting_reason: null, manual_start: false,
    position: id, priority: 1, print_time_seconds: 3600, scheduled_time: null, variants: [], due_at: null, due_warning: null, ...over,
  }) as PrintQueueItem;

const printers = [printer(1, 'Werkstatt X1C'), printer(2, 'Keller X1C')];

describe('QueueForecastPanel', () => {
  it('renders nothing when the queue has no active jobs', () => {
    const { container } = render(<QueueForecastPanel items={[job(1, { status: 'completed' })]} printers={printers} statuses={{}} sjfEnabled={false} />);
    expect(container.querySelector('[data-testid="queue-forecast"]')).toBeNull();
  });

  it('shows a card per printer with the running print, the queue load and the summary', () => {
    const items = [job(1, { status: 'printing', printer_id: 1, target_model: null }), job(2), job(3, { print_time_seconds: 1800 })];
    render(
      <QueueForecastPanel
        items={items}
        printers={printers}
        statuses={{ 1: { remaining_time: 90, state: 'RUNNING' }, 2: { state: 'IDLE' } }}
        sjfEnabled={false}
      />,
    );
    const summary = screen.getByTestId('forecast-summary');
    expect(summary).toHaveTextContent('Everything expected to finish');
    expect(summary).toHaveTextContent('2 jobs · 1h 30m of print time');
    const busy = screen.getByTestId('forecast-printer-1');
    expect(within(busy).getByText('Printing, free in 1h 30m')).toBeInTheDocument();
    const free = screen.getByTestId('forecast-printer-2');
    expect(within(free).getByText('Free')).toBeInTheDocument();
    expect(within(free).getByText(/2 queued · 1h 30m/)).toBeInTheDocument();
  });

  it('lists jobs without print time or without a matching printer as not included', () => {
    const items = [job(1, { print_time_seconds: null }), job(2, { target_model: 'H2D' }), job(3)];
    render(<QueueForecastPanel items={items} printers={printers} statuses={{ 1: { state: 'IDLE' }, 2: { state: 'IDLE' } }} sjfEnabled={false} />);
    expect(screen.getByText('1 job(s) without a print time are not included.')).toBeInTheDocument();
    expect(screen.getByText('1 job(s) without a matching printer are not included.')).toBeInTheDocument();
  });

  it('can be collapsed and keeps the summary', async () => {
    render(<QueueForecastPanel items={[job(1)]} printers={printers} statuses={{ 1: { state: 'IDLE' } }} sjfEnabled={false} />);
    expect(screen.getByTestId('forecast-printer-1')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Utilization and finish time' }));
    expect(screen.queryByTestId('forecast-printer-1')).toBeNull();
    expect(screen.getByTestId('forecast-summary')).toBeInTheDocument();
  });

  it('feeds the per-job finish time and the due-date warning from the forecast', () => {
    const tight = job(1, { due_at: new Date(Date.now() + 30 * 60 * 1000).toISOString(), print_time_seconds: 3600 });
    const fine = job(2, { printer_id: 2, target_model: null, due_at: new Date(Date.now() + 10 * 3600 * 1000).toISOString() });
    render(
      <>
        <QueueForecastPanel items={[tight, fine]} printers={printers} statuses={{ 1: { state: 'IDLE' }, 2: { state: 'IDLE' } }} sjfEnabled={false} />
        <div data-testid="row-tight"><QueueItemFlags item={tight} /></div>
        <div data-testid="row-fine"><QueueItemFlags item={fine} /></div>
      </>,
    );
    const tightRow = screen.getByTestId('row-tight');
    expect(within(tightRow).getByTestId('queue-item-forecast')).toHaveTextContent('Done around');
    expect(within(tightRow).getByText('Will miss the due date')).toBeInTheDocument();
    const fineRow = screen.getByTestId('row-fine');
    expect(within(fineRow).getByTestId('queue-item-forecast')).toBeInTheDocument();
    expect(within(fineRow).queryByText('Will miss the due date')).toBeNull();
  });

  it('waits behind earlier jobs when judging the due date', () => {
    const first = job(1, { printer_id: 1, target_model: null, print_time_seconds: 5 * 3600 });
    const second = job(2, { printer_id: 1, target_model: null, print_time_seconds: 1800, due_at: new Date(Date.now() + 2 * 3600 * 1000).toISOString() });
    render(
      <>
        <QueueForecastPanel items={[first, second]} printers={[printer(1, 'A')]} statuses={{ 1: { state: 'IDLE' } }} sjfEnabled={false} />
        <QueueItemFlags item={second} />
      </>,
    );
    // Starting right now it would fit (30 min < 2 h), but the 5 h job ahead pushes it past the due date.
    expect(screen.getByText('Will miss the due date')).toBeInTheDocument();
  });
});

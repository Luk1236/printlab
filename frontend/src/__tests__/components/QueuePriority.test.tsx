import { describe, it, expect, vi } from 'vitest';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { QueueItemFlags, QueuePriorityFilter } from '../../components/QueuePriority';
import { QueuePriorityFields } from '../../components/PrintModal/QueuePriorityFields';
import { DEFAULT_SCHEDULE_OPTIONS } from '../../components/PrintModal/types';
import { compareQueueOrder } from '../../utils/queueOrder';
import { queuePriorityPayload } from '../../utils/queuePriority';

describe('QueueItemFlags', () => {
  it('shows nothing for a normal item without a warning', () => {
    const { container } = render(<QueueItemFlags item={{ status: 'pending', priority: 1 }} />);
    expect(container.querySelector('[data-testid="queue-item-flags"]')).toBeNull();
  });

  it('marks urgent and low items and warns about the due date', () => {
    const { unmount } = render(<QueueItemFlags item={{ status: 'pending', priority: 2 }} />);
    expect(screen.getByText('Urgent')).toBeInTheDocument();
    unmount();
    const second = render(<QueueItemFlags item={{ status: 'pending', priority: 0 }} />);
    expect(screen.getByText('Low')).toBeInTheDocument();
    second.unmount();
    const third = render(<QueueItemFlags item={{ status: 'pending', due_warning: 'overdue' }} />);
    expect(screen.getByText('Overdue')).toBeInTheDocument();
    third.unmount();
    render(<QueueItemFlags item={{ status: 'pending', due_warning: 'too_late' }} />);
    expect(screen.getByText('Will miss the due date')).toBeInTheDocument();
  });

  it('shows nothing for finished items and treats a missing priority as normal', () => {
    const { container, rerender } = render(<QueueItemFlags item={{ status: 'completed', priority: 2, due_warning: 'overdue' }} />);
    expect(container.querySelector('[data-testid="queue-item-flags"]')).toBeNull();
    rerender(<QueueItemFlags item={{ status: 'pending' }} />);
    expect(container.querySelector('[data-testid="queue-item-flags"]')).toBeNull();
  });
});

describe('QueuePriorityFilter', () => {
  it('offers all levels and reports the choice', async () => {
    const onChange = vi.fn();
    render(<QueuePriorityFilter value="" onChange={onChange} />);
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['All priorities', 'Urgent', 'Normal', 'Low']);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Priority' }), '2');
    expect(onChange).toHaveBeenCalledWith('2');
  });
});

describe('QueuePriorityFields', () => {
  it('changes the priority and the due date in the schedule options', async () => {
    const onChange = vi.fn();
    render(<QueuePriorityFields options={DEFAULT_SCHEDULE_OPTIONS} onChange={onChange} />);
    await userEvent.selectOptions(screen.getByLabelText('Priority'), '2');
    expect(onChange).toHaveBeenLastCalledWith({ ...DEFAULT_SCHEDULE_OPTIONS, priority: 2 });
    expect(screen.getByText('Only warns; does not change the order.')).toBeInTheDocument();
  });
});

describe('queue order and payload', () => {
  const item = (id: number, position: number, priority?: number) => ({ id, position, priority });

  it('puts higher priority first, then the position', () => {
    const items = [item(1, 0, 0), item(2, 1, 1), item(3, 2, 2), item(4, 3), item(5, 4, 2)];
    expect(items.sort((a, b) => compareQueueOrder(a, b, false)).map((i) => i.id)).toEqual([3, 5, 2, 4, 1]);
  });

  it('keeps priority above shortest-job-first', () => {
    const long = { id: 1, position: 0, priority: 2, print_time_seconds: 9000 };
    const short = { id: 2, position: 1, priority: 1, print_time_seconds: 60 };
    expect(compareQueueOrder(long, short, true)).toBeLessThan(0);
  });

  it('builds the payload and drops an empty or invalid date', () => {
    expect(queuePriorityPayload({ priority: 2, dueAt: '' })).toEqual({ priority: 2, due_at: null });
    expect(queuePriorityPayload({ priority: 1, dueAt: 'kaputt' }).due_at).toBeNull();
    const payload = queuePriorityPayload({ priority: 0, dueAt: '2026-11-01T10:00' });
    expect(payload.priority).toBe(0);
    expect(new Date(payload.due_at as string).getTime()).toBe(new Date('2026-11-01T10:00').getTime());
  });
});

import { describe, it, expect, vi } from 'vitest';
import { fireEvent, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { BulkEditModal } from '../../components/QueueBulkEditModal';

function open(onSave = vi.fn()) {
  render(
    <BulkEditModal
      selectedCount={3}
      printers={[{ id: 1, name: 'X1C' }]}
      onSave={onSave}
      onClose={() => undefined}
      isSaving={false}
      canControlPrinter
      hasGcodeSnippets={false}
      t={(key) => key}
    />,
  );
  return onSave;
}

const apply = () => screen.getByRole('button', { name: 'queue.bulkEdit.applyChanges' });

describe('BulkEditModal — priority and due date', () => {
  it('starts with nothing to apply', () => {
    open();
    expect(apply()).toBeDisabled();
  });

  it('sends only the priority when only the priority is changed', async () => {
    const onSave = open();
    await userEvent.selectOptions(screen.getByLabelText('Priority'), '2');
    expect(apply()).toBeEnabled();
    await userEvent.click(apply());
    expect(onSave).toHaveBeenCalledWith({ priority: 2 });
    expect(onSave.mock.calls[0][0]).not.toHaveProperty('due_at');
  });

  it('can set low priority (0) — a falsy value must still count as a change', async () => {
    const onSave = open();
    await userEvent.selectOptions(screen.getByLabelText('Priority'), '0');
    await userEvent.click(apply());
    expect(onSave).toHaveBeenCalledWith({ priority: 0 });
  });

  it('sets a due date for all selected items', async () => {
    const onSave = open();
    await userEvent.selectOptions(screen.getByLabelText('Due date (optional)'), 'set');
    expect(apply()).toBeDisabled(); // no date entered yet
    fireEvent.change(screen.getByLabelText('Due date (optional)', { selector: 'input' }), { target: { value: '2026-11-05T09:30' } });
    expect(apply()).toBeEnabled();
    await userEvent.click(apply());
    const sent = onSave.mock.calls[0][0] as { due_at: string };
    expect(new Date(sent.due_at).getTime()).toBe(new Date('2026-11-05T09:30').getTime());
  });

  it('removes the due date with an explicit null', async () => {
    const onSave = open();
    await userEvent.selectOptions(screen.getByLabelText('Due date (optional)'), 'clear');
    await userEvent.click(apply());
    expect(onSave).toHaveBeenCalledWith({ due_at: null });
  });

  it('combines priority and due date, and drops them again when set back to unchanged', async () => {
    const onSave = open();
    await userEvent.selectOptions(screen.getByLabelText('Priority'), '2');
    await userEvent.selectOptions(screen.getByLabelText('Due date (optional)'), 'clear');
    await userEvent.selectOptions(screen.getByLabelText('Priority'), '');
    await userEvent.click(apply());
    expect(onSave).toHaveBeenCalledWith({ due_at: null });
    await userEvent.selectOptions(screen.getByLabelText('Due date (optional)'), 'unchanged');
    expect(apply()).toBeDisabled();
  });
});

/**
 * Tests for the useFocusTrap hook (WCAG 2.1 AA keyboard focus management).
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import { useFocusTrap } from '../../hooks/useFocusTrap';

function TestModal({
  isOpen,
  onClose,
  includeFocusables = true,
}: {
  isOpen: boolean;
  onClose?: () => void;
  includeFocusables?: boolean;
}) {
  const { containerRef } = useFocusTrap({ isOpen, onClose });

  if (!isOpen) return null;

  return (
    <div
      ref={containerRef}
      role="dialog"
      aria-modal="true"
      data-testid="modal-container"
      tabIndex={-1}
    >
      <h2>Modal Header</h2>
      {includeFocusables ? (
        <>
          <button data-testid="first-btn">First Button</button>
          <input data-testid="input-field" placeholder="Text input" />
          <button data-testid="last-btn">Last Button</button>
        </>
      ) : (
        <p>No interactive elements</p>
      )}
    </div>
  );
}

describe('useFocusTrap', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    document.body.style.overflow = '';
  });

  it('automatically focuses the first focusable element on mount', async () => {
    render(<TestModal isOpen={true} />);

    // requestAnimationFrame
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(document.activeElement).toBe(screen.getByTestId('first-btn'));
  });

  it('locks body scroll when opened and restores on unmount', () => {
    const { unmount } = render(<TestModal isOpen={true} />);
    expect(document.body.style.overflow).toBe('hidden');

    unmount();
    expect(document.body.style.overflow).toBe('');
  });

  it('traps Tab key navigation by wrapping from last to first element', async () => {
    render(<TestModal isOpen={true} />);

    const firstBtn = screen.getByTestId('first-btn');
    const lastBtn = screen.getByTestId('last-btn');

    lastBtn.focus();
    expect(document.activeElement).toBe(lastBtn);

    // Fire Tab on window / element
    fireEvent.keyDown(lastBtn, { key: 'Tab', shiftKey: false });
    expect(document.activeElement).toBe(firstBtn);
  });

  it('traps Shift+Tab key navigation by wrapping from first to last element', async () => {
    render(<TestModal isOpen={true} />);

    const firstBtn = screen.getByTestId('first-btn');
    const lastBtn = screen.getByTestId('last-btn');

    firstBtn.focus();
    expect(document.activeElement).toBe(firstBtn);

    fireEvent.keyDown(firstBtn, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(lastBtn);
  });

  it('calls onClose when Escape key is pressed', () => {
    const onClose = vi.fn();
    render(<TestModal isOpen={true} onClose={onClose} />);

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('restores focus to previously active element on unmount', async () => {
    const trigger = document.createElement('button');
    trigger.setAttribute('data-testid', 'trigger-btn');
    document.body.appendChild(trigger);
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    const { unmount } = render(<TestModal isOpen={true} />);
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(document.activeElement).toBe(screen.getByTestId('first-btn'));

    unmount();
    expect(document.activeElement).toBe(trigger);
    document.body.removeChild(trigger);
  });

  it('safely focuses container when no focusable elements are present', async () => {
    render(<TestModal isOpen={true} includeFocusables={false} />);
    await new Promise((resolve) => requestAnimationFrame(resolve));

    expect(document.activeElement).toBe(screen.getByTestId('modal-container'));
  });
});

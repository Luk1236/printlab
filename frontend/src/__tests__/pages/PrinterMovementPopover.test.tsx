/**
 * Tests for PrinterMovementPopover (accessibility & jog controls).
 */

import { describe, it, expect, vi, afterEach } from 'vitest';
import { screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { render } from '../utils';
import { PrinterMovementPopover } from '../../pages/PrinterMovementPopover';
import type { Printer } from '../../api/types';

describe('PrinterMovementPopover', () => {
  const mockPrinter: Printer = {
    id: 1,
    name: 'Lab X1C',
    model: 'X1C',
    serial_number: '00M00A000000000',
    ip_address: '192.168.1.100',
    access_code: '12345678',
    is_active: true,
  } as unknown as Printer;

  const defaultProps = {
    printer: mockPrinter,
    isPrinting: false,
    hasPermission: () => true,
    iconControlClass: 'test-icon-btn',
    bedJogStep: 10,
    setBedJogStep: vi.fn(),
    showBedJogMenu: null as string | null,
    setShowBedJogMenu: vi.fn(),
    homeAxesMutation: { mutate: vi.fn(), isPending: false },
    bedJogMutation: { mutate: vi.fn(), isPending: false },
    xyJogMutation: { mutate: vi.fn(), isPending: false },
    extruderJogMutation: { mutate: vi.fn(), isPending: false },
  };

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders trigger button with accessible ARIA attributes', () => {
    render(<PrinterMovementPopover {...defaultProps} />);
    const trigger = screen.getByRole('button');
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('renders open dialog with role="dialog" when active', () => {
    render(<PrinterMovementPopover {...defaultProps} showBedJogMenu="1" />);
    const dialog = screen.getByRole('dialog');
    expect(dialog).toBeInTheDocument();
  });

  it('highlights currently selected step with aria-pressed="true"', () => {
    render(<PrinterMovementPopover {...defaultProps} showBedJogMenu="1" bedJogStep={10} />);
    const step10 = screen.getByRole('button', { name: '10 mm' });
    const step1 = screen.getByRole('button', { name: '1 mm' });

    expect(step10).toHaveAttribute('aria-pressed', 'true');
    expect(step1).toHaveAttribute('aria-pressed', 'false');
  });

  it('calls setBedJogStep when step button is clicked', async () => {
    const user = userEvent.setup();
    const setStep = vi.fn();
    render(<PrinterMovementPopover {...defaultProps} showBedJogMenu="1" setBedJogStep={setStep} />);

    await user.click(screen.getByRole('button', { name: '50 mm' }));
    expect(setStep).toHaveBeenCalledWith(50);
  });

  it('triggers XY jog mutation on directional click', async () => {
    const user = userEvent.setup();
    const xyMutate = vi.fn();
    render(
      <PrinterMovementPopover
        {...defaultProps}
        showBedJogMenu="1"
        xyJogMutation={{ mutate: xyMutate, isPending: false }}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Move Y forward' }));
    expect(xyMutate).toHaveBeenCalledWith({ x: 0, y: 10 });
  });

  it('triggers home axes mutation on home click', async () => {
    const user = userEvent.setup();
    const homeMutate = vi.fn();
    const setMenu = vi.fn();
    render(
      <PrinterMovementPopover
        {...defaultProps}
        showBedJogMenu="1"
        setShowBedJogMenu={setMenu}
        homeAxesMutation={{ mutate: homeMutate, isPending: false }}
      />
    );

    await user.click(screen.getByRole('button', { name: 'Auto Home' }));
    expect(homeMutate).toHaveBeenCalledWith('all');
    expect(setMenu).toHaveBeenCalledWith(null);
  });
});

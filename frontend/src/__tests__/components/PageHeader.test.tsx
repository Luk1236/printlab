import { describe, it, expect, vi } from 'vitest';
import { screen, within, fireEvent } from '@testing-library/react';
import { Package } from 'lucide-react';
import { render } from '../utils';
import { PageHeader } from '../../components/PageHeader';

describe('PageHeader', () => {
  it('shows title, subtitle and the main actions', () => {
    render(
      <PageHeader icon={Package} title="Spools" subtitle="Manage your spools" actions={<button>Add spool</button>} />,
    );

    expect(screen.getByRole('heading', { name: 'Spools' })).toBeInTheDocument();
    expect(screen.getByText('Manage your spools')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Add spool' })).toBeInTheDocument();
  });

  it('shows no Actions menu without secondary actions', () => {
    render(<PageHeader title="Spools" actions={<button>Add spool</button>} />);

    expect(screen.queryByRole('button', { name: /Actions/ })).not.toBeInTheDocument();
  });

  it('keeps secondary actions in the Actions menu and runs them', () => {
    const onExport = vi.fn();
    render(<PageHeader title="Spools" more={[{ label: 'Export CSV', onClick: onExport }]} />);

    expect(screen.queryByText('Export CSV')).not.toBeInTheDocument();

    const header = screen.getByTestId('page-header');
    fireEvent.click(within(header).getByRole('button', { name: /Actions/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));

    expect(onExport).toHaveBeenCalledTimes(1);
  });

  it('does not run a disabled secondary action', () => {
    const onClick = vi.fn();
    render(<PageHeader title="Spools" more={[{ label: 'Export CSV', disabled: true, onClick }]} />);

    fireEvent.click(screen.getByRole('button', { name: /Actions/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }));

    expect(onClick).not.toHaveBeenCalled();
  });

  it('stacks below sm and lets the actions wrap', () => {
    render(<PageHeader title="Spools" actions={<button>Add spool</button>} />);

    const header = screen.getByTestId('page-header');
    expect(header.className).toContain('flex-col');
    expect(header.className).toContain('sm:flex-row');
    expect((header.lastElementChild as HTMLElement).className).toContain('flex-wrap');
  });
});

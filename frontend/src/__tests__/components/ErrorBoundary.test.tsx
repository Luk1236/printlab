import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import { reloadOnceAfterChunkError, reloadPage } from '../../utils/chunkReload';

vi.mock('../../utils/chunkReload', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../utils/chunkReload')>()),
  reloadOnceAfterChunkError: vi.fn(),
  reloadPage: vi.fn(),
}));

function Thrower({ message }: { message: string }): never {
  throw new Error(message);
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // React und die Boundary protokollieren den Absturz; im Testlauf ist das nur Rauschen.
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('reloads by itself when a page file failed to load', () => {
    render(
      <ErrorBoundary>
        <Thrower message="error loading dynamically imported module: http://pi:8000/assets/QueuePage-abc.js" />
      </ErrorBoundary>,
    );

    expect(screen.getByText('UI Crash')).toBeInTheDocument();
    expect(reloadOnceAfterChunkError).toHaveBeenCalledTimes(1);
  });

  it('does not reload by itself after an ordinary crash', () => {
    render(
      <ErrorBoundary>
        <Thrower message="boom" />
      </ErrorBoundary>,
    );

    expect(screen.getByText('boom')).toBeInTheDocument();
    expect(reloadOnceAfterChunkError).not.toHaveBeenCalled();
  });

  it('reloads the whole page on Retry, because React.lazy keeps a failed import', () => {
    render(
      <ErrorBoundary>
        <Thrower message="boom" />
      </ErrorBoundary>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    expect(reloadPage).toHaveBeenCalledTimes(1);
  });
});

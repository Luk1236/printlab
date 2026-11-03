import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { isChunkLoadError, reloadOnceAfterChunkError } from '../../utils/chunkReload';

describe('isChunkLoadError', () => {
  it.each([
    'Failed to fetch dynamically imported module: http://pi:8000/assets/QueuePage-abc.js',
    'error loading dynamically imported module: http://pi:8000/assets/QueuePage-abc.js',
    'Importing a module script failed.',
    'Unable to preload CSS for /assets/index-abc.css',
  ])('recognises %s', (message) => {
    expect(isChunkLoadError(new Error(message))).toBe(true);
  });

  it('leaves ordinary crashes alone', () => {
    expect(isChunkLoadError(new Error("Cannot read properties of undefined (reading 'id')"))).toBe(false);
    expect(isChunkLoadError('dynamically imported module')).toBe(false);
    expect(isChunkLoadError(null)).toBe(false);
  });
});

describe('reloadOnceAfterChunkError', () => {
  beforeEach(() => {
    sessionStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('reloads on the first failure', () => {
    const reload = vi.fn();

    expect(reloadOnceAfterChunkError(1_000_000, reload)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('does not reload again within a minute, so a dead server cannot cause a loop', () => {
    const reload = vi.fn();
    reloadOnceAfterChunkError(1_000_000, reload);

    expect(reloadOnceAfterChunkError(1_030_000, reload)).toBe(false);
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('reloads again once the minute has passed', () => {
    const reload = vi.fn();
    reloadOnceAfterChunkError(1_000_000, reload);

    expect(reloadOnceAfterChunkError(1_060_000, reload)).toBe(true);
    expect(reload).toHaveBeenCalledTimes(2);
  });

  it('does not reload when the guard cannot be stored', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const reload = vi.fn();

    expect(reloadOnceAfterChunkError(1_000_000, reload)).toBe(false);
    expect(reload).not.toHaveBeenCalled();
  });
});

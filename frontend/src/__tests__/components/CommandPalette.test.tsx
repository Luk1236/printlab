import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { CommandPalette } from '../../components/CommandPalette';

function mockSearch(results: Array<Record<string, unknown>>) {
  server.use(
    http.get('/api/v1/search', ({ request }) => {
      const query = new URL(request.url).searchParams.get('q') ?? '';
      return HttpResponse.json({ query, results });
    }),
  );
}

async function openPalette() {
  fireEvent.keyDown(document, { key: 'k', ctrlKey: true });
  return screen.findByTestId('command-palette');
}

describe('CommandPalette', () => {
  it('opens with Ctrl+K, filters pages and navigates with Enter', async () => {
    mockSearch([]);
    render(<CommandPalette />);
    await openPalette();

    const input = screen.getByPlaceholderText('Page, printer, file or archive …');
    await userEvent.type(input, 'archiv');
    expect(screen.getByRole('button', { name: 'Archives' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Settings' })).not.toBeInTheDocument();

    await userEvent.keyboard('{Enter}');
    expect(window.location.pathname).toBe('/archives');
  });

  it('shows server hits and opens the filtered archive list', async () => {
    mockSearch([{ kind: 'archive', id: 7, title: 'Benchy.3mf', subtitle: '30.10.2026' }]);
    render(<CommandPalette />);
    await openPalette();

    await userEvent.type(screen.getByRole('textbox'), 'benchy');
    const hit = await screen.findByRole('button', { name: 'Benchy.3mf' });
    await userEvent.click(hit);

    expect(window.location.pathname).toBe('/archives');
    expect(window.location.search).toBe('?search=benchy');
  });

  it('closes with Escape and does not query below two characters', async () => {
    let calls = 0;
    server.use(
      http.get('/api/v1/search', () => {
        calls += 1;
        return HttpResponse.json({ query: '', results: [] });
      }),
    );
    render(<CommandPalette />);
    await openPalette();
    await userEvent.type(screen.getByRole('textbox'), 'b');
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(calls).toBe(0);

    await userEvent.keyboard('{Escape}');
    expect(screen.queryByTestId('command-palette')).not.toBeInTheDocument();
  });
});

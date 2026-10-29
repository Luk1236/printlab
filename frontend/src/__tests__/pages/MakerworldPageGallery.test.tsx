/**
 * MakerWorld-Galerie: Suche und Sammlungsfilter wirken auf die eigenen Importe.
 *
 * Die Live-Suche bei MakerWorld ist serverseitig leer (siehe routes/makerworld.py);
 * die Seite zeigt deshalb den vorhandenen Bestand im MakerWorld-Layout.
 */

import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { server } from '../mocks/server';
import { MakerworldPage } from '../../pages/MakerworldPage';

function folder(id: number, name: string) {
  return {
    id,
    name,
    parent_id: null,
    project_id: null,
    archive_id: null,
    project_name: null,
    archive_name: null,
    is_external: false,
    external_path: null,
    external_readonly: false,
    file_count: 1,
    latest_activity_at: null,
    children: [],
  };
}

const recent = [
  {
    library_file_id: 11,
    filename: 'first-import.3mf',
    folder_id: 1,
    thumbnail_path: 'thumbnails/11.png',
    source_url: 'https://makerworld.com/models/1#profileId-2',
    created_at: '2026-10-01T12:00:00',
  },
  {
    library_file_id: 12,
    filename: 'second-import.3mf',
    folder_id: 2,
    thumbnail_path: null,
    source_url: 'https://makerworld.com/models/2',
    created_at: '2026-10-02T12:00:00',
  },
];

function handlers() {
  server.use(
    http.get('*/makerworld/status', () => HttpResponse.json({ has_cloud_token: true, can_download: true })),
    http.get('*/makerworld/recent-imports', () => HttpResponse.json(recent)),
    http.get('*/library/folders', () => HttpResponse.json([folder(1, 'MakerWorld'), folder(2, 'Deko')])),
    http.get('*/settings/', () => HttpResponse.json({ preferred_slicer: 'bambu_studio' })),
  );
}

describe('MakerworldPage gallery', () => {
  it('renders every import as a card with its source and date', async () => {
    handlers();
    render(<MakerworldPage />);

    expect(await screen.findByText(/Recent imports/i)).toBeInTheDocument();
    expect(screen.getAllByTestId('makerworld-card')).toHaveLength(2);
    expect(screen.getByText('first-import.3mf')).toBeInTheDocument();
    expect(screen.getByText('second-import.3mf')).toBeInTheDocument();
    expect(screen.getAllByText(/Imported 2026-10-0/)).toHaveLength(2);
  });

  it('filters the gallery by the search field', async () => {
    handlers();
    const user = userEvent.setup();
    render(<MakerworldPage />);

    await screen.findByText('first-import.3mf');
    await user.type(screen.getByRole('searchbox'), 'second');

    await waitFor(() => expect(screen.queryByText('first-import.3mf')).not.toBeInTheDocument());
    expect(screen.getByText('second-import.3mf')).toBeInTheDocument();
  });

  it('filters the gallery by collection', async () => {
    handlers();
    const user = userEvent.setup();
    render(<MakerworldPage />);

    await screen.findByText('first-import.3mf');
    await user.selectOptions(screen.getByRole('combobox', { name: 'Collections' }), '2');

    await waitFor(() => expect(screen.queryByText('first-import.3mf')).not.toBeInTheDocument());
    expect(screen.getByText('second-import.3mf')).toBeInTheDocument();
  });

  it('shows an empty state before the first import', async () => {
    handlers();
    server.use(http.get('*/makerworld/recent-imports', () => HttpResponse.json([])));
    render(<MakerworldPage />);

    expect(await screen.findByText(/No MakerWorld imports yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/Recent imports/i)).not.toBeInTheDocument();
  });
});

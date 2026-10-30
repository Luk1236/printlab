/**
 * Reine Hilfsfunktionen für die MakerWorld-Seite: Felder aus den undurchsichtigen API-Antworten
 * lesen, CDN-Adressen über den eigenen Thumbnail-Proxy leiten und den Bibliotheksbaum flach machen.
 *
 * Aus `pages/MakerworldPage.tsx` ausgelagert (siehe `backend/tests/unit/test_file_size_budget.py`):
 * Diese Funktionen brauchen weder React noch Übersetzungen und lassen sich einzeln prüfen.
 */

import type { LibraryFolderTree } from '../api/client';

export function pickString(obj: Record<string, unknown> | undefined, key: string): string {
  const value = obj?.[key];
  return typeof value === 'string' ? value : '';
}

export function pickNumber(obj: Record<string, unknown> | undefined, key: string): number | null {
  const value = obj?.[key];
  return typeof value === 'number' ? value : null;
}

export function pickObject(
  obj: Record<string, unknown> | undefined,
  key: string,
): Record<string, unknown> | undefined {
  const value = obj?.[key];
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

const CDN_HOSTS = /^https?:\/\/(makerworld|public-cdn)\.bblmw\.com\//i;

/** MakerWorld-CDN-Adresse über den eigenen Thumbnail-Proxy leiten (CSP erlaubt nur eigene Bilder). */
export function proxyCdn(url: string): string {
  if (!url) return '';
  if (!CDN_HOSTS.test(url)) return url;
  return `/api/v1/makerworld/thumbnail?url=${encodeURIComponent(url)}`;
}

/** CDN-Adressen in beschreibendem HTML umschreiben (Beschreibungen enthalten `<img src="...">`). */
export function proxyCdnUrlsInHtml(html: string): string {
  return html.replace(
    /(https?:\/\/(?:makerworld|public-cdn)\.bblmw\.com\/[^\s"']+)/gi,
    (match) => `/api/v1/makerworld/thumbnail?url=${encodeURIComponent(match)}`,
  );
}

export type FlatFolder = { folder: LibraryFolderTree; depth: number };

/** Bibliotheksbaum tiefenweise in eine Liste für ein `<select>` legen (mit Tiefe zum Einrücken). */
export function flattenFolderTree(tree: LibraryFolderTree, depth = 0, out: FlatFolder[] = []): FlatFolder[] {
  out.push({ folder: tree, depth });
  for (const child of tree.children ?? []) {
    flattenFolderTree(child, depth + 1, out);
  }
  return out;
}

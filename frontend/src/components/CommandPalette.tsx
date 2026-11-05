import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Search } from 'lucide-react';

import { api } from '../api/client';
import type { GlobalSearchHit, Permission } from '../api/client';
import { useAuth } from '../contexts/AuthContext';

interface PageEntry {
  to: string;
  labelKey: string;
  permission?: Permission;
}

/**
 * Dieselben Ziele wie die Seitenleiste, nur flach. Bewusst eine eigene Liste statt ``defaultNavItems`` aus dem
 * ``Layout``: der Import wäre ein Kreis (das Layout mountet die Palette) und würde die Seitenleisten-Reihenfolge an
 * dieses Overlay koppeln. Ein Ziel, das hier fehlt, ist über die Seitenleiste weiterhin erreichbar.
 */
const PAGES: PageEntry[] = [
  { to: '/', labelKey: 'nav.printers', permission: 'printers:read' },
  { to: '/archives', labelKey: 'nav.archives' },
  { to: '/queue', labelKey: 'nav.queue' },
  { to: '/files', labelKey: 'nav.files' },
  { to: '/projects', labelKey: 'nav.projects' },
  { to: '/inventory', labelKey: 'nav.inventory' },
  { to: '/maintenance', labelKey: 'nav.maintenance' },
  { to: '/assistant', labelKey: 'nav.assistant' },
  { to: '/settings?tab=setup', labelKey: 'setupWizard.title', permission: 'settings:read' },
  { to: '/error-help', labelKey: 'nav.errorHelp' },
  { to: '/settings?tab=system', labelKey: 'nav.systemStatus', permission: 'settings:read' },
  { to: '/stats', labelKey: 'nav.stats' },
  { to: '/notifications', labelKey: 'nav.notifications' },
  { to: '/settings', labelKey: 'nav.settings', permission: 'settings:read' },
];

/** Ziel einer Trefferkarte: Listen-Seite mit dem Suchbegriff, damit der Fund dort gleich gefiltert steht. */
function hitUrl(kind: GlobalSearchHit['kind'], query: string): string {
  if (kind === 'archive') return `/archives?search=${encodeURIComponent(query)}`;
  if (kind === 'library') return `/files?search=${encodeURIComponent(query)}`;
  if (kind === 'queue') return '/queue';
  return '/';
}

export function CommandPalette() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { hasPermission } = useAuth();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  const pages = useMemo(
    () =>
      PAGES.filter((page) => !page.permission || hasPermission(page.permission)).filter((page) =>
        t(page.labelKey).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
      ),
    [hasPermission, query, t],
  );

  const { data } = useQuery({
    queryKey: ['globalSearch', query],
    queryFn: () => api.searchGlobal(query),
    enabled: open && query.trim().length >= 2,
    staleTime: 30_000,
    retry: false,
  });
  const items = useMemo(() => {
    const hits = query.trim().length >= 2 ? (data?.results ?? []) : [];
    return [
      ...pages.map((page) => ({ key: `page:${page.to}`, label: t(page.labelKey), run: () => navigate(page.to) })),
      ...hits.map((hit) => ({
        key: `${hit.kind}:${hit.id}`,
        label: hit.title,
        run: () => navigate(hitUrl(hit.kind, query)),
      })),
    ];
  }, [data, navigate, pages, query, t]);

  useEffect(() => setActive(0), [query, open]);

  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener('open-command-palette', onOpen);
    return () => window.removeEventListener('open-command-palette', onOpen);
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setOpen((wasOpen) => !wasOpen);
        return;
      }
      if (!open) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
      } else if (event.key === 'ArrowDown') {
        event.preventDefault();
        setActive((index) => (items.length ? (index + 1) % items.length : 0));
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setActive((index) => (items.length ? (index - 1 + items.length) % items.length : 0));
      } else if (event.key === 'Enter' && items[active]) {
        event.preventDefault();
        items[active].run();
        setOpen(false);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [items, active, open]);

  useEffect(() => {
    if (!open) {
      setQuery('');
      return;
    }
    inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    const entry = listRef.current?.children[active] as HTMLElement | undefined;
    entry?.scrollIntoView({ block: 'nearest' });
  }, [active]);

  if (!open) return null;

  const choose = (run: () => void) => {
    run();
    setOpen(false);
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/50 p-4 pt-[10vh]"
      onMouseDown={() => setOpen(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('commandPalette.title')}
        data-testid="command-palette"
        className="w-full max-w-lg overflow-hidden rounded-xl border border-bambu-dark-tertiary bg-bambu-card shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-bambu-dark-tertiary px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-bambu-gray" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('commandPalette.placeholder')}
            aria-label={t('commandPalette.placeholder')}
            className="w-full bg-transparent text-sm text-white placeholder-bambu-gray focus:outline-none"
            autoComplete="off"
            spellCheck={false}
          />
        </div>

        <ul ref={listRef} className="max-h-80 overflow-y-auto py-1" data-testid="command-palette-list">
          {items.length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-bambu-gray">{t('commandPalette.empty')}</li>
          )}
          {items.map((item, index) => (
            <li key={item.key}>
              <button
                type="button"
                onClick={() => choose(item.run)}
                onMouseEnter={() => setActive(index)}
                className={`flex w-full items-center justify-between gap-3 px-4 py-2 text-left text-sm ${
                  index === active ? 'bg-bambu-green/15 text-white' : 'text-bambu-gray hover:bg-bambu-dark-secondary'
                }`}
              >
                <span className="truncate">{item.label}</span>
              </button>
            </li>
          ))}
        </ul>

        <div className="border-t border-bambu-dark-tertiary px-4 py-2 text-xs text-bambu-gray">
          {t('commandPalette.hint')}
        </div>
      </div>
    </div>
  );
}

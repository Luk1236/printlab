import { useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { MoreVertical } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { ContextMenu, type ContextMenuItem } from './ContextMenu';

interface PageHeaderProps {
  icon?: LucideIcon;
  title: ReactNode;
  subtitle?: ReactNode;
  /** Hauptaktionen: bleiben sichtbar (ein bis zwei Knöpfe, Ansichtsumschalter). */
  actions?: ReactNode;
  /** Nebenaktionen: wandern in das Menü „Aktionen“, damit die Kopfzeile ruhig bleibt. */
  more?: ContextMenuItem[];
}

/**
 * Einheitlicher Seitenkopf: links Titel mit Symbol und Untertitel, rechts die Hauptaktionen und – wenn es mehr als
 * zwei, drei Knöpfe wären – ein Menü „Aktionen“ für den Rest. Unter `sm` stapelt sich alles und die Knöpfe umbrechen
 * (sonst schiebt eine lange Knopfreihe auf dem Handy die ganze Seite zur Seite, #2813).
 */
export function PageHeader({ icon: Icon, title, subtitle, actions, more }: PageHeaderProps) {
  const { t } = useTranslation();
  const anchorRef = useRef<HTMLButtonElement>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const hasMore = !!more && more.length > 0;

  const toggleMenu = () => {
    if (menu) {
      setMenu(null);
      return;
    }
    const rect = anchorRef.current?.getBoundingClientRect();
    if (rect) setMenu({ x: Math.max(8, rect.right - 220), y: rect.bottom + 4 });
  };

  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between" data-testid="page-header">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          {Icon && <Icon className="w-7 h-7 text-bambu-green flex-shrink-0" />}
          {title}
        </h1>
        {subtitle && <p className="text-bambu-gray mt-1">{subtitle}</p>}
      </div>
      {(actions || hasMore) && (
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {hasMore && (
            <button
              ref={anchorRef}
              type="button"
              onClick={toggleMenu}
              aria-haspopup="menu"
              aria-expanded={menu !== null}
              className="inline-flex items-center gap-1.5 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark-secondary px-3 py-2 text-sm text-white hover:bg-bambu-dark-tertiary transition-colors"
            >
              <MoreVertical className="w-4 h-4" />
              {t('common.actions')}
            </button>
          )}
        </div>
      )}
      {menu && hasMore && (
        <ContextMenu x={menu.x} y={menu.y} items={more} onClose={() => setMenu(null)} anchorRef={anchorRef} />
      )}
    </div>
  );
}

/**
 * Suchfeld, Filter, Ansicht und Aktionen der Druckerliste.
 *
 * Aus PrintersPage ausgelagert: die Seite war mit knapp 2 000 Zeilen an der
 * Größengrenze, und die Leiste ist ein geschlossener Block — sie liest nur die
 * Filter- und Ansichtseinstellungen und schreibt sie über ihre Rückrufe zurück.
 * Das Messen für die kompakte Fassung (drei Menüs statt einer Reihe) gehört
 * dazu, weil es ausschließlich diese Leiste betrifft.
 */

import { useLayoutEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link as RouterLink } from 'react-router-dom';
import {
  ArrowDown,
  ArrowUp,
  CheckSquare,
  ChevronDown,
  ExternalLink,
  Filter,
  LayoutGrid,
  MonitorPlay,
  MoreHorizontal,
  Plus,
  Power,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { api, type Permission, type Printer } from '../api/client';
import { Button } from '../components/Button';
import { ToolbarDropdown, ToolbarMenu } from './PrinterCardParts';
import { STATUS_FILTER_OPTIONS, type SortOption } from './printerCardHelpers';

export interface PrinterToolbarProps {
  printers: Printer[] | undefined;
  search: string;
  onSearchChange: (value: string) => void;
  statusFilter: string;
  onStatusFilterChange: (value: string) => void;
  availableLocations: string[];
  locationFilter: string;
  onLocationFilterChange: (value: string) => void;
  hideDisconnected: boolean;
  onToggleHideDisconnected: () => void;
  sortBy: SortOption;
  onSortChange: (value: SortOption) => void;
  sortAsc: boolean;
  onToggleSortDirection: () => void;
  pageView: 'cards' | 'camwall';
  onPageViewChange: (view: 'cards' | 'camwall') => void;
  cardSize: number;
  onCardSizeChange: (size: number) => void;
  hasPermission: (permission: Permission) => boolean;
  selectionMode: boolean;
  onToggleSelection: () => void;
  smartPlugByPrinter: Record<number, { id: number; name: string }>;
  poweringOn: number | null;
  onPowerOn: (plugId: number) => void;
  onAddPrinter: () => void;
}

function usePrinterOfflineStatus(printerId: number) {
  const { data: status } = useQuery({
    queryKey: ['printerStatus', printerId],
    queryFn: () => api.getPrinterStatus(printerId),
    refetchInterval: 30000,
  });
  return !status?.connected;
}

// Power dropdown item for an offline printer
function PowerDropdownItem({
  printer,
  plug,
  onPowerOn,
  isPowering,
}: {
  printer: Printer;
  plug: { id: number; name: string };
  onPowerOn: (plugId: number) => void;
  isPowering: boolean;
}) {
  const isOffline = usePrinterOfflineStatus(printer.id);

  // Fetch plug status
  const { data: plugStatus } = useQuery({
    queryKey: ['smartPlugStatus', plug.id],
    queryFn: () => api.getSmartPlugStatus(plug.id),
    refetchInterval: 10000,
  });

  // Only show if printer is offline
  if (!isOffline) {
    return null;
  }

  return (
    <div className="flex items-center justify-between px-3 py-2 hover:bg-gray-100 dark:hover:bg-bambu-dark-tertiary">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-sm text-white truncate">{printer.name}</span>
        {plugStatus && (
          <span
            className={`text-xs px-1.5 py-0.5 rounded ${
              plugStatus.state === 'ON'
                ? 'bg-bambu-green/20 text-bambu-green'
                : 'bg-red-100 dark:bg-red-500/20 text-red-700 dark:text-red-400'
            }`}
          >
            {plugStatus.state || '?'}
          </span>
        )}
      </div>
      <button
        onClick={() => onPowerOn(plug.id)}
        disabled={isPowering || plugStatus?.state === 'ON'}
        className={`px-2 py-1 text-xs rounded transition-colors flex items-center gap-1 ${
          plugStatus?.state === 'ON'
            ? 'bg-bambu-green/20 text-bambu-green cursor-default'
            : 'bg-bambu-green/20 text-bambu-green hover:bg-bambu-green hover:text-white'
        }`}
      >
        <Power className="w-3 h-3" />
        {isPowering ? '...' : 'On'}
      </button>
    </div>
  );
}

export function PrinterToolbar({
  printers,
  search,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  availableLocations,
  locationFilter,
  onLocationFilterChange,
  hideDisconnected,
  onToggleHideDisconnected,
  sortBy,
  onSortChange,
  sortAsc,
  onToggleSortDirection,
  pageView,
  onPageViewChange,
  cardSize,
  onCardSizeChange,
  hasPermission,
  selectionMode,
  onToggleSelection,
  smartPlugByPrinter,
  poweringOn,
  onPowerOn,
  onAddPrinter,
}: PrinterToolbarProps) {
  const { t } = useTranslation();
  const [showPowerDropdown, setShowPowerDropdown] = useState(false);
  const toolbarRef = useRef<HTMLDivElement>(null);
  const expandedToolbarControlsRef = useRef<HTMLDivElement>(null);
  const expandedToolbarWidthRef = useRef(0);
  const [compactToolbar, setCompactToolbar] = useState(false);

  const measureToolbar = () => {
    const toolbar = toolbarRef.current;
    if (!toolbar) return;

    const measuredControlsWidth = expandedToolbarControlsRef.current?.offsetWidth;
    if (measuredControlsWidth) {
      expandedToolbarWidthRef.current = measuredControlsWidth;
    }

    const searchMinimumWidth = 220;
    const gapWidth = 8;
    const shouldCompact =
      expandedToolbarWidthRef.current > 0 &&
      toolbar.clientWidth < expandedToolbarWidthRef.current + searchMinimumWidth + gapWidth;
    setCompactToolbar((prev) => (prev === shouldCompact ? prev : shouldCompact));
  };

  const smartPlugCount = Object.keys(smartPlugByPrinter).length;
  useLayoutEffect(() => {
    measureToolbar();

    const toolbar = toolbarRef.current;
    if (!toolbar) return;

    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measureToolbar);
      return () => window.removeEventListener('resize', measureToolbar);
    }

    const resizeObserver = new ResizeObserver(() => measureToolbar());
    resizeObserver.observe(toolbar);
    window.addEventListener('resize', measureToolbar);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener('resize', measureToolbar);
    };
  }, [printers?.length, availableLocations.length, hideDisconnected, smartPlugCount]);

  const cardSizeLabels = ['S', 'M', 'L', 'XL'];

  const renderFilterControls = (inMenu = false) => (
    <>
      {/* Status filter */}
      {printers && printers.length > 0 && (
        <ToolbarDropdown
          value={statusFilter}
          onChange={onStatusFilterChange}
          fullWidth={inMenu}
          options={STATUS_FILTER_OPTIONS.map((option) => ({
            value: option.value,
            label: t(option.labelKey),
          }))}
        />
      )}

      {/* Location filter — only shown when at least one printer has a location */}
      {printers && printers.length > 0 && availableLocations.length > 0 && (
        <ToolbarDropdown
          value={locationFilter}
          onChange={onLocationFilterChange}
          fullWidth={inMenu}
          options={[
            { value: 'all', label: t('printers.filter.allLocations') },
            ...availableLocations.map((loc) => ({ value: loc, label: loc })),
          ]}
        />
      )}

      <button
        type="button"
        onClick={onToggleHideDisconnected}
        aria-pressed={hideDisconnected}
        className={`h-8 px-2 rounded-lg border text-sm font-medium transition-colors ${inMenu ? 'w-full' : ''} ${
          hideDisconnected
            ? 'bg-bambu-green border-bambu-green text-white'
            : 'bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary'
        }`}
      >
        {t('printers.hideOffline')}
      </button>
    </>
  );

  const renderViewControls = (inMenu = false) => (
    <>
      {/* Sort dropdown */}
      <div className={`flex items-center gap-1 ${inMenu ? 'w-full' : ''}`}>
        <ToolbarDropdown<SortOption>
          value={sortBy}
          onChange={onSortChange}
          fullWidth={inMenu}
          options={[
            { value: 'name', label: t('printers.sort.name') },
            { value: 'status', label: t('printers.sort.status') },
            { value: 'model', label: t('printers.sort.model') },
            { value: 'location', label: t('printers.sort.location') },
            { value: 'eta', label: t('printers.sort.eta') },
          ]}
        />
        <button
          onClick={onToggleSortDirection}
          className="h-8 shrink-0 px-2 rounded-lg border bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary transition-colors flex items-center justify-center"
          title={sortAsc ? t('printers.sort.descending') : t('printers.sort.ascending')}
        >
          {sortAsc ? <ArrowUp className="w-4 h-4 text-white" /> : <ArrowDown className="w-4 h-4 text-white" />}
        </button>
      </div>

      {/* Page view toggle: Cards / Cam Wall */}
      <div
        className={`flex h-8 items-center bg-bambu-dark rounded-lg border border-bambu-dark-tertiary ${
          inMenu ? 'w-full' : ''
        }`}
      >
        <button
          type="button"
          onClick={() => onPageViewChange('cards')}
          className={`flex h-full items-center gap-1 rounded-l-lg px-2 text-xs font-medium transition-colors ${
            inMenu ? 'flex-1 justify-center' : ''
          } ${pageView === 'cards' ? 'bg-bambu-green text-white' : 'text-white hover:bg-bambu-dark-tertiary'}`}
          title={t('printers.pageView.cards')}
          aria-pressed={pageView === 'cards'}
        >
          <LayoutGrid className="w-3.5 h-3.5" />
          {inMenu && <span>{t('printers.pageView.cards')}</span>}
        </button>
        <button
          type="button"
          onClick={() => onPageViewChange('camwall')}
          className={`flex h-full items-center gap-1 rounded-r-lg px-2 text-xs font-medium transition-colors ${
            inMenu ? 'flex-1 justify-center' : ''
          } ${pageView === 'camwall' ? 'bg-bambu-green text-white' : 'text-white hover:bg-bambu-dark-tertiary'}`}
          title={t('printers.pageView.camWall')}
          aria-pressed={pageView === 'camwall'}
          disabled={!hasPermission('camera:view')}
        >
          <MonitorPlay className="w-3.5 h-3.5" />
          {inMenu && <span>{t('printers.pageView.camWall')}</span>}
        </button>
      </div>

      {/* Cam Wall on its own URL (#2531) — the linkable/bookmarkable form of the
          view, and the page a kiosk token points at. Only offered once the wall
          is the active view, so it doesn't compete with the toggle above. */}
      {pageView === 'camwall' && hasPermission('camera:view') && (
        <RouterLink
          to="/camwall"
          className={`flex h-8 items-center gap-1 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark px-2 text-xs font-medium text-white transition-colors hover:bg-bambu-dark-tertiary ${
            inMenu ? 'w-full justify-center' : ''
          }`}
          title={t('printers.pageView.openCamWallPage')}
        >
          <ExternalLink className="w-3.5 h-3.5" />
          {inMenu && <span>{t('printers.pageView.openCamWallPage')}</span>}
        </RouterLink>
      )}

      {/* Card size selector */}
      <div
        className={`flex h-8 items-center bg-bambu-dark rounded-lg border border-bambu-dark-tertiary ${
          pageView === 'camwall' ? 'opacity-40 pointer-events-none' : ''
        } ${inMenu ? 'w-full' : ''}`}
      >
        {cardSizeLabels.map((label, index) => {
          const size = index + 1;
          const isSelected = cardSize === size;
          return (
            <button
              key={label}
              onClick={() => onCardSizeChange(size)}
              className={`h-full px-2 text-xs font-medium transition-colors ${inMenu ? 'flex-1' : ''} ${
                index === 0 ? 'rounded-l-lg' : ''
              } ${index === cardSizeLabels.length - 1 ? 'rounded-r-lg' : ''} ${
                isSelected ? 'bg-bambu-green text-white' : 'text-white hover:bg-bambu-dark-tertiary'
              }`}
              title={
                label === 'S'
                  ? t('printers.cardSize.small')
                  : label === 'M'
                    ? t('printers.cardSize.medium')
                    : label === 'L'
                      ? t('printers.cardSize.large')
                      : t('printers.cardSize.extraLarge')
              }
            >
              {label}
            </button>
          );
        })}
      </div>
    </>
  );

  const renderActionControls = (inMenu = false) => (
    <>
      {/* Bulk select toggle */}
      <button
        onClick={onToggleSelection}
        className={`h-8 px-2 rounded-lg border transition-colors ${
          inMenu ? 'w-full justify-center gap-1.5 text-sm font-medium flex items-center' : ''
        } ${
          selectionMode
            ? 'bg-bambu-green border-bambu-green text-white'
            : 'bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary'
        }`}
        title={t('printers.bulk.select')}
        disabled={!hasPermission('printers:control')}
      >
        <CheckSquare className="w-4 h-4" />
        {inMenu && <span>{t('printers.bulk.select')}</span>}
      </button>

      {/* Power dropdown for offline printers with smart plugs */}
      {hideDisconnected && smartPlugCount > 0 && (
        <div className={`relative ${inMenu ? 'w-full' : ''}`}>
          <button
            onClick={() => setShowPowerDropdown(!showPowerDropdown)}
            className={`h-8 flex items-center gap-1.5 px-2 text-sm rounded-lg border transition-colors ${
              inMenu
                ? 'w-full justify-between bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary hover:text-white'
                : 'bg-bambu-dark border-bambu-dark-tertiary text-white hover:bg-bambu-dark-tertiary'
            }`}
          >
            <span className="flex items-center gap-1.5">
              <Power className="w-4 h-4" />
              {t('printers.powerOn')}
            </span>
            <ChevronDown className={`w-3 h-3 transition-transform ${showPowerDropdown ? 'rotate-180' : ''}`} />
          </button>
          {showPowerDropdown && (
            <>
              {/* Backdrop to close dropdown */}
              <div className="fixed inset-0 z-10" onClick={() => setShowPowerDropdown(false)} />
              <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-bambu-dark-secondary border border-gray-200 dark:border-bambu-dark-tertiary rounded-lg shadow-lg z-20 py-1">
                <div className="px-3 py-2 text-xs text-gray-500 dark:text-bambu-gray border-b border-gray-200 dark:border-bambu-dark-tertiary">
                  {t('printers.offlinePrintersWithPlugs')}
                </div>
                {printers
                  ?.filter((p) => smartPlugByPrinter[p.id])
                  .map((printer) => (
                    <PowerDropdownItem
                      key={printer.id}
                      printer={printer}
                      plug={smartPlugByPrinter[printer.id]}
                      onPowerOn={onPowerOn}
                      isPowering={poweringOn === smartPlugByPrinter[printer.id]?.id}
                    />
                  ))}
                {printers?.filter((p) => smartPlugByPrinter[p.id]).length === 0 && (
                  <div className="px-3 py-2 text-sm text-bambu-gray">No printers with smart plugs</div>
                )}
              </div>
            </>
          )}
        </div>
      )}
      <Button
        onClick={onAddPrinter}
        disabled={!hasPermission('printers:create')}
        title={!hasPermission('printers:create') ? t('printers.permission.noAdd') : undefined}
        className={`!h-8 !min-h-8 px-2 py-0 ${inMenu ? 'w-full' : ''}`}
      >
        <Plus className="w-4 h-4" />
        {t('printers.addPrinter')}
      </Button>
    </>
  );

  return (
    <div ref={toolbarRef} className="relative flex items-center gap-2">
      {/* Only show search bar when printers exist */}
      {printers && printers.length > 0 && (
        <div className="relative min-w-0 flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray/50" />
          <input
            type="search"
            name="printer-search"
            autoComplete="off"
            data-1p-ignore
            data-lpignore="true"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder={t('printers.search')}
            aria-label={t('printers.search')}
            className="w-full h-8 pl-9 pr-8 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-white text-sm placeholder:text-bambu-gray/50 focus:outline-none focus:border-bambu-green"
          />
          {search && (
            <button
              type="button"
              aria-label={t('common.clear')}
              onClick={() => onSearchChange('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-bambu-gray hover:text-white"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      )}
      <div
        ref={expandedToolbarControlsRef}
        aria-hidden={compactToolbar}
        inert={compactToolbar}
        className={`${
          compactToolbar
            ? 'absolute -left-[9999px] top-0 flex w-max pointer-events-none opacity-0'
            : 'flex'
        } ml-auto items-center justify-end gap-2 flex-nowrap [&>*]:shrink-0`}
      >
        <div className="h-6 w-px bg-bambu-dark-tertiary" />
        <div className="flex items-center gap-2">{renderFilterControls()}</div>
        <div className="h-6 w-px bg-bambu-dark-tertiary" />
        <div className="flex items-center gap-2">{renderViewControls()}</div>
        <div className="h-6 w-px bg-bambu-dark-tertiary" />
        <div className="flex items-center gap-2">{renderActionControls()}</div>
      </div>

      {compactToolbar && (
        <div className="ml-auto flex items-center justify-end gap-1">
          <ToolbarMenu label={t('printers.toolbar.filters', 'Filters')} icon={<Filter className="w-4 h-4" />}>
            <div className="flex w-48 flex-col gap-2">{renderFilterControls(true)}</div>
          </ToolbarMenu>
          <ToolbarMenu label={t('printers.toolbar.view', 'View')} icon={<SlidersHorizontal className="w-4 h-4" />}>
            <div className="flex w-48 flex-col gap-2">{renderViewControls(true)}</div>
          </ToolbarMenu>
          <ToolbarMenu label={t('printers.toolbar.actions', 'Actions')} icon={<MoreHorizontal className="w-4 h-4" />}>
            <div className="flex w-48 flex-col gap-2">{renderActionControls(true)}</div>
          </ToolbarMenu>
        </div>
      )}
    </div>
  );
}

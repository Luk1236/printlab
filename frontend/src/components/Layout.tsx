import { useState, useEffect, useCallback, useRef, useMemo, Suspense } from 'react';
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Search, Printer, Archive, ListOrdered, BarChart3, Cloud, Settings, Sun, Moon, Monitor, ChevronLeft, ChevronRight, ChevronDown, Keyboard, Github, ArrowUpCircle, Wrench, FolderKanban, FolderOpen, X, Menu, Plug, Bug, LogOut, Key, Loader2, Disc3, ShieldAlert, Globe, Bell, Receipt, Megaphone, LifeBuoy, Bot, type LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../contexts/ThemeContext';
import { KeyboardShortcutsModal } from './KeyboardShortcutsModal';
import { InstallAppButton } from './InstallAppButton';
import { SwitchbarPopover } from './SwitchbarPopover';
import { useQuery, useQueries } from '@tanstack/react-query';
import { api, supportApi, pendingUploadsApi, bugReportApi, type Permission } from '../api/client';
import { getIconByName } from './IconPicker';
import { useIsSidebarCompact } from '../hooks/useIsSidebarCompact';
import { useColorCatalogVersion } from '../hooks/useColorCatalogVersion';
import { useUnknownTagPrompt } from '../hooks/useUnknownTagPrompt';
import { UnknownSpoolModal } from './UnknownSpoolModal';
import { ConfirmOutcomeDialog } from './ConfirmOutcomeDialog';
import { useAuth } from '../contexts/AuthContext';
import { useToast } from '../contexts/ToastContext';
import { Card, CardHeader, CardContent } from './Card';
import { PageLoading } from './PageLoading';
import { parseUTCDate } from '../utils/date';
import { Button } from './Button';
import { BugReportBubble } from './BugReportBubble';
import { CommandPalette } from './CommandPalette';
import { AnnouncementsPanel } from './AnnouncementsPanel';
import { AnnouncementBanner } from './AnnouncementBanner';
import { useAnnouncements } from '../hooks/useAnnouncements';
import {
  getHiddenSidebarSystemItemIds,
  getSidebarOrder,
  isExternalSidebarItemId,
  saveHiddenSidebarSystemItemIds,
  saveSidebarOrder,
  SIDEBAR_LAYOUT_CHANGED_EVENT,
} from '../utils/sidebarLayout';


interface NavItem {
  id: string;
  to: string;
  icon: LucideIcon;
  labelKey: string; // Translation key
}

export const defaultNavItems: NavItem[] = [
  { id: 'printers', to: '/', icon: Printer, labelKey: 'nav.printers' },
  { id: 'inventory', to: '/inventory', icon: Disc3, labelKey: 'nav.inventory' },
  { id: 'archives', to: '/archives', icon: Archive, labelKey: 'nav.archives' },
  { id: 'queue', to: '/queue', icon: ListOrdered, labelKey: 'nav.queue' },
  { id: 'projects', to: '/projects', icon: FolderKanban, labelKey: 'nav.projects' },
  { id: 'files', to: '/files', icon: FolderOpen, labelKey: 'nav.files' },
  { id: 'makerworld', to: '/makerworld', icon: Globe, labelKey: 'nav.makerworld' },
  { id: 'profiles', to: '/profiles', icon: Cloud, labelKey: 'nav.profiles' },
  { id: 'maintenance', to: '/maintenance', icon: Wrench, labelKey: 'nav.maintenance' },
  { id: 'assistant', to: '/assistant', icon: Bot, labelKey: 'nav.assistant' },
  { id: 'error-help', to: '/error-help', icon: LifeBuoy, labelKey: 'nav.errorHelp' },
  { id: 'stats', to: '/stats', icon: BarChart3, labelKey: 'nav.stats' },
  // Opt-in feature: gated in isHidden() on the billing_enabled setting, so the
  // entry stays out of the sidebar entirely until an admin turns billing on.
  { id: 'finance', to: '/finance', icon: Receipt, labelKey: 'nav.finance' },
  // User-account feature: gated in isHidden() on advanced auth + user_notifications
  // + the notifications:user_email permission. Kept adjacent to Settings
  // intentionally. Do not drop this entry — without it the /notifications page
  // is orphaned (route + page still exist but no nav link) (#1901).
  { id: 'notifications', to: '/notifications', icon: Bell, labelKey: 'nav.notifications' },
  { id: 'settings', to: '/settings', icon: Settings, labelKey: 'nav.settings' },
];

// Gruppierung der Seitenleiste. Die Reihenfolge innerhalb einer Gruppe bleibt
// die vom Benutzer gespeicherte; die Gruppen selbst stehen in fester Folge.
// Alles, was hier nicht genannt ist (externe Links, spätere Seiten), landet
// unter „Mehr“, damit keine Seite unsichtbar wird.
const NAV_GROUPS: { id: string; labelKey: string; defaultLabel: string; items: string[] }[] = [
  { id: 'print', labelKey: 'nav.groupPrint', defaultLabel: 'Drucken', items: ['printers', 'queue', 'archives'] },
  { id: 'library', labelKey: 'nav.groupLibrary', defaultLabel: 'Dateien & Modelle', items: ['projects', 'files', 'makerworld', 'profiles'] },
  { id: 'material', labelKey: 'nav.groupMaterial', defaultLabel: 'Material & Kosten', items: ['inventory', 'finance'] },
  { id: 'operations', labelKey: 'nav.groupOperations', defaultLabel: 'Betrieb', items: ['maintenance', 'assistant', 'stats', 'error-help', 'notifications'] },
  { id: 'admin', labelKey: 'nav.groupAdmin', defaultLabel: 'Verwaltung', items: ['settings'] },
];

// Get default view from localStorage
export function getDefaultView(): string {
  return localStorage.getItem('defaultView') || '/';
}

// Save default view to localStorage
export function setDefaultView(path: string) {
  localStorage.setItem('defaultView', path);
}

export function Layout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { mode, resolvedMode, toggleMode } = useTheme();
  const { t } = useTranslation();
  const isSidebarCompact = useIsSidebarCompact();

  // Bug-report panel state lives here because the trigger moves (#2750,
  // reporter @goodjaltman). Below the sidebar-compact breakpoint the floating
  // disc is replaced by a button in the compact header: the bottom-right corner
  // is the most contended region in the app — the Profiles scroll-to-top FAB,
  // the floating camera window and its resize handle, the Group Edit save bar,
  // the bulk-selection toolbars, and the File Manager / Archives per-card
  // action buttons all live there — and a fixed 48px disc sits on top of
  // whichever of them happens to be underneath. Moving out of the corner is
  // the only fix that covers in-flow content as well as fixed overlays.
  const [bugReportOpen, setBugReportOpen] = useState(false);
  // A bug-report logging run survives the panel being closed (#2847). The
  // floating disc shows that itself; the compact header's button and the
  // debug-logging banner need telling.
  const [bugReportLogging, setBugReportLogging] = useState(false);

  // Theme toggle: mode → icon and tooltip
  const ThemeIcon = { dark: Sun, light: Monitor, system: Moon }[mode];
  const themeSwitchTitle = t({ dark: 'nav.switchToLight', light: 'nav.switchToSystem', system: 'nav.switchToDark' }[mode]);

  // Re-render Layout (and the page rendered inside <Outlet />) whenever the
  // backend color catalog is (re)populated, so pages that mounted before the
  // catalog fetched — and cached HSL-fallback color names during their first
  // render — refresh with the real catalog names. See #857.
  useColorCatalogVersion();
  const { user, authEnabled, logout, hasPermission, hasAnyPermission, loading: authLoading } = useAuth();
  const { showToast } = useToast();
  const [showChangePasswordModal, setShowChangePasswordModal] = useState(false);
  const [changePasswordData, setChangePasswordData] = useState({ currentPassword: '', newPassword: '', confirmPassword: '' });
  const [changePasswordLoading, setChangePasswordLoading] = useState(false);
  const [sidebarExpanded, setSidebarExpanded] = useState(() => {
    const stored = localStorage.getItem('sidebarExpanded');
    return stored !== 'false';
  });
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [showSwitchbar, setShowSwitchbar] = useState(false);
  const defaultSidebarOrder = useMemo(() => defaultNavItems.map(i => i.id), []);
  const [sidebarOrder, setSidebarOrder] = useState<string[]>(() => getSidebarOrder(defaultNavItems.map(i => i.id)));
  const [hiddenSystemItemIds, setHiddenSystemItemIds] = useState<string[]>(getHiddenSidebarSystemItemIds);
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>(() => {
    try {
      const stored = localStorage.getItem('sidebarCollapsedGroups');
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  const toggleGroup = useCallback((groupId: string) => {
    setCollapsedGroups((prev) => {
      const next = prev.includes(groupId) ? prev.filter((id) => id !== groupId) : [...prev, groupId];
      try {
        localStorage.setItem('sidebarCollapsedGroups', JSON.stringify(next));
      } catch {
        // ignore
      }
      return next;
    });
  }, []);
  const hasRedirected = useRef(false);
  const [dismissedUpdateVersion, setDismissedUpdateVersion] = useState<string | null>(() =>
    sessionStorage.getItem('dismissedUpdateVersion')
  );
  const [plateDetectionAlert, setPlateDetectionAlert] = useState<{
    printer_id: number;
    printer_name: string;
    message: string;
  } | null>(null);
  // Post-print outcome confirmation (#1898): archive waiting for a verdict,
  // set by the print_confirm_request WebSocket event.
  const [confirmOutcomeArchiveId, setConfirmOutcomeArchiveId] = useState<number | null>(null);

  // Check for updates
  // Fork: Fehlerberichte gehen nur an ein eingerichtetes Relay; ohne Relay verschwindet der Knopf.
  const { data: bugReportStatus } = useQuery({
    queryKey: ['bug-report-status'],
    queryFn: bugReportApi.status,
    staleTime: Infinity,
  });
  const bugReportEnabled = bugReportStatus?.enabled !== false;

  const { data: versionInfo } = useQuery({
    queryKey: ['version'],
    queryFn: api.getVersion,
    staleTime: Infinity,
  });

  // GET /settings requires settings:read, so for every non-admin this query
  // 403'd and each of the four gates below silently took its fallback: Finance
  // vanished from the sidebar for the users cost_centers:read_own exists for,
  // a disabled user_notifications setting stopped applying to them, the sponsor
  // prompt showed EUR whatever the install uses, and the update check ran where
  // it had been switched off. Two of those were invisible to an administrator
  // testing it, because an administrator can read /settings (#3023).
  const { data: uiFlags } = useQuery({
    queryKey: ['ui-flags'],
    queryFn: api.getUiFlags,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Antwortet das eingestellte Slicer-Sidecar? Die Slice-Maske fragt dasselbe
  // beim Öffnen; hier steht es auf jeder Seite, damit ein ausgeschalteter PC
  // auffällt, bevor jemand ein Modell zum Slicen ablegt. Ein Fehler der
  // Abfrage selbst (ältere Installation) zeigt nichts an.
  const { data: slicerStatus } = useQuery({
    queryKey: ['slicer-status'],
    queryFn: api.getSlicerStatus,
    staleTime: 30_000,
    refetchInterval: (query) => (query.state.data?.configured ? 60_000 : false),
    retry: false,
  });
  const slicerDown = slicerStatus?.configured === true && !slicerStatus.reachable;

  // Announcements from the PrintLab maintainers: the sidebar entry above System,
  // the slide-over list, and the banner for unread important/critical ones. The
  // entry is there for whoever may see announcements, also with none published.
  const {
    visible: announcementsVisible,
    announcements,
    unread: unreadAnnouncements,
    bannerItems,
    markRead: markAnnouncementRead,
  } = useAnnouncements();
  const [announcementsOpen, setAnnouncementsOpen] = useState(false);
  const [announcementFocus, setAnnouncementFocus] = useState<string | null>(null);
  const openAnnouncements = useCallback((focusId?: string) => {
    setMobileDrawerOpen(false);
    setAnnouncementFocus(focusId ?? null);
    setAnnouncementsOpen(true);
  }, []);
  const closeAnnouncements = useCallback(() => setAnnouncementsOpen(false), []);

  // Sponsor-prompt toast — fires once per session post-auth if a milestone is eligible.
  // Fork: keine Spenden-Aufforderung.

  // Unknown-spool prompt — surfaces a confirmation modal when the AMS reports a
  // tag with no inventory match (only when `auto_add_unknown_rfid` is off).
  const unknownSpool = useUnknownTagPrompt();

  // Fetch default sidebar order via a public endpoint (no settings:read needed)
  const { data: defaultSidebarData } = useQuery({
    queryKey: ['default-sidebar-order'],
    queryFn: api.getDefaultSidebarOrder,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });

  // Apply admin default sidebar order once per user (skipped if already applied).
  // Uses a per-user localStorage flag to prevent re-application.
  useEffect(() => {
    const defaultOrder = defaultSidebarData?.default_sidebar_order;
    if (!defaultOrder) return;
    // Wait for auth state to settle before applying to avoid double-execution
    if (authEnabled && !user) return;
    const appliedKey = user ? `sidebarDefaultApplied_${user.id}` : 'sidebarDefaultApplied';
    if (localStorage.getItem(appliedKey)) return;
    try {
      const parsed = JSON.parse(defaultOrder);
      const orderArr = Array.isArray(parsed) ? parsed : parsed.order;
      if (!Array.isArray(orderArr) || orderArr.length === 0) return;
      // Filter to valid sidebar item IDs only
      const validIds = new Set(defaultNavItems.map(i => i.id));
      const filtered = orderArr.filter((id: string) => typeof id === 'string' && (validIds.has(id) || isExternalSidebarItemId(id)));
      if (filtered.length > 0) {
        setSidebarOrder(filtered);
        saveSidebarOrder(filtered);
        const hiddenIds = Array.isArray(parsed) ? [] : parsed.hiddenSystemItemIds;
        if (Array.isArray(hiddenIds)) {
          const filteredHiddenIds = hiddenIds.filter((id: string) => typeof id === 'string' && validIds.has(id) && id !== 'settings');
          setHiddenSystemItemIds(filteredHiddenIds);
          saveHiddenSidebarSystemItemIds(filteredHiddenIds);
        }
        localStorage.setItem(appliedKey, '1');
      }
    } catch (e) {
      console.error('Failed to apply default sidebar order:', e);
    }
  }, [defaultSidebarData?.default_sidebar_order, setSidebarOrder, user, authEnabled]);

  // Check advanced auth status — the notifications nav item is gated on it
  // (rendered only when authEnabled && advanced_auth_enabled && user_notifications_enabled).
  const { data: advancedAuthStatus } = useQuery({
    queryKey: ['advancedAuthStatus'],
    queryFn: api.getAdvancedAuthStatus,
    staleTime: 5 * 60 * 1000, // 5 minutes
    enabled: authEnabled,
  });

  const { data: updateCheck } = useQuery({
    queryKey: ['updateCheck'],
    queryFn: api.checkForUpdates,
    enabled: uiFlags?.check_updates !== false,
    staleTime: 60 * 60 * 1000, // 1 hour
    refetchInterval: 60 * 60 * 1000, // Check every hour
  });

  // Fetch external links for sidebar
  const { data: externalLinks } = useQuery({
    queryKey: ['external-links'],
    queryFn: api.getExternalLinks,
  });

  // Fetch smart plugs to check for switchbar items
  const { data: smartPlugs } = useQuery({
    queryKey: ['smart-plugs'],
    queryFn: api.getSmartPlugs,
    staleTime: 30 * 1000, // 30 seconds
  });

  const hasSwitchbarPlugs = smartPlugs?.some(p => p.show_in_switchbar) ?? false;

  // Check debug logging state
  const { data: debugLoggingState } = useQuery({
    queryKey: ['debugLogging'],
    queryFn: supportApi.getDebugLoggingState,
    staleTime: 60 * 1000, // 1 minute
    refetchInterval: 60 * 1000, // Refresh every minute
  });

  // Check developer LAN mode warnings
  const { data: devModeWarnings } = useQuery({
    queryKey: ['developer-mode-warnings'],
    queryFn: api.getDeveloperModeWarnings,
    staleTime: 10 * 1000,
    refetchInterval: 30 * 1000,
    refetchOnWindowFocus: true,
  });

  // Fetch pending queue items count for badge
  const { data: queueItems } = useQuery({
    queryKey: ['queue', 'pending'],
    queryFn: () => api.getQueue(undefined, 'pending'),
    staleTime: 5 * 1000, // 5 seconds
    refetchInterval: 5 * 1000, // Refresh every 5 seconds
    refetchOnWindowFocus: true,
  });
  const pendingQueueCount = queueItems?.length ?? 0;

  // Fetch pending uploads count for archive badge (virtual printer review items)
  const { data: pendingUploadsData } = useQuery({
    queryKey: ['pending-uploads', 'count'],
    queryFn: pendingUploadsApi.getCount,
    staleTime: 5 * 1000, // 5 seconds
    refetchInterval: 5 * 1000, // Refresh every 5 seconds
    refetchOnWindowFocus: true,
  });
  const pendingUploadsCount = pendingUploadsData?.count ?? 0;

  // Check if any printer with pending queue items needs plate clearing
  const queuePrinterIds = useMemo(() => {
    const ids = new Set<number>();
    queueItems?.forEach(item => {
      if (item.printer_id) ids.add(item.printer_id);
    });
    return Array.from(ids);
  }, [queueItems]);

  const printerStatusQueries = useQueries({
    queries: queuePrinterIds.map(id => ({
      queryKey: ['printerStatus', id],
      queryFn: () => api.getPrinterStatus(id),
      staleTime: 30 * 1000, // WebSocket keeps this warm
    })),
  });

  const needsClearPlate = printerStatusQueries.some(result => {
    const status = result.data;
    if (!status) return false;
    return !!status.awaiting_plate_clear;
  });

  // Calculate debug duration client-side for real-time updates
  const [debugDuration, setDebugDuration] = useState<number | null>(null);
  useEffect(() => {
    if (!debugLoggingState?.enabled || !debugLoggingState.enabled_at) {
      setDebugDuration(null);
      return;
    }
    const enabledAt = parseUTCDate(debugLoggingState.enabled_at)?.getTime() ?? Date.now();
    const updateDuration = () => {
      setDebugDuration(Math.floor((Date.now() - enabledAt) / 1000));
    };
    updateDuration();
    const interval = setInterval(updateDuration, 1000);
    return () => clearInterval(interval);
  }, [debugLoggingState?.enabled, debugLoggingState?.enabled_at]);

  // Build the unified sidebar items list - memoized to prevent re-renders
  const navItemsMap = useMemo(() => new Map(defaultNavItems.map(item => [item.id, item])), []);
  const extLinksMap = useMemo(() => new Map((externalLinks || []).map(link => [`ext-${link.id}`, link])), [externalLinks]);

  // Compute the ordered sidebar: include stored order + any new items
  // Hide nav items the user doesn't have read permission for
  const orderedSidebarIds = (() => {
    const result: string[] = [];
    const seen = new Set<string>();

    // Map nav item IDs to the permission(s) required to see them. Resources
    // that ship in three tiers (legacy `*:read` + granular `*:read_own` /
    // `*:read_all`) list all three: the default Operators group is seeded
    // with `_own` only, so gating on the legacy alone hides the entry from
    // every non-admin user even though the underlying API accepts their
    // request (#1755).
    const navPermissions: Record<string, Permission | Permission[]> = {
      archives: ['archives:read', 'archives:read_own', 'archives:read_all'],
      queue: ['queue:read', 'queue:read_own', 'queue:read_all'],
      stats: 'stats:read',
      profiles: 'kprofiles:read',
      maintenance: 'maintenance:read',
      assistant: 'printers:read',
      'error-help': 'printers:read',
      projects: 'projects:read',
      inventory: 'inventory:read',
      finance: 'cost_centers:read_own',
      files: ['library:read', 'library:read_own', 'library:read_all'],
      makerworld: 'makerworld:view',
      settings: 'settings:read',
      // The user-email-preferences API requires notifications:user_email, so
      // gate the nav item on the same permission (both default groups —
      // Administrators and Operators — hold it). The advanced-auth /
      // user_notifications enablement gate is applied separately below.
      notifications: 'notifications:user_email',
    };

    const isHidden = (id: string) => {
      // User-toggled hide (#1673) wins first — cheapest check, explicit intent.
      if (hiddenSystemItemIds.includes(id)) return true;
      // Permission gate accepts Permission | Permission[] so resources with
      // granular `*:read_own` / `*:read_all` tiers (default Operators group)
      // don't get hidden from users who only hold the granular variant (#1755).
      if (authEnabled && id in navPermissions) {
        const required = navPermissions[id];
        const granted = Array.isArray(required)
          ? required.some((p) => hasPermission(p))
          : hasPermission(required);
        if (!granted) return true;
      }
      // notifications nav item also requires advanced auth to be enabled and user_notifications_enabled setting
      if (id === 'notifications' && (!authEnabled || !advancedAuthStatus?.advanced_auth_enabled || (uiFlags?.user_notifications_enabled === false))) return true;
      // Finance is off by default and the page is meaningless without it, so it
      // stays hidden until billing is explicitly on. Tested for `true` rather
      // than `!== false` on purpose: the flags are undefined on the first
      // render, and a nav entry that appears and then vanishes reads as a
      // glitch. That polarity is also why reading this from /settings hid the
      // entry outright for anyone without settings:read, rather than failing
      // open the way the notifications gate two lines up did (#3023).
      if (id === 'finance' && uiFlags?.billing_enabled !== true) return true;
      return false;
    };

    // Add items in stored order
    for (const id of sidebarOrder) {
      if (isHidden(id)) continue;
      if (navItemsMap.has(id) || extLinksMap.has(id)) {
        result.push(id);
        seen.add(id);
      }
    }

    // Add any new internal nav items not in stored order
    for (const item of defaultNavItems) {
      if (isHidden(item.id)) continue;
      if (!seen.has(item.id)) {
        result.push(item.id);
        seen.add(item.id);
      }
    }

    // Add any new external links not in stored order
    for (const link of externalLinks || []) {
      const extId = `ext-${link.id}`;
      if (!seen.has(extId)) {
        result.push(extId);
        seen.add(extId);
      }
    }

    return result;
  })();

  // Gruppen und Einträge; Seiten außerhalb der Gruppen (externe Links,
  // neue Einträge) kommen unter „Mehr“.
  const sidebarGroups = useMemo(() => {
    const groups = NAV_GROUPS.map((group) => ({
      ...group,
      ids: orderedSidebarIds.filter((id) => group.items.includes(id)),
    }));
    const known = new Set(NAV_GROUPS.flatMap((group) => group.items));
    const rest = orderedSidebarIds.filter((id) => !known.has(id));
    if (rest.length > 0) {
      groups.push({ id: 'more', labelKey: 'nav.groupMore', defaultLabel: 'Mehr', items: [], ids: rest });
    }
    return groups.filter((g) => g.ids.length > 0);
  }, [orderedSidebarIds]);

  const sidebarItemIds = useMemo(() => {
    return sidebarGroups.flatMap((g) => g.ids);
  }, [sidebarGroups]);

  // Show update banner if update available and not dismissed for this version.
  // Suppressed when running as a Home Assistant addon — HA Supervisor surfaces
  // its own update notification in the HA UI, so the in-app banner is duplicate
  // noise that links to a page that just says "update via HA."
  const showUpdateBanner = updateCheck?.update_available &&
    updateCheck.latest_version &&
    updateCheck.latest_version !== dismissedUpdateVersion &&
    !updateCheck.is_ha_addon;

  const dismissUpdateBanner = () => {
    if (updateCheck?.latest_version) {
      sessionStorage.setItem('dismissedUpdateVersion', updateCheck.latest_version);
      setDismissedUpdateVersion(updateCheck.latest_version);
    }
  };

  // Redirect to default view on initial load
  useEffect(() => {
    if (!hasRedirected.current && location.pathname === '/') {
      const defaultView = getDefaultView();
      if (defaultView !== '/') {
        hasRedirected.current = true;
        navigate(defaultView, { replace: true });
      }
    }
  }, [location.pathname, navigate]);

  useEffect(() => {
    localStorage.setItem('sidebarExpanded', String(sidebarExpanded));
  }, [sidebarExpanded]);

  useEffect(() => {
    const refreshSidebarLayout = () => {
      setSidebarOrder(getSidebarOrder(defaultSidebarOrder));
      setHiddenSystemItemIds(getHiddenSidebarSystemItemIds());
    };
    window.addEventListener(SIDEBAR_LAYOUT_CHANGED_EVENT, refreshSidebarLayout);
    window.addEventListener('storage', refreshSidebarLayout);
    return () => {
      window.removeEventListener(SIDEBAR_LAYOUT_CHANGED_EVENT, refreshSidebarLayout);
      window.removeEventListener('storage', refreshSidebarLayout);
    };
  }, [defaultSidebarOrder]);

  // Close compact drawer on navigation
  useEffect(() => {
    if (isSidebarCompact) {
      setMobileDrawerOpen(false);
    }
  }, [location.pathname, isSidebarCompact]);

  // Listen for plate detection warnings (objects on plate, print paused)
  // Only show to users with printers:control permission
  useEffect(() => {
    const handlePlateNotEmpty = (event: Event) => {
      // Only show alert to users who can control printers
      if (!hasPermission('printers:control')) {
        return;
      }
      const detail = (event as CustomEvent).detail;
      setPlateDetectionAlert({
        printer_id: detail.printer_id,
        printer_name: detail.printer_name,
        message: detail.message,
      });
    };
    window.addEventListener('plate-not-empty', handlePlateNotEmpty);
    return () => window.removeEventListener('plate-not-empty', handlePlateNotEmpty);
  }, [hasPermission]);

  // A completed print asked for its outcome verdict (#1898). Same CustomEvent
  // relay as plate-not-empty, and gated the same way: the PATCH route decides
  // who may record a verdict, so a user who cannot should not be handed a
  // dialog whose only outcome is a 403.
  // Held until the auth state has landed: while it is loading, `authEnabled`
  // is still false and every permission check answers yes, which would open
  // the dialog for exactly the user this gate exists to spare.
  const canConfirmOutcome = !authLoading && hasAnyPermission('archives:update_all', 'archives:update_own');
  useEffect(() => {
    const handleConfirmRequest = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (typeof detail?.archive_id === 'number') {
        setConfirmOutcomeArchiveId(detail.archive_id);
      }
    };
    window.addEventListener('print-confirm-request', handleConfirmRequest);
    return () => window.removeEventListener('print-confirm-request', handleConfirmRequest);
  }, []);

  // The ?confirm=<id> deep link a push notification carries (#1898). It is read
  // here and not on ArchivesPage because that page renders inside this Layout's
  // <Outlet />: React flushes a child's effects before its parent's, so a page
  // dispatching `print-confirm-request` on mount fired before the listener above
  // existed — which is exactly the cold load a notification tap produces. The
  // parameter is stripped afterwards so a reload does not re-open the dialog.
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const confirmId = params.get('confirm');
    if (!confirmId || !/^\d+$/.test(confirmId)) {
      return;
    }
    setConfirmOutcomeArchiveId(Number(confirmId));
    params.delete('confirm');
    const rest = params.toString();
    navigate({ pathname: location.pathname, search: rest ? `?${rest}` : '' }, { replace: true });
  }, [location.pathname, location.search, navigate]);

  // Global keyboard shortcuts for navigation
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    const target = e.target as HTMLElement;
    // Ignore if typing in an input/textarea
    if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
      return;
    }

    // Number keys for navigation (1-9) - follows sidebar order including external links
    if (!e.metaKey && !e.ctrlKey && !e.altKey) {
      const keyNum = parseInt(e.key);
      if (keyNum >= 1 && keyNum <= sidebarItemIds.length && keyNum <= 9) {
        const id = sidebarItemIds[keyNum - 1];
        e.preventDefault();

        if (isExternalSidebarItemId(id)) {
          // External link
          const extLink = extLinksMap.get(id);
          if (extLink?.open_in_new_tab) {
            window.open(extLink.url, '_blank', 'noopener,noreferrer');
          } else {
            const linkId = id.replace('ext-', '');
            navigate(`/external/${linkId}`);
          }
        } else {
          // Internal nav item
          const navItem = navItemsMap.get(id);
          if (navItem) {
            navigate(navItem.to);
          }
        }
        return;
      }

      switch (e.key) {
        case '?':
          e.preventDefault();
          setShowShortcuts(true);
          break;
        case 'Escape':
          setShowShortcuts(false);
          break;
      }
    }
  }, [navigate, sidebarItemIds, navItemsMap, extLinksMap]);

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="flex min-h-screen">
      {/* Skip-Link (Tastatur, Screenreader): einmal Tab drücken → Direkt zum Inhalt. */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-[100] focus:rounded-lg focus:bg-orange-600 focus:px-4 focus:py-2 focus:text-white focus:text-sm focus:font-medium focus:shadow-lg"
      >
        {t('navigation.skipToContent')}
      </a>
      {/* Compact Header */}
      {isSidebarCompact && (
        <header className="fixed top-0 left-0 right-0 z-40 h-14 bg-bambu-dark-secondary border-b border-bambu-dark-tertiary flex items-center px-4">
          <button
            onClick={() => setMobileDrawerOpen(true)}
            className="p-2 -ml-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors"
            aria-label="Open menu"
          >
            <Menu className="w-6 h-6 text-white" />
          </button>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex items-center ml-2 group"
            title="PrintLab"
            aria-label="PrintLab"
          >
            <img
              src={resolvedMode === 'dark' ? '/img/printlab_dark.png' : '/img/printlab_light.png'}
              alt="PrintLab"
              className="h-7 w-auto transition-opacity group-hover:opacity-90"
            />
          </button>
          <div className="ml-auto flex items-center gap-1">
            <button
              onClick={() => window.dispatchEvent(new CustomEvent('open-command-palette'))}
              className="p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray hover:text-white"
              title={t('commandPalette.title', { defaultValue: 'Schnellsuche' })}
              aria-label={t('commandPalette.title', { defaultValue: 'Schnellsuche' })}
            >
              <Search className="w-5 h-5" />
            </button>
            {/* Bug report — the compact-layout home of the floating bubble. */}
            {bugReportEnabled && (
            <button
              onClick={() => setBugReportOpen(true)}
              className={`p-2 -mr-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors ${
                bugReportLogging ? 'text-amber-500' : 'text-red-500'
              }`}
              title={bugReportLogging ? t('bugReport.resumeReport') : t('bugReport.title')}
              aria-label={bugReportLogging ? t('bugReport.resumeReport') : t('bugReport.title')}
            >
              <Bug className={`w-5 h-5 ${bugReportLogging ? 'animate-pulse' : ''}`} />
            </button>
            )}
          </div>
        </header>
      )}

      {/* Compact Drawer Backdrop */}
      {isSidebarCompact && mobileDrawerOpen && (
        <div
          className="fixed inset-0 bg-black/60 z-40 transition-opacity"
          onClick={() => setMobileDrawerOpen(false)}
        />
      )}

      {/* Sidebar / Mobile Drawer */}
      <aside
        className={`bg-bambu-dark-secondary border-r border-bambu-dark-tertiary flex flex-col transition-all duration-300 ${
          isSidebarCompact
            ? `fixed inset-y-0 left-0 z-50 w-72 transform ${mobileDrawerOpen ? 'translate-x-0' : '-translate-x-full'}`
            : `fixed inset-y-0 left-0 z-30 ${sidebarExpanded ? 'w-64' : 'w-16'}`
        }`}
      >
        {/* Logo */}
        <div className={`border-b border-bambu-dark-tertiary flex items-center ${isSidebarCompact || sidebarExpanded ? 'px-4 py-3 justify-between' : 'p-2 justify-center'}`}>
          <button
            type="button"
            onClick={() => navigate('/')}
            className="flex items-center gap-2 group transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-bambu-green rounded-lg"
            title="PrintLab"
            aria-label="PrintLab"
          >
            <img
              src={resolvedMode === 'dark' ? '/img/printlab_dark.png' : '/img/printlab_light.png'}
              alt="PrintLab"
              className={isSidebarCompact || sidebarExpanded ? 'h-9 w-auto max-w-[170px] object-contain' : 'h-8 w-8 object-contain'}
            />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-1 overflow-y-auto sidebar-scroll">
          <div className="space-y-1.5">
            {sidebarGroups.map((group) => {
              const isCollapsed = (isSidebarCompact || sidebarExpanded) ? collapsedGroups.includes(group.id) : false;
              const hasActiveChild = group.ids.some((id) => {
                if (isExternalSidebarItemId(id)) {
                  return location.pathname === `/external/${id.replace(/^ext-/, '')}`;
                }
                const item = navItemsMap.get(id);
                if (!item) return false;
                return item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to);
              });

              return (
                <div key={`group-${group.id}`} className="space-y-0.5">
                  {isSidebarCompact || sidebarExpanded ? (
                    <button
                      type="button"
                      onClick={() => toggleGroup(group.id)}
                      className="w-full flex items-center justify-between px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-bambu-gray/80 hover:text-white hover:bg-bambu-dark-tertiary/40 rounded transition-colors group/header select-none"
                      aria-expanded={!isCollapsed}
                      title={isCollapsed ? t('nav.expandGroup', { defaultValue: 'Gruppe aufklappen' }) : t('nav.collapseGroup', { defaultValue: 'Gruppe einklappen' })}
                    >
                      <span className="flex items-center gap-1.5 truncate">
                        <span>{t(group.labelKey, { defaultValue: group.defaultLabel })}</span>
                        {isCollapsed && hasActiveChild && (
                          <span
                            className="w-1.5 h-1.5 rounded-full bg-bambu-green flex-shrink-0"
                            title={t('nav.activeItemInGroup', { defaultValue: 'Aktive Seite in dieser Gruppe' })}
                          />
                        )}
                      </span>
                      <ChevronDown
                        className={`w-3.5 h-3.5 text-bambu-gray/60 group-hover/header:text-white transition-transform duration-200 flex-shrink-0 ${
                          isCollapsed ? '-rotate-90' : 'rotate-0'
                        }`}
                      />
                    </button>
                  ) : (
                    <div className="mx-2 my-2 border-t border-bambu-dark-tertiary" aria-hidden="true" />
                  )}

                  {!isCollapsed && (
                    <ul className="space-y-0.5">
                      {group.ids.map((id) => {
                        const isExternal = isExternalSidebarItemId(id);

                        if (isExternal) {
                          // Render external link
                          const link = extLinksMap.get(id);
                          if (!link) return null;

                          const LinkIcon = link.custom_icon ? null : getIconByName(link.icon);
                          return (
                            <li key={id}>
                              {link.open_in_new_tab ? (
                                <a
                                  href={link.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={`flex items-center ${isSidebarCompact || sidebarExpanded ? 'gap-2.5 px-3' : 'justify-center px-2'} py-1.5 rounded-lg transition-colors group text-bambu-gray-light hover:bg-bambu-dark-tertiary hover:text-white text-sm font-medium`}
                                  title={!isSidebarCompact && !sidebarExpanded ? link.name : undefined}
                                >
                                  {link.custom_icon ? (
                                    <img
                                      src={api.getExternalLinkIconUrl(link.id)}
                                      alt=""
                                      className="w-5 h-5 flex-shrink-0"
                                    />
                                  ) : (
                                    LinkIcon && <LinkIcon className="w-5 h-5 flex-shrink-0" />
                                  )}
                                  {(isSidebarCompact || sidebarExpanded) && <span className="truncate">{link.name}</span>}
                                </a>
                              ) : (
                                <NavLink
                                  to={`/external/${link.id}`}
                                  className={({ isActive }) =>
                                    `flex items-center ${isSidebarCompact || sidebarExpanded ? 'gap-2.5 px-3' : 'justify-center px-2'} py-1.5 rounded-lg transition-colors group text-sm font-medium ${
                                      isActive
                                        ? 'bg-bambu-green text-white font-semibold'
                                        : 'text-bambu-gray-light hover:bg-bambu-dark-tertiary hover:text-white'
                                    }`
                                  }
                                  title={!isSidebarCompact && !sidebarExpanded ? link.name : undefined}
                                >
                                  {link.custom_icon ? (
                                    <img
                                      src={api.getExternalLinkIconUrl(link.id)}
                                      alt=""
                                      className="w-5 h-5 flex-shrink-0"
                                    />
                                  ) : (
                                    LinkIcon && <LinkIcon className="w-5 h-5 flex-shrink-0" />
                                  )}
                                  {(isSidebarCompact || sidebarExpanded) && <span className="truncate">{link.name}</span>}
                                </NavLink>
                              )}
                            </li>
                          );
                        } else {
                          // Render internal nav item
                          const navItem = navItemsMap.get(id);
                          if (!navItem) return null;

                          const { to, icon: Icon, labelKey } = navItem;
                          const showQueueBadge = id === 'queue' && pendingQueueCount > 0;
                          const showArchiveBadge = id === 'archives' && pendingUploadsCount > 0;
                          const badgeCount = showQueueBadge ? pendingQueueCount : showArchiveBadge ? pendingUploadsCount : 0;
                          const showBadge = showQueueBadge || showArchiveBadge;
                          const showClearPlateDot = id === 'printers' && needsClearPlate;

                          return (
                            <li key={id}>
                              <NavLink
                                to={to}
                                className={({ isActive }) =>
                                  `flex items-center ${isSidebarCompact || sidebarExpanded ? 'gap-2.5 px-3' : 'justify-center px-2'} py-1.5 rounded-lg transition-colors group text-sm font-medium ${
                                    isActive
                                      ? 'bg-bambu-green text-white font-semibold'
                                      : 'text-bambu-gray-light hover:bg-bambu-dark-tertiary hover:text-white'
                                  }`
                                }
                                title={!isSidebarCompact && !sidebarExpanded ? t(labelKey) : undefined}
                              >
                                <div className="relative">
                                  <Icon className="w-5 h-5 flex-shrink-0" />
                                  {showClearPlateDot && (
                                    <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 bg-yellow-500 rounded-full border-2 border-bambu-dark-secondary" />
                                  )}
                                  {showBadge && (
                                    <span className={`absolute -top-1.5 -right-1.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center text-[10px] font-bold rounded-full ${
                                      showArchiveBadge ? 'bg-blue-500 text-white' : 'bg-yellow-500 text-black'
                                    }`}>
                                      {badgeCount > 99 ? '99+' : badgeCount}
                                    </span>
                                  )}
                                </div>
                                {(isSidebarCompact || sidebarExpanded) && <span className="truncate">{t(labelKey)}</span>}
                              </NavLink>
                            </li>
                          );
                        }
                      })}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </nav>

        {/* Collapse toggle - hide on compact sidebar */}
        {!isSidebarCompact && (
          <div className="px-2 pt-1 pb-1 border-t border-bambu-dark-tertiary/40">
            {sidebarExpanded ? (
              <button
                type="button"
                onClick={() => setSidebarExpanded(false)}
                className="w-full flex items-center justify-between px-3 py-1.5 rounded-lg text-xs font-medium text-bambu-gray hover:text-white hover:bg-bambu-dark-tertiary/60 transition-colors group"
                title={t('nav.collapseSidebar', { defaultValue: 'Seitenleiste einklappen' })}
                aria-label={t('nav.collapseSidebar', { defaultValue: 'Seitenleiste einklappen' })}
              >
                <span className="flex items-center gap-2">
                  <ChevronLeft className="w-4 h-4 text-bambu-gray transition-transform group-hover:-translate-x-0.5 group-hover:text-white" />
                  <span>{t('nav.collapseSidebar', { defaultValue: 'Seitenleiste einklappen' })}</span>
                </span>
                <span className="text-[10px] text-bambu-gray/50 font-mono hidden group-hover:inline">[</span>
              </button>
            ) : (
              <div className="flex justify-center">
                <button
                  type="button"
                  onClick={() => setSidebarExpanded(true)}
                  className="p-2 rounded-lg text-bambu-gray hover:text-white hover:bg-bambu-dark-tertiary/60 transition-colors group"
                  title={t('nav.expandSidebar', { defaultValue: 'Seitenleiste ausklappen' })}
                  aria-label={t('nav.expandSidebar', { defaultValue: 'Seitenleiste ausklappen' })}
                >
                  <ChevronRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5 group-hover:text-white" />
                </button>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex-shrink-0 p-2 border-t border-bambu-dark-tertiary bg-bambu-dark-secondary/60">
          {isSidebarCompact || sidebarExpanded ? (
            <div className="flex flex-col gap-1.5">
              {/* User session card if authenticated */}
              {authEnabled && user && (
                <div className="flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-bambu-dark-tertiary/30 border border-bambu-dark-tertiary/50">
                  <div className="flex items-center gap-2 min-w-0 pr-1">
                    <div className="w-5 h-5 rounded-full bg-bambu-green/20 text-bambu-green flex items-center justify-center text-[10px] font-bold uppercase flex-shrink-0">
                      {user.username.charAt(0)}
                    </div>
                    <span className="text-xs font-medium text-white truncate" title={user.username}>
                      {user.username}
                    </span>
                  </div>
                  <div className="flex items-center gap-0.5 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => setShowChangePasswordModal(true)}
                      className="p-1 rounded text-bambu-gray hover:text-white hover:bg-bambu-dark-tertiary transition-colors"
                      title={t('changePassword.title')}
                      aria-label={t('changePassword.title')}
                    >
                      <Key className="w-3.5 h-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={logout}
                      className="p-1 rounded text-bambu-gray hover:text-red-400 hover:bg-bambu-dark-tertiary transition-colors"
                      title={t('nav.logout', { defaultValue: 'Logout' })}
                      aria-label={t('nav.logout', { defaultValue: 'Logout' })}
                    >
                      <LogOut className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              )}

              {/* Utility icons row */}
              <div className="flex items-center justify-around py-0.5 text-bambu-gray-light [&>a]:p-1.5 [&>button]:p-1.5 [&>span]:p-1.5 [&>div>button]:p-1.5">
                {hasSwitchbarPlugs && (
                  <div className="relative">
                    <button
                      onMouseEnter={() => setShowSwitchbar(true)}
                      className={`rounded-lg hover:bg-bambu-dark-tertiary transition-colors ${
                        showSwitchbar ? 'text-bambu-green' : 'text-bambu-gray-light hover:text-white'
                      }`}
                      title={t('nav.smartSwitches', { defaultValue: 'Smart Switches' })}
                    >
                      <Plug className="w-4 h-4" />
                    </button>
                    {showSwitchbar && (
                      <SwitchbarPopover onClose={() => setShowSwitchbar(false)} />
                    )}
                  </div>
                )}
                {announcementsVisible && (
                  <button
                    onClick={() => openAnnouncements()}
                    className="relative rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                    title={t('announcements.title')}
                    aria-label={
                      unreadAnnouncements.length > 0
                        ? t('announcements.unread', { count: unreadAnnouncements.length })
                        : t('announcements.title')
                    }
                  >
                    <Megaphone className="w-4 h-4" />
                    {unreadAnnouncements.length > 0 && (
                      <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-3.5 px-0.5 flex items-center justify-center text-[9px] font-bold rounded-full bg-bambu-green text-white">
                        {unreadAnnouncements.length}
                      </span>
                    )}
                  </button>
                )}
                <InstallAppButton />
                <a
                  href="https://github.com/Luk1236/printlab"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                  title={t('nav.viewOnGithub')}
                >
                  <Github className="w-4 h-4" />
                </a>
                <button
                  onClick={() => setShowShortcuts(true)}
                  className="rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                  title={t('nav.keyboardShortcuts')}
                >
                  <Keyboard className="w-4 h-4" />
                </button>
                <button
                  onClick={toggleMode}
                  className="rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                  title={themeSwitchTitle}
                >
                  <ThemeIcon className="w-4 h-4" />
                </button>
              </div>

              {/* Version & Update row */}
              <div className="flex items-center justify-between px-2 pt-0.5 text-[11px] text-bambu-gray">
                <span className="font-mono text-bambu-gray/70">v{versionInfo?.version || '...'}</span>
                {updateCheck?.update_available && (
                  <button
                    onClick={() => navigate('/settings?tab=updates')}
                    className="flex items-center gap-1 px-1.5 py-0.5 rounded bg-bambu-green/10 text-bambu-green hover:bg-bambu-green/20 font-medium transition-colors"
                    title={t('nav.updateAvailable', { version: updateCheck.latest_version })}
                  >
                    <ArrowUpCircle className="w-3.5 h-3.5 animate-pulse" />
                    <span>{t('nav.update')}</span>
                  </button>
                )}
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-1 overflow-y-auto max-h-[50vh] sidebar-scroll">
              {updateCheck?.update_available && (
                <button
                  onClick={() => navigate('/settings?tab=updates')}
                  className="p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-green hover:text-bambu-green/80"
                  title={t('nav.updateAvailable', { version: updateCheck.latest_version })}
                >
                  <ArrowUpCircle className="w-5 h-5 animate-pulse" />
                </button>
              )}
              {hasSwitchbarPlugs && (
                <div className="relative">
                  <button
                    onMouseEnter={() => setShowSwitchbar(true)}
                    className={`p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors ${
                      showSwitchbar ? 'text-bambu-green' : 'text-bambu-gray-light hover:text-white'
                    }`}
                    title={t('nav.smartSwitches', { defaultValue: 'Smart Switches' })}
                  >
                    <Plug className="w-5 h-5" />
                  </button>
                  {showSwitchbar && (
                    <SwitchbarPopover onClose={() => setShowSwitchbar(false)} />
                  )}
                </div>
              )}
              {announcementsVisible && (
                <button
                  onClick={() => openAnnouncements()}
                  className="relative p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                  title={t('announcements.title')}
                  aria-label={
                    unreadAnnouncements.length > 0
                      ? t('announcements.unread', { count: unreadAnnouncements.length })
                      : t('announcements.title')
                  }
                >
                  <Megaphone className="w-5 h-5" />
                  {unreadAnnouncements.length > 0 && (
                    <span className="absolute top-1 right-1 w-2.5 h-2.5 rounded-full bg-bambu-green ring-2 ring-bambu-dark-secondary" />
                  )}
                </button>
              )}
              <InstallAppButton />
              <a
                href="https://github.com/Luk1236/printlab"
                target="_blank"
                rel="noopener noreferrer"
                className="p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                title={t('nav.viewOnGithub')}
              >
                <Github className="w-5 h-5" />
              </a>
              <button
                onClick={() => setShowShortcuts(true)}
                className="p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                title={t('nav.keyboardShortcuts')}
              >
                <Keyboard className="w-5 h-5" />
              </button>
              <button
                onClick={toggleMode}
                className="p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                title={themeSwitchTitle}
              >
                <ThemeIcon className="w-5 h-5" />
              </button>
              {authEnabled && user && (
                <>
                  <button
                    onClick={() => setShowChangePasswordModal(true)}
                    className="p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                    title={t('changePassword.title')}
                  >
                    <Key className="w-5 h-5" />
                  </button>
                  <button
                    onClick={logout}
                    className="p-2 rounded-lg hover:bg-bambu-dark-tertiary transition-colors text-bambu-gray-light hover:text-white"
                    title={t('nav.logout', { defaultValue: 'Logout' })}
                  >
                    <LogOut className="w-5 h-5" />
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      </aside>

      {/* Main content — Tab-Ziel des Skip-Links */}
      <main id="main-content" tabIndex={-1} className={`flex-1 bg-bambu-dark overflow-auto transition-all duration-300 ${
        isSidebarCompact ? 'mt-14' : sidebarExpanded ? 'ml-64' : 'ml-16'
      }`}>
        {/* Debug logging indicator */}
        {debugLoggingState?.enabled && (
          <div className="bg-amber-100 dark:bg-amber-500/20 border-b border-amber-300 dark:border-amber-500/30 px-4 py-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              <Bug className="w-4 h-4 text-amber-500 animate-pulse" />
              <span className="text-amber-800 dark:text-amber-200">
                {t('support.debugLoggingActive', { defaultValue: 'Debug logging is active' })}
                {debugDuration !== null && (
                  <span className="text-amber-700/80 dark:text-amber-300/70 ml-2">
                    ({Math.floor(debugDuration / 60)}m {debugDuration % 60}s)
                  </span>
                )}
              </span>
              {/* A run started from the bug-report panel ends at that panel's
                  Stop & Submit button, so send the user back there rather than
                  to the System page's raw toggle, which would drop the logs
                  and the description they already wrote (#2847). */}
              {bugReportLogging && (
                <button
                  onClick={() => setBugReportOpen(true)}
                  className="text-amber-700 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-300 font-medium underline ml-2"
                >
                  {t('bugReport.resumeReport')}
                </button>
              )}
              <button
                onClick={() => navigate('/settings?tab=system')}
                className="text-amber-700 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-300 font-medium underline ml-2"
              >
                {t('support.manageLogs', { defaultValue: 'Manage' })}
              </button>
            </div>
          </div>
        )}
        {devModeWarnings && devModeWarnings.length > 0 && (
          <div className="bg-orange-100 dark:bg-orange-500/20 border-b border-orange-300 dark:border-orange-500/30 px-4 py-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              <ShieldAlert className="w-4 h-4 text-orange-500" />
              <span className="text-orange-800 dark:text-orange-200">
                {t('printers.developerModeWarning', {
                  names: devModeWarnings.map(w => w.name).join(', '),
                  defaultValue: `Developer LAN mode is not enabled on: ${devModeWarnings.map(w => w.name).join(', ')}. Some features may not work.`
                })}
              </span>
              <a href="https://wiki.bambulab.com/en/knowledge-sharing/enable-developer-mode"
                 target="_blank" rel="noopener noreferrer"
                 className="text-orange-700 dark:text-orange-400 hover:text-orange-900 dark:hover:text-orange-300 font-medium underline ml-2">
                {t('printers.howToEnable', { defaultValue: 'How to enable' })}
              </a>
            </div>
          </div>
        )}
        {slicerDown && (
          <div className="bg-amber-100 dark:bg-amber-500/20 border-b border-amber-300 dark:border-amber-500/30 px-4 py-2 flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-sm min-w-0">
              <ShieldAlert className="w-4 h-4 text-amber-500 shrink-0" />
              <span className="text-amber-800 dark:text-amber-200 truncate">
                {t('slicerBanner.unreachable', {
                  url: slicerStatus?.url ?? '',
                  defaultValue:
                    'The slicer is unreachable ({{url}}). Slicing is unavailable until the sidecar answers again.',
                })}
              </span>
              <button
                onClick={() => navigate('/settings')}
                className="text-amber-700 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-300 font-medium underline shrink-0"
              >
                {t('slicerBanner.openSettings', { defaultValue: 'Slicer settings' })}
              </button>
            </div>
          </div>
        )}
        <AnnouncementBanner items={bannerItems} onOpen={openAnnouncements} markRead={markAnnouncementRead} />
        {/* Persistent update banner */}
        {showUpdateBanner && (
          <div className="bg-bambu-green/20 border-b border-bambu-green/30 px-4 py-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm">
              <ArrowUpCircle className="w-4 h-4 text-bambu-green" />
              <span>
                {t('nav.updateAvailableBanner', {
                  version: updateCheck?.latest_version,
                  defaultValue: `Version ${updateCheck?.latest_version} is available!`
                })}
              </span>
              <button
                onClick={() => navigate('/settings')}
                className="text-bambu-green hover:text-bambu-green/80 font-medium underline"
              >
                {t('nav.viewUpdate', { defaultValue: 'View update' })}
              </button>
            </div>
            <button
              onClick={dismissUpdateBanner}
              className="p-1 hover:bg-bambu-dark-tertiary rounded transition-colors"
              title={t('common.dismiss', { defaultValue: 'Dismiss' })}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        )}
        <Suspense fallback={<PageLoading />}>
          <Outlet />
        </Suspense>
      </main>
      <AnnouncementsPanel
        open={announcementsOpen}
        onClose={closeAnnouncements}
        announcements={announcements}
        markRead={markAnnouncementRead}
        focusId={announcementFocus}
      />

      <UnknownSpoolModal
        prompt={unknownSpool.prompt}
        isPending={unknownSpool.isPending}
        onConfirm={unknownSpool.confirm}
        onCancel={unknownSpool.cancel}
      />

      {/* Keyboard Shortcuts Modal */}
      {showShortcuts && (
        <KeyboardShortcutsModal
          onClose={() => setShowShortcuts(false)}
          sidebarItems={orderedSidebarIds.map(id => {
            if (isExternalSidebarItemId(id)) {
              const extLink = extLinksMap.get(id);
              return extLink ? { type: 'external' as const, label: extLink.name } : null;
            } else {
              const navItem = navItemsMap.get(id);
              return navItem ? { type: 'nav' as const, label: navItem.labelKey, labelKey: navItem.labelKey } : null;
            }
          }).filter(Boolean) as { type: 'nav' | 'external'; label: string; labelKey?: string }[]}
        />
      )}

      {/* Plate Detection Alert Modal */}
      {plateDetectionAlert && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-[100] p-4">
          <div className="bg-bambu-dark-secondary border-2 border-yellow-500 rounded-xl shadow-2xl max-w-md w-full animate-in fade-in zoom-in duration-200">
            <div className="p-6 text-center">
              <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-yellow-500/20 flex items-center justify-center">
                <svg className="w-10 h-10 text-yellow-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
              </div>
              <h2 className="text-xl font-bold text-yellow-700 dark:text-yellow-400 mb-2">
                {t('plateAlert.title')}
              </h2>
              <p className="text-lg text-white mb-2">
                {plateDetectionAlert.printer_name}
              </p>
              <p className="text-bambu-gray mb-6">
                {t('plateAlert.message')}
              </p>
              <button
                onClick={() => setPlateDetectionAlert(null)}
                className="w-full py-3 px-6 bg-yellow-500 hover:bg-yellow-600 text-black font-semibold rounded-lg transition-colors"
              >
                {t('plateAlert.understand')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Post-print outcome confirmation (#1898) */}
      {/* The dialog's only outcome for a user who may not record a verdict is
          a 403 from the PATCH, so it is gated on the permissions that route
          enforces — the names the June migration left in the default groups.
          Gated on the render rather than on the two ways a request arrives:
          one of them can land before /auth/me has answered, and a check made
          then would drop it for everybody. */}
      {canConfirmOutcome && confirmOutcomeArchiveId !== null && (
        <ConfirmOutcomeDialog
          archiveId={confirmOutcomeArchiveId}
          onClose={() => setConfirmOutcomeArchiveId(null)}
        />
      )}

      {/* Change Password Modal */}
      {showChangePasswordModal && (
        <div
          className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4"
          onClick={() => {
            setShowChangePasswordModal(false);
            setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
          }}
        >
          <Card
            className="w-full max-w-md"
            onClick={(e: React.MouseEvent) => e.stopPropagation()}
          >
            <CardHeader>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Key className="w-5 h-5 text-bambu-green" />
                  <h2 className="text-lg font-semibold text-white">{t('changePassword.title')}</h2>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowChangePasswordModal(false);
                    setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
                  }}
                >
                  <X className="w-5 h-5" />
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <input
                  type="text"
                  name="username"
                  autoComplete="username"
                  value={user?.username ?? ''}
                  readOnly
                  hidden
                  aria-hidden="true"
                  tabIndex={-1}
                />
                <div>
                  <label className="block text-sm font-medium text-white mb-2">
                    {t('changePassword.currentPassword')}
                  </label>
                  <input
                    type="password"
                    value={changePasswordData.currentPassword}
                    onChange={(e) => setChangePasswordData({ ...changePasswordData, currentPassword: e.target.value })}
                    className="w-full px-4 py-3 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors"
                    placeholder={t('changePassword.currentPasswordPlaceholder')}
                    autoComplete="current-password"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-white mb-2">
                    {t('changePassword.newPassword')}
                  </label>
                  <input
                    type="password"
                    value={changePasswordData.newPassword}
                    onChange={(e) => setChangePasswordData({ ...changePasswordData, newPassword: e.target.value })}
                    className="w-full px-4 py-3 bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors"
                    placeholder={t('changePassword.newPasswordPlaceholder')}
                    autoComplete="new-password"
                    minLength={6}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-white mb-2">
                    {t('changePassword.confirmPassword')}
                  </label>
                  <input
                    type="password"
                    value={changePasswordData.confirmPassword}
                    onChange={(e) => setChangePasswordData({ ...changePasswordData, confirmPassword: e.target.value })}
                    className={`w-full px-4 py-3 bg-bambu-dark-secondary border rounded-lg text-white placeholder-bambu-gray focus:outline-none focus:ring-2 focus:ring-bambu-green/50 focus:border-bambu-green transition-colors ${
                      changePasswordData.confirmPassword && changePasswordData.newPassword !== changePasswordData.confirmPassword
                        ? 'border-red-500'
                        : 'border-bambu-dark-tertiary'
                    }`}
                    placeholder={t('changePassword.confirmPasswordPlaceholder')}
                    autoComplete="new-password"
                    minLength={6}
                  />
                  {changePasswordData.confirmPassword && changePasswordData.newPassword !== changePasswordData.confirmPassword && (
                    <p className="text-red-700 dark:text-red-400 text-xs mt-1">{t('changePassword.passwordsDoNotMatch')}</p>
                  )}
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowChangePasswordModal(false);
                    setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
                  }}
                >
                  {t('common.cancel')}
                </Button>
                <Button
                  onClick={async () => {
                    if (changePasswordData.newPassword !== changePasswordData.confirmPassword) {
                      showToast(t('changePassword.passwordsDoNotMatch'), 'error');
                      return;
                    }
                    if (changePasswordData.newPassword.length < 6) {
                      showToast(t('changePassword.passwordTooShort'), 'error');
                      return;
                    }
                    setChangePasswordLoading(true);
                    try {
                      await api.changePassword(changePasswordData.currentPassword, changePasswordData.newPassword);
                      showToast(t('changePassword.success'), 'success');
                      setShowChangePasswordModal(false);
                      setChangePasswordData({ currentPassword: '', newPassword: '', confirmPassword: '' });
                    } catch (error: unknown) {
                      const message = error instanceof Error ? error.message : t('changePassword.failed');
                      showToast(message, 'error');
                    } finally {
                      setChangePasswordLoading(false);
                    }
                  }}
                  disabled={changePasswordLoading || !changePasswordData.currentPassword || !changePasswordData.newPassword || changePasswordData.newPassword !== changePasswordData.confirmPassword || changePasswordData.newPassword.length < 6}
                >
                  {changePasswordLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      {t('changePassword.changing')}
                    </>
                  ) : (
                    <>
                      <Key className="w-4 h-4" />
                      {t('changePassword.title')}
                    </>
                  )}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
      {/* The panel always mounts here, at the Layout root. It must not move
          into the header alongside its compact-layout trigger: the header is
          `fixed z-40` and so its own stacking context, which would cap the
          z-50 panel at the header's level and bury it under every ordinary
          modal in the app. */}
      {bugReportEnabled && <BugReportBubble
        showTrigger={!isSidebarCompact}
        open={bugReportOpen}
        onOpenChange={setBugReportOpen}
        onLoggingChange={setBugReportLogging}
      />}
      {/* Am Wurzelknoten wie der Fehlerbericht: eigene Palette über allen Seiten, Strg+K/⌘K öffnet sie. */}
      <CommandPalette />
    </div>
  );
}

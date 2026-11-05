import React, { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Sliders,
  Compass,
  Activity,
  ArrowUpCircle,
  Database,
  Plug,
  Gauge,
  Printer,
  Scale,
  ListOrdered,
  Cylinder,
  ScanEye,
  Wifi,
  Bell,
  Key,
  Users,
  Search,
  X,
  type LucideIcon,
} from 'lucide-react';

export type SettingsTabType =
  | 'general'
  | 'setup'
  | 'system'
  | 'updates'
  | 'plugs'
  | 'sensors'
  | 'virtual-printer'
  | 'spoolbuddy'
  | 'queue'
  | 'filament'
  | 'failure-detection'
  | 'network'
  | 'notifications'
  | 'apikeys'
  | 'users'
  | 'backup';

export interface SettingsNavRailProps {
  activeTab: SettingsTabType;
  onTabChange: (tab: SettingsTabType) => void;
  smartPlugsCount?: number;
  sensorsCount?: number;
  notificationsCount?: number;
  apiKeysCount?: number;
  spoolbuddyDeviceCount?: number;
  mqttEnabled?: boolean;
  virtualPrinterRunning?: boolean;
  spoolbuddyAnyOnline?: boolean;
  obicoActive?: boolean;
  authEnabled?: boolean;
  backupConfigured?: boolean;
  updateAvailable?: boolean;
}

interface NavItem {
  id: SettingsTabType;
  labelKey: string;
  defaultLabel: string;
  icon: LucideIcon;
  badge?: React.ReactNode;
}

interface NavCategory {
  id: string;
  labelKey: string;
  defaultLabel: string;
  items: NavItem[];
}

export function SettingsNavRail({
  activeTab,
  onTabChange,
  smartPlugsCount = 0,
  sensorsCount = 0,
  notificationsCount = 0,
  apiKeysCount = 0,
  spoolbuddyDeviceCount = 0,
  mqttEnabled = false,
  virtualPrinterRunning = false,
  spoolbuddyAnyOnline = false,
  obicoActive = false,
  authEnabled = false,
  backupConfigured = false,
  updateAvailable = false,
}: SettingsNavRailProps) {
  const { t } = useTranslation();
  const [filterQuery, setFilterQuery] = useState('');

  const categories: NavCategory[] = useMemo(
    () => [
      {
        id: 'system',
        labelKey: 'settings.categories.system',
        defaultLabel: 'System & Allgemein',
        items: [
          {
            id: 'general',
            labelKey: 'settings.tabs.general',
            defaultLabel: 'Allgemein',
            icon: Sliders,
          },
          {
            id: 'setup',
            labelKey: 'settings.tabs.setup',
            defaultLabel: 'Einrichtung & Assistent',
            icon: Compass,
          },
          {
            id: 'system',
            labelKey: 'settings.tabs.system',
            defaultLabel: 'Systemzustand & Diagnose',
            icon: Activity,
          },
          {
            id: 'updates',
            labelKey: 'settings.tabs.updates',
            defaultLabel: 'Updates & Version',
            icon: ArrowUpCircle,
            badge: updateAvailable ? (
              <span className="text-[10px] font-bold uppercase tracking-wider bg-amber-500/20 text-amber-500 dark:text-amber-400 px-1.5 py-0.5 rounded-full shrink-0 animate-pulse">
                {t('common.new', 'Neu')}
              </span>
            ) : null,
          },
          {
            id: 'backup',
            labelKey: 'settings.tabs.backup',
            defaultLabel: 'Datensicherung & Speicher',
            icon: Database,
            badge: (
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${backupConfigured ? 'bg-green-400' : 'bg-gray-500'}`}
                title={backupConfigured ? 'Backup aktiv' : 'Kein Backup eingerichtet'}
              />
            ),
          },
        ],
      },
      {
        id: 'hardware',
        labelKey: 'settings.categories.hardware',
        defaultLabel: 'Geräte & Hardware',
        items: [
          {
            id: 'plugs',
            labelKey: 'settings.tabs.smartPlugs',
            defaultLabel: 'Smart Plugs',
            icon: Plug,
            badge:
              smartPlugsCount > 0 ? (
                <span className="text-xs bg-bambu-dark-tertiary px-1.5 py-0.5 rounded-full shrink-0 text-bambu-gray">
                  {smartPlugsCount}
                </span>
              ) : null,
          },
          {
            id: 'sensors',
            labelKey: 'settings.tabs.sensors',
            defaultLabel: 'Sensoren',
            icon: Gauge,
            badge:
              sensorsCount > 0 ? (
                <span className="text-xs bg-bambu-dark-tertiary px-1.5 py-0.5 rounded-full shrink-0 text-bambu-gray">
                  {sensorsCount}
                </span>
              ) : null,
          },
          {
            id: 'spoolbuddy',
            labelKey: 'settings.tabs.spoolbuddy',
            defaultLabel: 'PrintLab Spool',
            icon: Scale,
            badge: (
              <span className="flex items-center gap-1.5 shrink-0">
                {spoolbuddyDeviceCount > 0 && (
                  <span className="text-xs bg-bambu-dark-tertiary px-1.5 py-0.5 rounded-full text-bambu-gray">
                    {spoolbuddyDeviceCount}
                  </span>
                )}
                <span
                  className={`w-2 h-2 rounded-full ${spoolbuddyAnyOnline ? 'bg-green-400' : 'bg-gray-500'}`}
                />
              </span>
            ),
          },
          {
            id: 'virtual-printer',
            labelKey: 'settings.tabs.virtualPrinter',
            defaultLabel: 'Virtueller Drucker',
            icon: Printer,
            badge: (
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${virtualPrinterRunning ? 'bg-green-400' : 'bg-gray-500'}`}
              />
            ),
          },
        ],
      },
      {
        id: 'workflow',
        labelKey: 'settings.categories.workflow',
        defaultLabel: 'Workflow & Druck',
        items: [
          {
            id: 'queue',
            labelKey: 'settings.tabs.queue',
            defaultLabel: 'Workflow',
            icon: ListOrdered,
          },
          {
            id: 'filament',
            labelKey: 'settings.tabs.filament',
            defaultLabel: 'Filament',
            icon: Cylinder,
          },
          {
            id: 'failure-detection',
            labelKey: 'settings.tabs.failureDetection',
            defaultLabel: 'Fehlererkennung',
            icon: ScanEye,
            badge: (
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${obicoActive ? 'bg-green-400' : 'bg-gray-500'}`}
              />
            ),
          },
        ],
      },
      {
        id: 'network',
        labelKey: 'settings.categories.network',
        defaultLabel: 'Netzwerk & Schnittstellen',
        items: [
          {
            id: 'network',
            labelKey: 'settings.tabs.network',
            defaultLabel: 'Netzwerk',
            icon: Wifi,
            badge: (
              <span
                className={`w-2 h-2 rounded-full shrink-0 ${mqttEnabled ? 'bg-green-400' : 'bg-gray-500'}`}
              />
            ),
          },
          {
            id: 'notifications',
            labelKey: 'settings.tabs.notifications',
            defaultLabel: 'Benachrichtigungen',
            icon: Bell,
            badge:
              notificationsCount > 0 ? (
                <span className="text-xs bg-bambu-dark-tertiary px-1.5 py-0.5 rounded-full shrink-0 text-bambu-gray">
                  {notificationsCount}
                </span>
              ) : null,
          },
          {
            id: 'apikeys',
            labelKey: 'settings.tabs.apiKeys',
            defaultLabel: 'API-Schlüssel',
            icon: Key,
            badge:
              apiKeysCount > 0 ? (
                <span className="text-xs bg-bambu-dark-tertiary px-1.5 py-0.5 rounded-full shrink-0 text-bambu-gray">
                  {apiKeysCount}
                </span>
              ) : null,
          },
        ],
      },
      {
        id: 'security',
        labelKey: 'settings.categories.security',
        defaultLabel: 'Sicherheit & Zugriff',
        items: [
          {
            id: 'users',
            labelKey: 'settings.tabs.users',
            defaultLabel: 'Authentifizierung',
            icon: Users,
            badge: authEnabled ? (
              <span className="w-2 h-2 rounded-full shrink-0 bg-green-400" />
            ) : null,
          },
        ],
      },
    ],
    [
      smartPlugsCount,
      sensorsCount,
      notificationsCount,
      apiKeysCount,
      spoolbuddyDeviceCount,
      mqttEnabled,
      virtualPrinterRunning,
      spoolbuddyAnyOnline,
      obicoActive,
      authEnabled,
      backupConfigured,
      updateAvailable,
      t,
    ]
  );

  const filteredCategories = useMemo(() => {
    if (!filterQuery.trim()) return categories;
    const query = filterQuery.toLowerCase().trim();
    return categories
      .map((cat) => {
        const catLabel = t(cat.labelKey, cat.defaultLabel).toLowerCase();
        const matchesCategory = catLabel.includes(query);
        const matchingItems = cat.items.filter((item) => {
          const itemLabel = t(item.labelKey, item.defaultLabel).toLowerCase();
          return itemLabel.includes(query) || matchesCategory;
        });
        return {
          ...cat,
          items: matchingItems,
        };
      })
      .filter((cat) => cat.items.length > 0);
  }, [categories, filterQuery, t]);

  return (
    <nav className="flex flex-wrap gap-1 border-b border-bambu-dark-tertiary pb-3 lg:pb-0 lg:flex-col lg:flex-nowrap lg:gap-3 lg:border-b-0 lg:border-r lg:w-64 lg:flex-shrink-0 lg:self-start lg:sticky lg:top-4 lg:pr-3">
      {/* Quick Search in Rail */}
      <div className="w-full relative mb-1 lg:mb-2">
        <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-bambu-gray pointer-events-none" />
        <input
          type="text"
          value={filterQuery}
          onChange={(e) => setFilterQuery(e.target.value)}
          placeholder={t('settings.searchPlaceholder', 'Menü filtern...')}
          className="w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-md pl-8 pr-7 py-1 text-xs text-white placeholder-bambu-gray/60 focus:outline-none focus:border-bambu-green transition-colors"
        />
        {filterQuery && (
          <button
            onClick={() => setFilterQuery('')}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-bambu-gray hover:text-white"
            aria-label="Filter leeren"
          >
            <X className="w-3 h-3" />
          </button>
        )}
      </div>

      {filteredCategories.map((cat) => (
        <div key={cat.id} className="flex flex-wrap gap-1 lg:flex-col lg:flex-nowrap lg:gap-0.5 lg:w-full">
          <div className="hidden lg:flex px-2.5 py-1 text-[11px] font-semibold text-bambu-gray/70 uppercase tracking-wider items-center justify-between">
            <span>{t(cat.labelKey, cat.defaultLabel)}</span>
          </div>
          {cat.items.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => onTabChange(item.id)}
                className={`px-3 py-1.5 text-xs lg:px-2.5 lg:py-2 lg:text-sm font-medium rounded-lg transition-all flex items-center gap-2 lg:gap-2.5 group ${
                  isActive
                    ? 'bg-bambu-green/15 text-bambu-green font-semibold border border-bambu-green/40 lg:border-transparent lg:shadow-sm'
                    : 'bg-bambu-dark lg:bg-transparent text-bambu-gray border border-bambu-dark-tertiary lg:border-transparent hover:text-gray-900 dark:hover:text-white hover:bg-bambu-dark-secondary/60'
                }`}
              >
                <Icon
                  className={`w-3.5 h-3.5 lg:w-4 lg:h-4 shrink-0 transition-colors ${
                    isActive ? 'text-bambu-green' : 'text-bambu-gray group-hover:text-white'
                  }`}
                />
                {t(item.labelKey, item.defaultLabel)}
                {item.badge && <span className="ml-auto pl-1.5">{item.badge}</span>}
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

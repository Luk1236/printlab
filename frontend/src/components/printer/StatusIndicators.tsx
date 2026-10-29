/**
 * Kleine Anzeige-Bausteine der Druckerkarte.
 *
 * Aus pages/PrintersPage.tsx ausgelagert: K-Wert-Zeile, Düsen-/Einlass-
 * Abzeichen, Wasser- und Thermometer-Symbole, Feuchte- und Temperaturanzeige
 * sowie die beiden Umschalter. Alle Bausteine sind rein darstellend und hängen
 * nur an Übersetzung, Theme und den AMS-Hilfswerten.
 */

import type { FC } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, Repeat } from 'lucide-react';

import { useTheme } from '../../contexts/ThemeContext';
import { FTS_INLET_SIDE } from '../../utils/amsHelpers';
import { formatKValue } from '../../utils/kValue';

// K-profile value shown on the slot card itself (#2532) rather than only inside
// the hover popup, the way BambuStudio shows it per slot.
//
// `k` arrives already gated on the slot being loaded; falsy means the printer
// never reported a calibration for it. formatKValue() substitutes 0.020 for a
// missing value, which is captioned inside the hover card but would read as a
// real measurement on this permanent, uncaptioned line -- so an uncalibrated
// slot gets no value at all. A ternary rather than `k && <div/>`: a firmware-
// reported 0 makes that expression evaluate to the number 0, and React renders
// numbers, putting a bare "0" under the material name.
//
// `reserve` holds the row's height open on the slots without a value whenever
// some other slot on the same card has one, so every fill bar stays on one line.
function KValueLine({ k, reserve }: { k: number | null | undefined; reserve: boolean }) {
  const { t } = useTranslation();
  const className = 'text-[length:var(--pc-t8,8px)] text-bambu-gray tabular-nums leading-none truncate';
  if (!k) {
    return reserve ? <div className={className} aria-hidden="true">&nbsp;</div> : null;
  }
  // Short label, full localized name on the title: "K Factor" / "K-Faktor" /
  // "Facteur K" clipped the value itself below ~70px, and the slot grid floor is
  // 3.5rem. tabular-nums rather than font-mono, which resolved to a different
  // family per browser and so measured differently in Safari.
  return (
    <div className={className} title={t('ams.kFactor')}>
      {t('ams.kFactorShort')} {formatKValue(k)}
    </div>
  );
}

// Nozzle side indicators (Bambu Lab style - square badge with L/R)
function NozzleBadge({ side }: { side: 'L' | 'R' }) {
  const { mode } = useTheme();
  const { t } = useTranslation();
  // Light mode: #e7f5e9 (light green), Dark mode: #1a4d2e (dark green)
  const bgColor = mode === 'dark' ? '#1a4d2e' : '#e7f5e9';
  return (
    <span
      className="inline-flex items-center justify-center w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)] text-[length:var(--pc-t10,10px)] font-bold rounded"
      style={{ backgroundColor: bgColor, color: '#00ae42' }}
      title={side === 'L' ? t('common.left') : t('common.right')}
    >
      {side}
    </span>
  );
}

// Filament Track Switch inlet indicator. Same L/R lettering as NozzleBadge but
// deliberately a different colour, because it means something different: this
// AMS is plumbed into one switch inlet and reaches BOTH nozzles through it.
function InletBadge({ inlet, title }: { inlet: 'A' | 'B'; title: string }) {
  const { mode } = useTheme();
  const bgColor = mode === 'dark' ? '#1e3a5f' : '#e3f0fb';
  return (
    <span
      className="inline-flex items-center justify-center w-[var(--pc-i4,1rem)] h-[var(--pc-i4,1rem)] text-[length:var(--pc-t10,10px)] font-bold rounded"
      style={{ backgroundColor: bgColor, color: '#3b82f6' }}
      title={title}
    >
      {FTS_INLET_SIDE[inlet]}
    </span>
  );
}

/**
 * Which side indicator, if any, belongs on an AMS card header.
 *
 * Three sources, in descending authority:
 *   1. A Filament Track Switch inlet binding — the AMS feeds both nozzles
 *      through the switch, so the inlet is the only meaningful label.
 *   2. A real extruder id from ams_extruder_map.
 *   3. The AMS unit id, as a last-resort guess for dual-nozzle printers that
 *      never reported a map. This one is only a guess, and it is suppressed
 *      when a switch is installed: with an FTS every unit reports extruder
 *      0xE, so the fallback would silently label AMS 0 "R" and AMS 1 "L" from
 *      nothing but their unit numbers.
 */

function WaterDropEmpty({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 36 54" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M17.8131 0.00538C18.4463 -0.15091 20.3648 3.14642 20.8264 3.84781C25.4187 10.816 35.3089 26.9368 35.9383 34.8694C37.4182 53.5822 11.882 61.3357 2.53721 45.3789C-1.73471 38.0791 0.016 32.2049 3.178 25.0232C6.99221 16.3662 12.6411 7.90372 17.8131 0.00538ZM18.3738 7.24807L17.5881 7.48441C14.4452 12.9431 10.917 18.2341 8.19369 23.9368C4.6808 31.29 1.18317 38.5479 7.69403 45.5657C17.3058 55.9228 34.9847 46.8808 31.4604 32.8681C29.2558 24.0969 22.4207 15.2913 18.3776 7.24807H18.3738Z" fill="#C3C2C1"/>
    </svg>
  );
}

// Water drop SVG - half filled with blue water (Bambu Lab style from bambu-humidity)
function WaterDropHalf({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 35 53" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M17.3165 0.0038C17.932 -0.14959 19.7971 3.08645 20.2458 3.77481C24.7103 10.6135 34.3251 26.4346 34.937 34.2198C36.3757 52.5848 11.5505 60.1942 2.46584 44.534C-1.68714 37.3735 0.0148 31.6085 3.08879 24.5603C6.79681 16.0605 12.2884 7.75907 17.3165 0.0038ZM17.8615 7.11561L17.0977 7.34755C14.0423 12.7048 10.6124 17.8974 7.96483 23.4941C4.54975 30.7107 1.14949 37.8337 7.47908 44.721C16.8233 54.8856 34.01 46.0117 30.5838 32.2595C28.4405 23.6512 21.7957 15.0093 17.8652 7.11561H17.8615Z" fill="#C3C2C1"/>
      <path d="M5.03547 30.112C9.64453 30.4936 11.632 35.7985 16.4154 35.791C19.6339 35.7873 20.2161 33.2283 22.3853 31.6197C31.6776 24.7286 33.5835 37.4894 27.9881 44.4254C18.1878 56.5653 -1.16063 44.6013 5.03917 30.1158L5.03547 30.112Z" fill="#1F8FEB"/>
    </svg>
  );
}

// Water drop SVG - fully filled with blue water (Bambu Lab style from bambu-humidity)
function WaterDropFull({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 36 54" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M17.9625 4.48059L4.77216 26.3154L2.08228 40.2175L10.0224 50.8414H23.1594L33.3246 42.1693V30.2455L17.9625 4.48059Z" fill="#1F8FEB"/>
      <path d="M17.7948 0.00538C18.4273 -0.15091 20.3438 3.14642 20.8048 3.84781C25.3921 10.816 35.2715 26.9368 35.9001 34.8694C37.3784 53.5822 11.8702 61.3357 2.53562 45.3789C-1.73163 38.0829 0.0134 32.2087 3.1757 25.027C6.98574 16.3662 12.6284 7.90372 17.7948 0.00538ZM18.3549 7.24807L17.57 7.48441C14.4306 12.9431 10.9063 18.2341 8.1859 23.9368C4.67686 31.29 1.18305 38.5479 7.68679 45.5657C17.2881 55.9228 34.9476 46.8808 31.4271 32.8681C29.2249 24.0969 22.3974 15.2913 18.3587 7.24807H18.3549Z" fill="#C3C2C1"/>
    </svg>
  );
}

// Thermometer SVG - empty outline
function ThermometerEmpty({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 12 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M6 0.5C4.6 0.5 3.5 1.6 3.5 3V12.1C2.6 12.8 2 13.9 2 15C2 17.2 3.8 19 6 19C8.2 19 10 17.2 10 15C10 13.9 9.4 12.8 8.5 12.1V3C8.5 1.6 7.4 0.5 6 0.5Z" stroke="#C3C2C1" strokeWidth="1" fill="none"/>
      <circle cx="6" cy="15" r="2.5" stroke="#C3C2C1" strokeWidth="1" fill="none"/>
    </svg>
  );
}

// Thermometer SVG - half filled (gold - same as humidity fair)
function ThermometerHalf({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 12 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="4.5" y="8" width="3" height="4.5" fill="#d4a017" rx="0.5"/>
      <circle cx="6" cy="15" r="2" fill="#d4a017"/>
      <path d="M6 0.5C4.6 0.5 3.5 1.6 3.5 3V12.1C2.6 12.8 2 13.9 2 15C2 17.2 3.8 19 6 19C8.2 19 10 17.2 10 15C10 13.9 9.4 12.8 8.5 12.1V3C8.5 1.6 7.4 0.5 6 0.5Z" stroke="#C3C2C1" strokeWidth="1" fill="none"/>
    </svg>
  );
}

// Thermometer SVG - fully filled (red - same as humidity bad)
function ThermometerFull({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 12 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <rect x="4.5" y="3" width="3" height="9.5" fill="#c62828" rx="0.5"/>
      <circle cx="6" cy="15" r="2" fill="#c62828"/>
      <path d="M6 0.5C4.6 0.5 3.5 1.6 3.5 3V12.1C2.6 12.8 2 13.9 2 15C2 17.2 3.8 19 6 19C8.2 19 10 17.2 10 15C10 13.9 9.4 12.8 8.5 12.1V3C8.5 1.6 7.4 0.5 6 0.5Z" stroke="#C3C2C1" strokeWidth="1" fill="none"/>
    </svg>
  );
}

// Nozzle icon - schematic hot-end view (filament body + heater block + tip).
// Added for visual parity with the thermometer icons on the dual-nozzle card
// that previously had no icon at all (#1115, design by @m4rtini2).
function NozzleIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="9.2" y="3.4" width="5.6" height="8.1" />
      <rect x="6" y="11.5" width="12.1" height="3.7" />
      <path d="M 7.3 15.2 L 12.1 19.6 L 16.7 15.2" />
    </svg>
  );
}

// Heater thermometer icon - filled when heating, outline when off
interface HeaterThermometerProps {
  className?: string;
  color: string;  // The color class (e.g., "text-orange-400")
  isHeating: boolean;
}

function HeaterThermometer({ className, color, isHeating }: HeaterThermometerProps) {
  // Extract the actual color from Tailwind class for SVG fill
  const colorMap: Record<string, string> = {
    'text-orange-400': '#fb923c',
    'text-blue-400': '#60a5fa',
    'text-green-400': '#4ade80',
  };
  const fillColor = colorMap[color] || '#888';

  // Glow style when heating
  const glowStyle = isHeating ? {
    filter: `drop-shadow(0 0 4px ${fillColor}) drop-shadow(0 0 8px ${fillColor})`,
  } : {};

  if (isHeating) {
    // Filled thermometer with glow - heater is ON
    return (
      <svg className={className} style={glowStyle} viewBox="0 0 12 20" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="4.5" y="3" width="3" height="9.5" fill={fillColor} rx="0.5"/>
        <circle cx="6" cy="15" r="2" fill={fillColor}/>
        <path d="M6 0.5C4.6 0.5 3.5 1.6 3.5 3V12.1C2.6 12.8 2 13.9 2 15C2 17.2 3.8 19 6 19C8.2 19 10 17.2 10 15C10 13.9 9.4 12.8 8.5 12.1V3C8.5 1.6 7.4 0.5 6 0.5Z" stroke={fillColor} strokeWidth="1" fill="none"/>
      </svg>
    );
  }

  // Empty thermometer - heater is OFF
  return (
    <svg className={className} viewBox="0 0 12 20" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path d="M6 0.5C4.6 0.5 3.5 1.6 3.5 3V12.1C2.6 12.8 2 13.9 2 15C2 17.2 3.8 19 6 19C8.2 19 10 17.2 10 15C10 13.9 9.4 12.8 8.5 12.1V3C8.5 1.6 7.4 0.5 6 0.5Z" stroke={fillColor} strokeWidth="1" fill="none"/>
      <circle cx="6" cy="15" r="2.5" stroke={fillColor} strokeWidth="1" fill="none"/>
    </svg>
  );
}

// AMS Filament Backup tri-state indicator + toggle.
// state=true  → ON, click to disable
// state=false → OFF, click opens modal
// state=null  → unknown/unsupported (e.g. A1 family), click disabled
interface AmsBackupBadgeProps {
  state: boolean | null;
  onClick: () => void;
}

function AmsBackupBadge({ state, onClick }: AmsBackupBadgeProps) {
  const { t } = useTranslation();
  const known = state !== null;

  let className = 'flex items-center justify-center w-[18px] h-[18px] rounded text-[length:var(--pc-t10,10px)] transition-colors ';
  let title: string;
  if (state === true) {
    className += known
      ? 'bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400 hover:bg-blue-500/30 cursor-pointer'
      : 'bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400 cursor-default';
    title = t('printers.amsBackup.titleOn');
  } else if (state === false) {
    className += known
      ? 'bg-bambu-dark text-bambu-gray hover:text-white hover:bg-bambu-dark/80 cursor-pointer'
      : 'bg-bambu-dark text-bambu-gray cursor-default';
    title = t('printers.amsBackup.titleOff');
  } else {
    className += 'bg-bambu-dark text-bambu-gray/50 cursor-default';
    title = t('printers.amsBackup.titleUnknown');
  }

  return (
    <button
      type="button"
      disabled={!known}
      onClick={() => known && onClick()}
      className={className}
      title={title}
      aria-label={title}
    >
      {known ? <Repeat className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)]" /> : <span>?</span>}
    </button>
  );
}

// Hide/show the external spool in the filament row (#1782). Sized and shaped
// like AmsBackupBadge so the two sit together in the section header, but
// pinned to the right-hand end of the rule: this is a view preference for the
// row, not a property of the printer.
interface ExternalSpoolToggleProps {
  hidden: boolean;
  onClick: () => void;
}

function ExternalSpoolToggle({ hidden, onClick }: ExternalSpoolToggleProps) {
  const { t } = useTranslation();
  const title = hidden ? t('printers.externalSpool.show') : t('printers.externalSpool.hide');

  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={hidden}
      className={`flex items-center justify-center w-[18px] h-[18px] rounded transition-colors cursor-pointer ${
        hidden
          ? 'bg-bambu-green/20 text-bambu-green hover:bg-bambu-green/30'
          : 'bg-bambu-dark text-bambu-gray hover:text-white hover:bg-bambu-dark/80'
      }`}
      title={title}
      aria-label={title}
    >
      {hidden ? <EyeOff className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)]" /> : <Eye className="w-[var(--pc-i3,0.75rem)] h-[var(--pc-i3,0.75rem)]" />}
    </button>
  );
}

// Humidity indicator with water drop that fills based on level (Bambu Lab style)
// Reference: https://github.com/theicedmango/bambu-humidity
interface HumidityIndicatorProps {
  humidity: number | string;
  goodThreshold?: number;  // <= this is green
  fairThreshold?: number;  // <= this is orange, > is red
  onClick?: () => void;
  compact?: boolean;  // Smaller version for grid layout
}

function HumidityIndicator({ humidity, goodThreshold = 40, fairThreshold = 60, onClick, compact }: HumidityIndicatorProps) {
  const humidityValue = typeof humidity === 'string' ? parseInt(humidity, 10) : humidity;
  const good = typeof goodThreshold === 'number' ? goodThreshold : 40;
  const fair = typeof fairThreshold === 'number' ? fairThreshold : 60;

  // Status thresholds (configurable via settings)
  // Good: ≤goodThreshold (green #22a352), Fair: ≤fairThreshold (gold #d4a017), Bad: >fairThreshold (red #c62828)
  let textColor: string;
  let statusText: string;

  if (isNaN(humidityValue)) {
    textColor = '#C3C2C1';
    statusText = 'Unknown';
  } else if (humidityValue <= good) {
    textColor = '#22a352'; // Green - Good
    statusText = 'Good';
  } else if (humidityValue <= fair) {
    textColor = '#d4a017'; // Gold - Fair
    statusText = 'Fair';
  } else {
    textColor = '#c62828'; // Red - Bad
    statusText = 'Bad';
  }

  // Fill level based on status: Good=Empty (dry), Fair=Half, Bad=Full (wet)
  let DropComponent: FC<{ className?: string }>;
  if (isNaN(humidityValue)) {
    DropComponent = WaterDropEmpty;
  } else if (humidityValue <= good) {
    DropComponent = WaterDropEmpty; // Good - empty drop (dry)
  } else if (humidityValue <= fair) {
    DropComponent = WaterDropHalf; // Fair - half filled
  } else {
    DropComponent = WaterDropFull; // Bad - full (too humid)
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1 ${onClick ? 'cursor-pointer hover:opacity-80 transition-opacity' : ''}`}
      title={`Humidity: ${humidityValue}% - ${statusText}${onClick ? ' (click for history)' : ''}`}
    >
      <DropComponent className={compact ? "w-2.5 h-3" : "w-3 h-4"} />
      <span className={`font-medium tabular-nums ${compact ? 'text-[length:var(--pc-t10,10px)]' : 'text-xs'}`} style={{ color: textColor }}>{humidityValue}%</span>
    </button>
  );
}

// Temperature indicator with dynamic icon and coloring
interface TemperatureIndicatorProps {
  temp: number;
  goodThreshold?: number;  // <= this is blue
  fairThreshold?: number;  // <= this is orange, > is red
  onClick?: () => void;
  compact?: boolean;  // Smaller version for grid layout
}

function TemperatureIndicator({ temp, goodThreshold = 28, fairThreshold = 35, onClick, compact }: TemperatureIndicatorProps) {
  // Ensure thresholds are numbers
  const good = typeof goodThreshold === 'number' ? goodThreshold : 28;
  const fair = typeof fairThreshold === 'number' ? fairThreshold : 35;

  let textColor: string;
  let statusText: string;
  let ThermoComponent: FC<{ className?: string }>;

  if (temp <= good) {
    textColor = '#22a352'; // Green - good (same as humidity)
    statusText = 'Good';
    ThermoComponent = ThermometerEmpty;
  } else if (temp <= fair) {
    textColor = '#d4a017'; // Gold - fair (same as humidity)
    statusText = 'Fair';
    ThermoComponent = ThermometerHalf;
  } else {
    textColor = '#c62828'; // Red - bad (same as humidity)
    statusText = 'Bad';
    ThermoComponent = ThermometerFull;
  }

  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-1 ${onClick ? 'cursor-pointer hover:opacity-80 transition-opacity' : ''}`}
      title={`Temperature: ${temp}°C - ${statusText}${onClick ? ' (click for history)' : ''}`}
    >
      <ThermoComponent className={compact ? "w-2.5 h-3" : "w-3 h-4"} />
      <span className={`tabular-nums text-right ${compact ? 'text-[length:var(--pc-t10,10px)] w-8' : 'w-12'}`} style={{ color: textColor }}>{temp}°C</span>
    </button>
  );
}

export {
  KValueLine,
  NozzleBadge,
  InletBadge,
  WaterDropEmpty,
  WaterDropHalf,
  WaterDropFull,
  ThermometerEmpty,
  ThermometerHalf,
  ThermometerFull,
  NozzleIcon,
  HeaterThermometer,
  AmsBackupBadge,
  ExternalSpoolToggle,
  HumidityIndicator,
  TemperatureIndicator,
};

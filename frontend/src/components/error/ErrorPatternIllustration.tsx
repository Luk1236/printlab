import type { ReactNode } from 'react';

/**
 * Schematische Fehlerbilder für die Fehlerhilfe.
 *
 * Bewusst Zeichnungen statt Fotos: keine Lizenzfragen, offline verfügbar und
 * auf hellem wie dunklem Hintergrund lesbar. Orange markiert die Stelle, an
 * der der Fehler sichtbar wird; Grau ist das Bauteil.
 */

const ACCENT = '#fa6831';
const BASE = '#9ca3af';
const BED = '#6b7280';

const drawings: Record<string, ReactNode> = {
  heat_creep: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <rect x="78" y="26" width="44" height="46" rx="4" stroke={BASE} strokeWidth="2.5" fill="none" />
      <path d="M100 8 v28" stroke={BASE} strokeWidth="2.5" strokeLinecap="round" />
      <ellipse cx="100" cy="44" rx="10" ry="7" fill={ACCENT} opacity="0.85" />
      <path d="M78 34 h-8 a8 8 0 0 1 -8 8 v12" stroke={ACCENT} strokeWidth="2" fill="none" />
      <path d="M44 40 h12 M44 52 h12 M44 64 h12" stroke={ACCENT} strokeWidth="2" strokeLinecap="round" />
      <path d="M60 34 l-6 6 6 6" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M132 30 q8 6 0 12 q8 6 0 12" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" />
    </>
  ),
  under_extrusion: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <path d="M46 86 h108 M46 70 h52 M112 70 h42 M46 54 h30 M92 54 h62 M46 38 h88 M150 38 h4" stroke={BASE} strokeWidth="7" strokeLinecap="round" opacity="0.75" />
      <path d="M96 70 h16 M76 54 h16 M134 38 h16" stroke={ACCENT} strokeWidth="7" strokeLinecap="round" />
    </>
  ),
  over_extrusion: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <path d="M52 90 v-58 a8 8 0 0 1 8 -8 h72 a8 8 0 0 1 8 8 v58" stroke={BASE} strokeWidth="2.5" fill="none" />
      <circle cx="145" cy="52" r="8" fill={ACCENT} opacity="0.8" />
      <circle cx="146" cy="74" r="6" fill={ACCENT} opacity="0.6" />
      <path d="M138 34 q10 4 2 10" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" />
      <path d="M120 44 q12 0 12 12" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" />
    </>
  ),
  stringing: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <rect x="46" y="34" width="24" height="66" rx="3" stroke={BASE} strokeWidth="2.5" fill="none" />
      <rect x="130" y="26" width="24" height="74" rx="3" stroke={BASE} strokeWidth="2.5" fill="none" />
      <path d="M70 40 C 90 46, 112 38, 130 44 M70 58 C 94 64, 108 54, 130 60 M70 78 C 92 84, 110 74, 130 80" stroke={ACCENT} strokeWidth="1.6" fill="none" />
      <circle cx="130" cy="44" r="2.4" fill={ACCENT} />
      <circle cx="70" cy="58" r="2.4" fill={ACCENT} />
    </>
  ),
  warping: (
    <>
      <line x1="20" y1="100" x2="180" y2="100" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <path d="M52 96 q6 -8 14 -2 v-46 h68 v46 q8 -6 14 2" stroke={BASE} strokeWidth="2.5" fill="none" strokeLinejoin="round" />
      <path d="M52 54 q6 -10 14 -4 h68 q8 -6 14 4" stroke={ACCENT} strokeWidth="2.5" fill="none" strokeLinecap="round" />
      <path d="M46 80 l-6 -10 M46 80 l8 -8 M154 80 l6 -10 M154 80 l-8 -8" stroke={ACCENT} strokeWidth="2" strokeLinecap="round" />
    </>
  ),
  curling: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <path d="M56 100 v-52 h44 c18 0 30 6 34 18" stroke={BASE} strokeWidth="2.5" fill="none" strokeLinejoin="round" />
      <path d="M134 66 c8 -10 20 -8 22 2 c2 10 -10 14 -16 6" stroke={ACCENT} strokeWidth="3" fill="none" strokeLinecap="round" />
      <path d="M120 46 q10 -6 20 0" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" />
    </>
  ),
  elephants_foot: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <path d="M56 100 h88 l-10 -12 h-68 z" fill={ACCENT} opacity="0.55" />
      <path d="M66 88 v-52 h68 v52" stroke={BASE} strokeWidth="2.5" fill="none" />
      <path d="M48 96 h-10 M58 86 l-8 -6 M152 96 h10 M142 86 l8 -6" stroke={ACCENT} strokeWidth="2" strokeLinecap="round" />
    </>
  ),
  delamination: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <rect x="62" y="82" width="76" height="10" rx="2" fill={BASE} opacity="0.55" />
      <rect x="62" y="68" width="76" height="10" rx="2" fill={BASE} opacity="0.55" />
      <rect x="62" y="54" width="76" height="10" rx="2" fill={BASE} opacity="0.55" />
      <path d="M62 46 h76" stroke={ACCENT} strokeWidth="4" strokeLinecap="round" />
      <rect x="62" y="26" width="76" height="12" rx="2" fill={BASE} opacity="0.55" />
      <path d="M84 46 l8 -6 -6 6 10 -4" stroke={ACCENT} strokeWidth="1.8" fill="none" />
    </>
  ),
  layer_shift: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <rect x="56" y="58" width="46" height="42" rx="2" stroke={BASE} strokeWidth="2.5" fill="none" />
      <rect x="76" y="18" width="46" height="36" rx="2" stroke={ACCENT} strokeWidth="2.5" fill="none" />
      <path d="M56 58 h46 M76 54 h46" stroke={BASE} strokeWidth="1.5" strokeDasharray="4 4" />
      <path d="M104 46 h24" stroke={ACCENT} strokeWidth="2" strokeLinecap="round" />
      <path d="M124 42 l8 4 -8 4" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
  ghosting: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <path d="M56 100 v-64 h36" stroke={BASE} strokeWidth="2.5" fill="none" strokeLinejoin="round" />
      <path d="M92 36 c6 0 6 8 0 8 M100 36 c8 0 8 12 0 12 M110 36 c10 0 10 18 0 18 M122 36 c12 0 12 24 0 24" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" />
    </>
  ),
  z_wobble: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <rect x="62" y="22" width="76" height="78" rx="2" stroke={BASE} strokeWidth="2.5" fill="none" />
      <path d="M62 36 h76 M62 48 h76 M62 60 h76 M62 72 h76 M62 84 h76" stroke={ACCENT} strokeWidth="2" opacity="0.85" />
    </>
  ),
  object_detached: (
    <>
      <line x1="20" y1="104" x2="180" y2="104" stroke={BED} strokeWidth="3" strokeLinecap="round" />
      <rect x="62" y="64" width="56" height="34" rx="3" stroke={BASE} strokeWidth="2.5" fill="none" />
      <rect x="96" y="52" width="56" height="34" rx="3" stroke={ACCENT} strokeWidth="2.5" fill="none" transform="rotate(8 124 69)" />
      <path d="M62 96 h56" stroke={BASE} strokeWidth="1.5" strokeDasharray="4 4" />
      <path d="M84 30 v12 M76 38 l8 8 8 -8" stroke={ACCENT} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
};

export function ErrorPatternIllustration({ patternId, className = 'w-full h-full' }: { patternId: string; className?: string }) {
  const drawing = drawings[patternId] ?? drawings.under_extrusion;
  return (
    <svg
      viewBox="0 0 200 120"
      className={className}
      role="img"
      aria-hidden="true"
      data-testid={`error-illustration-${patternId}`}
      preserveAspectRatio="xMidYMid meet"
    >
      {drawing}
    </svg>
  );
}

import { parsePresetName } from '../components/spool-form/utils';
import type { FilamentOption } from '../components/spool-form/types';

/** Was von einer Spule für die Zuordnung gebraucht wird. */
export interface MatchSpool {
  id: number;
  material: string;
  subtype: string | null;
  brand: string | null;
  slicer_filament: string | null;
}

/** exact: Marke, Material und Sorte passen; close: Marke und Material passen; generic: nur das Material (Generic-Profil). */
export type MatchKind = 'exact' | 'close' | 'generic';

export interface PresetMatch {
  spoolId: number;
  option: FilamentOption;
  kind: MatchKind;
}

export const SOURCE_PRIORITY: Record<string, number> = { local: 0, orca_cloud: 1, cloud: 2, builtin: 3 };

const norm = (value: string | null | undefined) =>
  (value ?? '')
    .toLowerCase()
    .replace(/\(custom\)/g, '')
    .replace(/[^a-z0-9+]+/g, ' ')
    .trim();

/** „Bambu Lab" und „Bambu" sind dieselbe Marke. */
const brandKey = (value: string | null | undefined) => norm(value).replace(/\blab\b/, '').trim();

const isBasic = (variant: string) => variant === '' || variant === 'basic';

/** Bewertet ein Profil für eine Spule: Art des Treffers oder null, wenn das Material nicht passt. */
export function kindOf(spool: MatchSpool, option: FilamentOption): MatchKind | null {
  const parsed = parsePresetName(option.name);
  if (norm(parsed.material) !== norm(spool.material)) return null;
  const optionBrand = brandKey(parsed.brand);
  const spoolBrand = brandKey(spool.brand);
  const spoolVariant = norm(spool.subtype);
  const optionVariant = norm(parsed.variant);

  if (optionBrand === 'generic') return spoolBrand === 'generic' ? 'exact' : 'generic';
  if (!optionBrand || !spoolBrand || optionBrand !== spoolBrand) return null;
  const sameVariant = spoolVariant === optionVariant || (isBasic(spoolVariant) && isBasic(optionVariant));
  return sameVariant ? 'exact' : 'close';
}

const RANK: Record<MatchKind, number> = { exact: 0, close: 1, generic: 2 };

/** Bei mehreren Varianten desselben Profils (@BBL X1C, @BBL P1S …) gewinnt die für ein vorhandenes Druckermodell. */
function modelRank(name: string, preferredModels: string[]): number {
  const at = name.indexOf('@');
  if (at === -1) return 1;
  const suffix = norm(name.slice(at + 1));
  return preferredModels.some((m) => m && suffix.split(' ').join('').includes(norm(m).split(' ').join(''))) ? 0 : 2;
}

/** Bestes Profil für eine Spule; Reihenfolge: Art des Treffers, Herkunft (lokal > Orca > Bambu > eingebaut), Druckermodell, Name. */
export function bestPreset(spool: MatchSpool, options: FilamentOption[], preferredModels: string[] = []): PresetMatch | null {
  let best: { option: FilamentOption; kind: MatchKind } | null = null;
  const better = (a: { option: FilamentOption; kind: MatchKind }, b: { option: FilamentOption; kind: MatchKind }) =>
    RANK[a.kind] - RANK[b.kind] ||
    (SOURCE_PRIORITY[a.option.source] ?? 9) - (SOURCE_PRIORITY[b.option.source] ?? 9) ||
    modelRank(a.option.name, preferredModels) - modelRank(b.option.name, preferredModels) ||
    a.option.name.localeCompare(b.option.name);
  for (const option of options) {
    const kind = kindOf(spool, option);
    if (!kind) continue;
    const candidate = { option, kind };
    if (!best || better(candidate, best) < 0) best = candidate;
  }
  return best ? { spoolId: spool.id, ...best } : null;
}

/** Vorschläge für alle Spulen ohne Profil (oder für alle, wenn `includeAssigned`), dazu die Spulen ohne Treffer. */
export function buildProposals(
  spools: MatchSpool[],
  options: FilamentOption[],
  preferredModels: string[] = [],
  includeAssigned = false,
) {
  const matches: PresetMatch[] = [];
  const unmatched: MatchSpool[] = [];
  for (const spool of spools) {
    if (!includeAssigned && spool.slicer_filament) continue;
    const match = bestPreset(spool, options, preferredModels);
    if (match) matches.push(match);
    else unmatched.push(spool);
  }
  return { matches, unmatched };
}

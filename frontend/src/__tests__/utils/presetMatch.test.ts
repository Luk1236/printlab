import { describe, it, expect } from 'vitest';
import { bestPreset, buildProposals, kindOf } from '../../utils/presetMatch';
import type { MatchSpool } from '../../utils/presetMatch';
import type { FilamentOption } from '../../components/spool-form/types';

const opt = (name: string, source: FilamentOption['source'] = 'cloud', code = name): FilamentOption => ({
  code,
  name,
  displayName: name,
  isCustom: false,
  allCodes: [code],
  source,
});
const spool = (over: Partial<MatchSpool> = {}): MatchSpool => ({
  id: 1,
  material: 'PLA',
  subtype: 'Basic',
  brand: 'Bambu Lab',
  slicer_filament: null,
  ...over,
});

describe('kindOf', () => {
  it('treats Bambu and Bambu Lab as the same brand and Basic as the default sort', () => {
    expect(kindOf(spool(), opt('Bambu PLA Basic @BBL X1C'))).toBe('exact');
    expect(kindOf(spool({ subtype: null }), opt('Bambu PLA Basic @BBL X1C'))).toBe('exact');
    expect(kindOf(spool({ subtype: 'Matte' }), opt('Bambu PLA Matte @BBL P1S'))).toBe('exact');
  });

  it('is close when brand and material match but the sort differs, and null for other materials or brands', () => {
    expect(kindOf(spool({ subtype: 'Silk' }), opt('Bambu PLA Basic'))).toBe('close');
    expect(kindOf(spool({ material: 'PETG' }), opt('Bambu PLA Basic'))).toBeNull();
    expect(kindOf(spool({ brand: 'Polymaker' }), opt('Bambu PLA Basic'))).toBeNull();
    expect(kindOf(spool({ brand: null }), opt('Bambu PLA Basic'))).toBeNull();
  });

  it('falls back to generic profiles by material only', () => {
    expect(kindOf(spool({ brand: 'Polymaker' }), opt('Generic PLA'))).toBe('generic');
    expect(kindOf(spool({ brand: null }), opt('Generic PLA'))).toBe('generic');
    expect(kindOf(spool({ brand: 'Generic' }), opt('Generic PLA'))).toBe('exact');
    expect(kindOf(spool({ material: 'PA-CF' }), opt('Bambu PA-CF'))).toBe('exact');
  });
});

describe('bestPreset', () => {
  it('prefers exact over close over generic', () => {
    const options = [opt('Generic PLA'), opt('Bambu PLA Matte'), opt('Bambu PLA Basic')];
    expect(bestPreset(spool(), options)?.option.name).toBe('Bambu PLA Basic');
    expect(bestPreset(spool({ subtype: 'Silk' }), options)?.kind).toBe('close');
    expect(bestPreset(spool({ brand: 'Other' }), options)?.option.name).toBe('Generic PLA');
  });

  it('prefers local over Orca over Bambu cloud over built-in for the same match', () => {
    const options = [opt('Bambu PLA Basic', 'builtin'), opt('Bambu PLA Basic', 'cloud', 'c'), opt('Bambu PLA Basic', 'orca_cloud', 'o'), opt('Bambu PLA Basic', 'local', 'l')];
    expect(bestPreset(spool(), options)?.option.code).toBe('l');
    expect(bestPreset(spool(), options.slice(0, 3))?.option.code).toBe('o');
  });

  it('picks the variant for an owned printer model, then a model-free name', () => {
    const options = [opt('Bambu PLA Basic @BBL A1'), opt('Bambu PLA Basic @BBL X1C'), opt('Bambu PLA Basic @BBL P1S')];
    expect(bestPreset(spool(), options, ['X1C'])?.option.name).toBe('Bambu PLA Basic @BBL X1C');
    expect(bestPreset(spool(), [...options, opt('Bambu PLA Basic')], ['H2D'])?.option.name).toBe('Bambu PLA Basic');
    expect(bestPreset(spool(), options, ['H2D'])?.option.name).toBe('Bambu PLA Basic @BBL A1');
  });

  it('returns null without any option for the material', () => {
    expect(bestPreset(spool({ material: 'TPU' }), [opt('Bambu PLA Basic')])).toBeNull();
    expect(bestPreset(spool(), [])).toBeNull();
  });
});

describe('buildProposals', () => {
  const options = [opt('Bambu PLA Basic'), opt('Generic PETG')];

  it('skips spools that already have a preset unless asked', () => {
    const spools = [spool({ id: 1 }), spool({ id: 2, slicer_filament: 'GFL00' })];
    expect(buildProposals(spools, options).matches.map((m) => m.spoolId)).toEqual([1]);
    expect(buildProposals(spools, options, [], true).matches.map((m) => m.spoolId)).toEqual([1, 2]);
  });

  it('lists spools without any match separately', () => {
    const spools = [spool({ id: 1 }), spool({ id: 3, material: 'TPU' })];
    const { matches, unmatched } = buildProposals(spools, options);
    expect(matches).toHaveLength(1);
    expect(unmatched.map((s) => s.id)).toEqual([3]);
  });
});

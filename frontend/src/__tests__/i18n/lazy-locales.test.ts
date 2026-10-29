import { describe, it, expect } from 'vitest';
import i18n, { ensureLocale } from '../../i18n';

describe('lazy locale loading', () => {
  it('loads a non-bundled language on demand', async () => {
    expect(i18n.hasResourceBundle('fr', 'translation')).toBe(false);
    expect(await ensureLocale('fr')).toBe(true);
    expect(i18n.hasResourceBundle('fr', 'translation')).toBe(true);
    expect(i18n.t('nav.printers', { lng: 'fr' })).toBe('Imprimantes');
  });

  it('does not fetch the same bundle twice', async () => {
    expect(await ensureLocale('fr')).toBe(false);
  });

  it('maps a bare language tag to its regional bundle', async () => {
    expect(await ensureLocale('pt')).toBe(true);
    expect(i18n.hasResourceBundle('pt-BR', 'translation')).toBe(true);
  });

  it('leaves the bundled German and English alone', async () => {
    expect(await ensureLocale('de')).toBe(false);
    expect(await ensureLocale('en')).toBe(false);
  });
});

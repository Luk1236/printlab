import { describe, it, expect } from 'vitest';
import en from '../../i18n/locales/en';
import de from '../../i18n/locales/de';
import es from '../../i18n/locales/es';
import fr from '../../i18n/locales/fr';
import it_ from '../../i18n/locales/it';
import ja from '../../i18n/locales/ja';
import ko from '../../i18n/locales/ko';
import nl from '../../i18n/locales/nl';
import ptBR from '../../i18n/locales/pt-BR';
import ru from '../../i18n/locales/ru';
import sv from '../../i18n/locales/sv';
import tr from '../../i18n/locales/tr';
import uk from '../../i18n/locales/uk';
import zhCN from '../../i18n/locales/zh-CN';
import zhTW from '../../i18n/locales/zh-TW';

type Tree = { [key: string]: string | Tree };

const locales: Record<string, Tree> = {
  de, es, fr, it: it_, ja, ko, nl, 'pt-BR': ptBR, ru, sv, tr, uk, 'zh-CN': zhCN, 'zh-TW': zhTW,
} as unknown as Record<string, Tree>;

function leaves(tree: Tree, prefix = ''): Map<string, string> {
  const out = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') out.set(path, value);
    else if (value && typeof value === 'object') for (const [p, v] of leaves(value, path)) out.set(p, v);
  }
  return out;
}

const placeholders = (text: string) => [...new Set([...text.matchAll(/\{\{\s*([\w.]+)\s*[,}]/g)].map((m) => m[1]))].sort();

const reference = leaves(en as unknown as Tree);

describe('translation placeholders', () => {
  for (const [code, tree] of Object.entries(locales)) {
    it(`${code} keeps every {{placeholder}} of the English text`, () => {
      const own = leaves(tree);
      const broken: string[] = [];
      for (const [key, english] of reference) {
        const translated = own.get(key);
        if (translated === undefined) continue;
        const want = placeholders(english);
        const got = placeholders(translated);
        if (want.join(',') !== got.join(',')) broken.push(`${key}: erwartet {${want.join(', ')}}, gefunden {${got.join(', ')}}`);
      }
      expect(broken).toEqual([]);
    });
  }

  it('has no empty translations', () => {
    const empty: string[] = [];
    for (const [code, tree] of Object.entries(locales)) {
      for (const [key, text] of leaves(tree)) {
        if (text.trim() === '' && (reference.get(key) ?? '').trim() !== '') empty.push(`${code}:${key}`);
      }
    }
    expect(empty).toEqual([]);
  });
});

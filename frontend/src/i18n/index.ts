import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';

// Import the fallback languages eagerly; the other locales are loaded on
// demand (see LAZY_LOCALES). The fifteen translation files are by far the
// largest part of the bundle, so shipping them all up front meant every
// visitor downloaded ~5 MB of languages they do not read.
import en from './locales/en';
import de from './locales/de';

const resources = {
  en: { translation: en },
  de: { translation: de },
};

// Bundles loaded the first time a language is selected. `hasResourceBundle`
// keeps repeated switches from fetching twice.
const LAZY_LOCALES: Record<string, () => Promise<{ default: Record<string, unknown> }>> = {
  es: () => import('./locales/es'),
  fr: () => import('./locales/fr'),
  ja: () => import('./locales/ja'),
  it: () => import('./locales/it'),
  ko: () => import('./locales/ko'),
  nl: () => import('./locales/nl'),
  'pt-BR': () => import('./locales/pt-BR'),
  'zh-CN': () => import('./locales/zh-CN'),
  'zh-TW': () => import('./locales/zh-TW'),
  sv: () => import('./locales/sv'),
  tr: () => import('./locales/tr'),
  ru: () => import('./locales/ru'),
  uk: () => import('./locales/uk'),
};

const LOCALE_ALIASES: Record<string, string> = {
  pt: 'pt-BR',
  zh: 'zh-CN',
};

/** Lädt die Übersetzung für eine Sprache nach; true, wenn ein Bündel dazukam. */
export async function ensureLocale(language: string): Promise<boolean> {
  const candidates = [language, LOCALE_ALIASES[language], language.split('-')[0], LOCALE_ALIASES[language.split('-')[0]]];
  for (const code of candidates) {
    if (!code) continue;
    const loader = LAZY_LOCALES[code];
    if (!loader || i18n.hasResourceBundle(code, 'translation')) continue;
    const module = await loader();
    i18n.addResourceBundle(code, 'translation', module.default, true, true);
    return true;
  }
  return false;
}

const SUPPORTED_LNGS = ['en', 'de', 'es', 'fr', 'ja', 'it', 'ko', 'nl', 'pt-BR', 'ru', 'sv', 'tr', 'uk', 'zh-CN', 'zh-TW'];
const APPLIANCE_CONSUMED_KEY = 'printlab_appliance_locale_consumed';

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    lng: 'de',
    fallbackLng: 'de',
    supportedLngs: SUPPORTED_LNGS,

    detection: {
      // Order of detection methods
      order: ['localStorage', 'navigator', 'htmlTag'],
      // Key to use in localStorage
      lookupLocalStorage: 'bambutrack_language',
      // Cache user language
      caches: ['localStorage'],
    },

    interpolation: {
      escapeValue: false, // React already escapes
    },

    react: {
      useSuspense: false,
    },
  });

// Sprachwechsel (Auswahl in den Einstellungen, Geräte-Assistent) lädt das
// passende Bündel nach. Der erste Start wird in main.tsx abgewartet, damit
// die Oberfläche nicht kurz in der Falschsprache aufblitzt. addResourceBundle
// allein löst kein Neuzeichnen aus, deshalb wird das Ereignis danach erneut
// gesendet — mit Schutz gegen die eigene Schleife.
let reloadingLocale = false;
i18n.on('languageChanged', (language) => {
  if (reloadingLocale) return;
  void ensureLocale(language).then((loaded) => {
    if (!loaded || i18n.language !== language) return;
    reloadingLocale = true;
    i18n.emit('languageChanged', language);
    reloadingLocale = false;
  });
});

/**
 * PrintLab Appliance hook: on the first SPA load after the firstboot wizard
 * runs, /api/v1/system/appliance returns the locale the user picked. We
 * apply it once (gated by a localStorage flag) and stop. On non-appliance
 * installs the endpoint either 404s or returns nulls — silent no-op.
 *
 * This runs AFTER i18n.init so the LanguageDetector has already populated a
 * default; we override that default exactly once for fresh appliances. The
 * appliance is then "consumed" and the language picker is the only way to
 * change locale going forward (the wizard ran once; future intent comes from
 * the running UI).
 */
function applyApplianceLocale() {
  if (typeof window === 'undefined' || !window.localStorage) return;
  const storage = window.localStorage;
  if (typeof storage.getItem !== 'function' || typeof storage.setItem !== 'function') return;
  if (storage.getItem(APPLIANCE_CONSUMED_KEY)) return;

  fetch('/api/v1/system/appliance')
    .then((r) => (r.ok ? r.json() : null))
    .then((data) => {
      if (!data || typeof data.locale !== 'string') return;
      if (!SUPPORTED_LNGS.includes(data.locale)) return;
      i18n.changeLanguage(data.locale);
      storage.setItem(APPLIANCE_CONSUMED_KEY, '1');
    })
    .catch(() => {
      // Endpoint absent or unreachable — non-appliance install or dev environment.
      // Leave the detector's choice in place.
    });
}

applyApplianceLocale();

export default i18n;

// Helper to get available languages
export const availableLanguages = [
  { code: 'en', name: 'English', nativeName: 'English' },
  { code: 'de', name: 'German', nativeName: 'Deutsch' },
  { code: 'es', name: 'Spanish', nativeName: 'Español' },
  { code: 'fr', name: 'French', nativeName: 'Français' },
  { code: 'ja', name: 'Japanese', nativeName: '日本語' },
  { code: 'it', name: 'Italian', nativeName: 'Italiano' },
  { code: 'ko', name: 'Korean', nativeName: '한국어' },
  { code: 'nl', name: 'Dutch', nativeName: 'Nederlands' },
  { code: 'pt-BR', name: 'Portuguese (Brazil)', nativeName: 'Português (Brasil)' },
  { code: 'zh-CN', name: 'Chinese (Simplified)', nativeName: '简体中文' },
  { code: 'zh-TW', name: 'Chinese (Traditional)', nativeName: '繁體中文' },
  { code: 'sv', name: 'Swedish', nativeName: 'Svenska' },
  { code: 'tr', name: 'Turkish', nativeName: 'Türkçe' },
  { code: 'ru', name: 'Russian', nativeName: 'Русский' },
  { code: 'uk', name: 'Ukrainian', nativeName: 'Українська' },
];

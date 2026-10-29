import { Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

/** Platzhalter, während eine nachgeladene Seite (React.lazy) geladen wird. */
export function PageLoading() {
  const { t } = useTranslation();
  return (
    <div className="min-h-[40vh] flex items-center justify-center gap-2" role="status" aria-live="polite">
      <Loader2 className="w-5 h-5 animate-spin text-bambu-green" aria-hidden="true" />
      <span className="text-sm text-bambu-gray">{t('common.loading')}</span>
    </div>
  );
}

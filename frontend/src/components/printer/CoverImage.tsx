import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Box } from 'lucide-react';

import { withMediaToken } from '../../api/client';

/**
 * Titelbild des aktiven Drucks mit Vollbild-Overlay.
 *
 * Aus pages/PrintersPage.tsx ausgelagert, inklusive der Lade-/Fehlerbehandlung
 * für zwischengespeicherte Bilder (#2826).
 */

export function CoverImage({
  url,
  printName,
  className = 'w-20 h-20',
  radiusClass = 'rounded-lg',
}: {
  url: string | null;
  printName?: string;
  className?: string;
  radiusClass?: string;
}) {
  const { t } = useTranslation();
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);
  const [showOverlay, setShowOverlay] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);

  // Cache-bust the image URL when the print name changes so the browser
  // fetches the new cover instead of serving the stale cached image.
  const cacheBustedUrl = useMemo(() => {
    if (!url) return null;
    const sep = url.includes('?') ? '&' : '?';
    return withMediaToken(`${url}${sep}v=${encodeURIComponent(printName || Date.now().toString())}`);
  }, [url, printName]);

  // Re-evaluate load state when the image URL changes, and ask the element
  // whether it is already showing something rather than assuming it is not.
  //
  // `onLoad` used to be the only thing that could set `loaded`, and this
  // effect reset it to false unconditionally. That is right when the URL
  // really changes, but it also runs on mount — and the two are not the same
  // situation (#2826). The URL is cache-busted on the print *name*, which is
  // constant for the duration of a print, so navigating away from the
  // printers page and back re-mounts with a byte-identical src that the
  // browser serves from its in-memory cache. The `load` event for a cache hit
  // and React's passive-effect flush are both plain tasks with no ordering
  // between them, so when `load` won, this effect ran afterwards and undid
  // it: `loaded` stayed false, the img stayed `hidden`, and the placeholder
  // sat there until a full reload. Nothing recovered it, because the URL
  // never changes again during the print and so this effect never re-runs.
  //
  // Being a race, it reproduced every time for #2826's reporter and not at
  // all here, which is also why the network panel showed no request: there
  // was no request to show.
  //
  // Asking `complete && naturalWidth > 0` settles it without needing to know
  // which of the two ran first. It is also correct for the case the reporter
  // proposed (a `load` that fires before React's handler is live), so the
  // fix stands whichever mechanism is really at work.
  useEffect(() => {
    setError(false);
    const el = imgRef.current;
    setLoaded(Boolean(el?.complete && el.naturalWidth > 0));
  }, [cacheBustedUrl]);

  return (
    <>
      <div
        className={`${className} flex-shrink-0 ${radiusClass} overflow-hidden bg-bambu-dark-tertiary flex items-center justify-center ${cacheBustedUrl && loaded ? 'cursor-pointer' : ''}`}
        onClick={() => cacheBustedUrl && loaded && setShowOverlay(true)}
      >
        {cacheBustedUrl && !error ? (
          <>
            <img
              ref={imgRef}
              src={cacheBustedUrl}
              alt={t('printers.printPreview')}
              className={`w-full h-full object-cover ${loaded ? 'block' : 'hidden'}`}
              onLoad={() => setLoaded(true)}
              onError={() => setError(true)}
            />
            {!loaded && <Box className="w-8 h-8 text-bambu-gray" />}
          </>
        ) : (
          <Box className="w-8 h-8 text-bambu-gray" />
        )}
      </div>

      {/* Cover Image Overlay */}
      {showOverlay && cacheBustedUrl && (
        <div
          className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-8"
          onClick={() => setShowOverlay(false)}
        >
          <div className="relative max-w-2xl max-h-full">
            <img
              src={cacheBustedUrl}
              alt={t('printers.printPreview')}
              className="max-w-full max-h-[80vh] rounded-lg shadow-2xl"
            />
            {printName && (
              <p className="text-white text-center mt-4 text-lg">{printName}</p>
            )}
          </div>
        </div>
      )}
    </>
  );
}

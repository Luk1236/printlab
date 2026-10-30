import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Link2 } from 'lucide-react';

import { api } from '../api/client';
import { Button } from './Button';
import { useToast } from '../contexts/ToastContext';

/**
 * Öffentlichen Angebots-Link erzeugen: der Kunde öffnet ihn ohne Anmeldung und sagt zu oder ab.
 * Der Link ist die Berechtigung — ein neuer Link macht den vorherigen ungültig.
 */
export function QuoteShareButton({ quoteId }: { quoteId: string }) {
  const { showToast } = useToast();
  const [shareUrl, setShareUrl] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const { data } = useQuery({
    queryKey: ['quoteShares', quoteId],
    queryFn: () => api.listQuoteShares(quoteId),
    enabled: expanded,
  });

  const create = useMutation({
    mutationFn: () => api.createQuoteShare(quoteId, 14),
    onSuccess: async (result) => {
      setShareUrl(result.url);
      setExpanded(true);
      try {
        await navigator.clipboard.writeText(result.url);
        showToast('Link erstellt und kopiert — 14 Tage gültig.');
      } catch {
        showToast('Link erstellt — bitte aus der Anzeige kopieren.');
      }
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const revoke = useMutation({
    mutationFn: () => api.revokeQuoteShare(quoteId),
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  const latest = data?.shares?.[0];
  return (
    <span className="inline-flex flex-col gap-1">
      <span className="inline-flex items-center gap-1">
        <Button
          size="sm"
          variant="ghost"
          aria-label="Angebots-Link teilen"
          disabled={create.isPending}
          onClick={() => create.mutate()}
        >
          <Link2 className="w-4 h-4" />
          Teilen
        </Button>
        {latest && (
          <span
            className={
              latest.status === 'accepted'
                ? 'text-bambu-green'
                : latest.status === 'declined'
                  ? 'text-red-700 dark:text-red-400'
                  : 'text-bambu-gray'
            }
            title={latest.responded_at ? `Antwort am ${latest.responded_at.slice(0, 10)}` : undefined}
          >
            {latest.status === 'accepted'
              ? 'zugesagt'
              : latest.status === 'declined'
                ? 'abgelehnt'
                : latest.status === 'revoked'
                  ? 'zurückgezogen'
                  : latest.expired
                    ? 'abgelaufen'
                    : 'offen'}
          </span>
        )}
      </span>
      {(shareUrl || (expanded && latest)) && (
        <span className="flex flex-wrap items-center gap-1">
          {shareUrl && (
            <input
              readOnly
              value={shareUrl}
              onFocus={(event) => event.currentTarget.select()}
              className="w-64 rounded border border-bambu-dark-tertiary bg-bambu-dark px-1.5 py-0.5 text-[11px] text-bambu-gray-light"
              aria-label="Öffentlicher Angebots-Link"
            />
          )}
          {expanded && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setExpanded(false);
                setShareUrl(null);
              }}
            >
              schließen
            </Button>
          )}
          {latest?.status === 'open' && (
            <span className="text-[11px] text-bambu-gray">
              Link endet mit …{latest.token_tail}
              <Button
                size="sm"
                variant="ghost"
                disabled={revoke.isPending}
                onClick={() => revoke.mutate()}
              >
                zurückziehen
              </Button>
            </span>
          )}
        </span>
      )}
    </span>
  );
}

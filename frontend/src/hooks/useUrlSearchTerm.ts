import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Übernimmt ``?search=…`` in einen vorhandenen Filter. Die Befehlspalette (Strg+K) springt so auf die Listen-Seite und
 * der Begriff steht bereits im Suchfeld; ein erneuter Sprung auf dieselbe Seite aktualisiert ihn ebenfalls.
 */
export function useUrlSearchTerm(setTerm: (term: string) => void) {
  const [params] = useSearchParams();
  const term = params.get('search');
  useEffect(() => {
    if (term !== null) setTerm(term);
  }, [term, setTerm]);
}

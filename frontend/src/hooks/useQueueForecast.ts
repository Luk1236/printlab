import { useQuery } from '@tanstack/react-query';

import type { QueueForecast } from '../utils/queueForecast';

/** Schlüssel, unter dem die Übersicht ihre Prognose ablegt; die Anzeige je Auftrag liest sie von dort. */
export const QUEUE_FORECAST_KEY = ['queueForecast'] as const;

/** Die zuletzt von der Auslastungs-Übersicht berechnete Prognose (undefined, solange die Übersicht nicht gezeigt wird). */
export function useQueueForecast(): QueueForecast | undefined {
  const { data } = useQuery<QueueForecast | undefined>({
    queryKey: QUEUE_FORECAST_KEY,
    queryFn: () => undefined,
    enabled: false,
    staleTime: Infinity,
  });
  return data;
}

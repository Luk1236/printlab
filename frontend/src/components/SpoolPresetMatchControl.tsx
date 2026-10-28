import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import type { InventorySpool } from '../api/client';
import { Button } from './Button';
import { SpoolPresetMatchModal } from './SpoolPresetMatchModal';

/** Knopf „Profile zuordnen" für die Filamentverwaltung; öffnet das Fenster mit den Vorschlägen für alle aktiven Spulen. */
export function SpoolPresetMatchControl({ spools }: { spools: InventorySpool[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {t('inventory.presetMatch.button')}
      </Button>
      {open && <SpoolPresetMatchModal spools={spools.filter((spool) => !spool.archived_at)} onClose={() => setOpen(false)} />}
    </>
  );
}

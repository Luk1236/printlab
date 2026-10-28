/** Hilfen für die zusätzlichen Positionen eines Angebots (Eingabezeilen, Summen). */
export interface ExtraItemDraft {
  description: string;
  quantity: string;
  unit_price: string;
}

export const EMPTY_ITEM: ExtraItemDraft = { description: '', quantity: '1', unit_price: '' };
export const MAX_EXTRA_ITEMS = 20;

const round2 = (value: number) => Math.round(value * 100) / 100;

/** Nur vollständige Zeilen zählen (Beschreibung, Menge > 0, Preis >= 0); halb ausgefüllte werden ignoriert. */
export function validItems(drafts: ExtraItemDraft[]) {
  return drafts
    .filter((d) => d.description.trim() && Number(d.quantity) > 0 && d.unit_price.trim() !== '' && Number(d.unit_price) >= 0)
    .map((d) => ({ description: d.description.trim(), quantity: Number(d.quantity), unit_price: Number(d.unit_price) }));
}

export function itemAmount(item: { quantity: number; unit_price: number }): number {
  return round2(item.quantity * item.unit_price);
}

export function extrasTotal(drafts: ExtraItemDraft[]): number {
  return round2(validItems(drafts).reduce((sum, item) => sum + itemAmount(item), 0));
}

import { useTranslation } from 'react-i18next';
import { Plus, X } from 'lucide-react';

import { Button } from './Button';
import { EMPTY_ITEM, MAX_EXTRA_ITEMS } from '../utils/quoteItems';
import type { ExtraItemDraft } from '../utils/quoteItems';

/** Eingabe der zusätzlichen Positionen eines Angebots (Versand, Konstruktion, Nachbearbeitung …), ohne Aufschlag. */
export function QuoteExtraItems({
  items,
  onChange,
}: {
  items: ExtraItemDraft[];
  onChange: (items: ExtraItemDraft[]) => void;
}) {
  const { t } = useTranslation();
  const update = (index: number, patch: Partial<ExtraItemDraft>) =>
    onChange(items.map((item, i) => (i === index ? { ...item, ...patch } : item)));
  const input =
    'mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm';

  return (
    <div className="space-y-2" data-testid="quote-extra-items">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-bambu-gray">{t('quote.extraItems')}</span>
        <Button
          size="sm"
          variant="ghost"
          disabled={items.length >= MAX_EXTRA_ITEMS}
          onClick={() => onChange([...items, { ...EMPTY_ITEM }])}
        >
          <Plus className="w-4 h-4" />
          {t('quote.addItem')}
        </Button>
      </div>
      {items.map((item, index) => (
        <div key={index} className="grid grid-cols-[1fr_5rem_6rem_auto] gap-2 items-end">
          <label className="text-xs text-bambu-gray">
            {t('quote.itemName')}
            <input
              value={item.description}
              maxLength={80}
              onChange={(event) => update(index, { description: event.target.value })}
              className={input}
              aria-label={`${t('quote.itemName')} ${index + 1}`}
            />
          </label>
          <label className="text-xs text-bambu-gray">
            {t('quote.itemQuantity')}
            <input
              type="number"
              min={0}
              step="any"
              value={item.quantity}
              onChange={(event) => update(index, { quantity: event.target.value })}
              className={input}
              aria-label={`${t('quote.itemQuantity')} ${index + 1}`}
            />
          </label>
          <label className="text-xs text-bambu-gray">
            {t('quote.itemUnitPrice')}
            <input
              type="number"
              min={0}
              step="0.01"
              value={item.unit_price}
              onChange={(event) => update(index, { unit_price: event.target.value })}
              className={input}
              aria-label={`${t('quote.itemUnitPrice')} ${index + 1}`}
            />
          </label>
          <Button
            size="sm"
            variant="ghost"
            aria-label={`${t('quote.removeItem')} ${index + 1}`}
            onClick={() => onChange(items.filter((_, i) => i !== index))}
          >
            <X className="w-4 h-4" />
          </Button>
        </div>
      ))}
    </div>
  );
}

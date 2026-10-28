import { describe, it, expect } from 'vitest';
import { extrasTotal, itemAmount, validItems } from '../../utils/quoteItems';

const row = (description: string, quantity: string, unit_price: string) => ({ description, quantity, unit_price });

describe('quote extra items', () => {
  it('counts only complete rows', () => {
    const rows = [row('Versand', '2', '4.5'), row('', '1', '5'), row('ohne Preis', '1', ''), row('Menge null', '0', '3'), row('negativ', '1', '-2')];
    expect(validItems(rows)).toEqual([{ description: 'Versand', quantity: 2, unit_price: 4.5 }]);
    expect(extrasTotal(rows)).toBe(9);
  });

  it('allows a free item and rounds to cents', () => {
    expect(validItems([row('Gratis', '1', '0')])).toHaveLength(1);
    expect(itemAmount({ quantity: 3, unit_price: 0.1 })).toBe(0.3);
    expect(extrasTotal([row('A', '1.5', '19.99')])).toBe(29.99);
  });
});

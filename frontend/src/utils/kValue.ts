/** K-Faktor mit drei Nachkommastellen; fehlender Wert steht für den Standard 0.020. */
export function formatKValue(k: number | null | undefined): string {
  const value = k ?? 0.02;
  return value.toFixed(3);
}

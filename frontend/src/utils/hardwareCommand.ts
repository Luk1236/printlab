// Befehle sind Text (Shell) oder eine Liste (Programm + Argumente, ohne Shell). Im Formular steht eine Liste als JSON.
export function commandToDraft(value: string | string[] | undefined): string {
  if (Array.isArray(value)) return JSON.stringify(value);
  return value ?? '';
}

export function draftToCommand(value: string): string | string[] {
  const text = value.trim();
  if (text.startsWith('[')) {
    try {
      const parsed: unknown = JSON.parse(text);
      if (Array.isArray(parsed) && parsed.every((part) => typeof part === 'string')) return parsed as string[];
    } catch {
      // kein gültiges JSON: bleibt ein normaler Befehlstext
    }
  }
  return value;
}

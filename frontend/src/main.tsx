import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import i18n, { ensureLocale } from './i18n' // Initialize i18n
import App from './App.tsx'

// Globale Fänger (best practices): unbehandelte Fehler/Abweisungen müssen
// mindestens sichtbar in der Konsole landen — ohne Tracker (lokal-first) ist
// das die Rückhalteebene neben dem Crash-Bildschirm (React-Fehlergrenze).
const reportGlobalProblem = (label: string, detail: unknown) => {
  console.error('[PrintLab]', label, detail)
}
window.addEventListener('error', (event) => reportGlobalProblem('Unbehandelter Fehler', event.error ?? event.message))
window.addEventListener('unhandledrejection', (event) => reportGlobalProblem('Unbehandelte Ablehnung', event.reason))

const root = createRoot(document.getElementById('root')!)

// Nicht gebündelte Sprachen (alles außer Deutsch und Englisch) werden vor dem
// ersten Rendern nachgeladen — sonst stünde die Oberfläche in der falschen
// Sprache, bis das Bündel eintrifft.
void ensureLocale(i18n.language).finally(() => {
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})

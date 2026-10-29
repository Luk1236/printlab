import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import i18n, { ensureLocale } from './i18n' // Initialize i18n
import App from './App.tsx'

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

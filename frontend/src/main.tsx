import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

if (window.Capacitor?.isNativePlatform?.() || window.location.protocol === "capacitor:" || window.location.protocol === "ionic:") {
  window.__STOCKAGENT_FORCE_REMOTE__ = true
}

const CHUNK_RELOAD_KEY = "workbench:chunk-reload"

window.addEventListener("vite:preloadError", (event) => {
  const last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || 0)
  if (Date.now() - last < 10_000) return
  event.preventDefault()
  sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
  window.location.reload()
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)

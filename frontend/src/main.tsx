import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { PetWindow } from './components/pet/PetWindow.tsx'

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

const root = createRoot(document.getElementById('root')!)

/** 桌宠窗口和主界面加载同一个 URL，只能靠窗口 label 区分。
 *  withGlobalTauri 下 label 可以直接同步读到；读不到再退回 IPC 兜底。 */
type TauriBoot = {
  window?: { getCurrentWindow?: () => { label?: string } }
  core?: { invoke?: <T>(cmd: string, args?: Record<string, unknown>) => Promise<T> }
}

async function currentWindowLabel(): Promise<string> {
  // 浏览器里没有窗口 label：用 ?pet=1 预览桌宠 UI（设计稿/联调用）
  if (new URLSearchParams(window.location.search).get("pet") === "1") return "pet"
  const tauri = (window as unknown as { __TAURI__?: TauriBoot }).__TAURI__
  const direct = tauri?.window?.getCurrentWindow?.()?.label
  if (typeof direct === 'string' && direct) return direct
  const invoke = tauri?.core?.invoke
  if (!invoke) return 'main'
  try {
    return await invoke<string>('window_label')
  } catch {
    return 'main'
  }
}

void (async () => {
  const label = await currentWindowLabel()
  if (label === 'pet') {
    document.documentElement.classList.add('pet-window-root')
    root.render(<PetWindow />)
    return
  }
  root.render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})()

import { useState, useCallback, useEffect, useRef } from 'react'
import { BrowserRouter, Routes, Route, NavLink, Outlet } from 'react-router-dom'
import {
  LayoutDashboard, Building2, GitCompare, Activity,
  Play, Loader2, CheckCircle, XCircle, Clock, Settings2, X,
} from 'lucide-react'
import Overview from './pages/Overview'
import Banks from './pages/Banks'
import Changes from './pages/Changes'

const NAV = [
  { to: '/',        icon: LayoutDashboard, label: 'OVERVIEW'   },
  { to: '/banks',   icon: Building2,       label: 'BANKS'      },
  { to: '/changes', icon: GitCompare,      label: 'CHANGES'    },
]

const BANK_COLORS: Record<string, string> = {
  tbank: '#fbbf24', alfabank: '#f87171', sber: '#86efac', tochka: '#60a5fa',
}
const BANK_LABELS: Record<string, string> = {
  tbank: 'Т-Банк', alfabank: 'Альфа-Банк', sber: 'Сбер', tochka: 'Точка',
}

interface BankStatus {
  status: 'pending' | 'running' | 'done' | 'error'
  started_at: string | null
  finished_at: string | null
  services: number
  methods: number
  error: string | null
}
interface ParseStatus {
  running: boolean
  started_at: string | null
  finished_at: string | null
  banks: Record<string, BankStatus>
}

function BankStatusRow({ bank, st }: { bank: string; st: BankStatus }) {
  const color = BANK_COLORS[bank] ?? '#888'
  const label = BANK_LABELS[bank] ?? bank

  const icon = (() => {
    if (st.status === 'running') return <Loader2 size={14} className="animate-spin text-[#86efac]" />
    if (st.status === 'done')    return <CheckCircle size={14} className="text-[#86efac]" />
    if (st.status === 'error')   return <XCircle size={14} className="text-[#f87171]" />
    return <Clock size={14} className="text-[#666]" />
  })()

  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[#1F1F1F] last:border-0">
      <div className="flex items-center gap-2">
        <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
        <span className={`text-sm ${st.status === 'pending' ? 'text-[#666]' : 'text-[#E7E7E7]'}`}>{label}</span>
      </div>
      <div className="flex items-center gap-2">
        {st.status === 'done' && (
          <span className="text-[10px] text-[#666]">{st.services} сервисов · {st.methods.toLocaleString('ru')} методов</span>
        )}
        {st.status === 'error' && (
          <span className="text-[10px] text-[#f87171] max-w-[120px] truncate" title={st.error ?? ''}>Ошибка</span>
        )}
        {st.status === 'running' && (
          <span className="text-[10px] text-[#86efac]">Парсинг…</span>
        )}
        {icon}
      </div>
    </div>
  )
}

function ParsePanel({ status, onClose }: { status: ParseStatus; onClose: () => void }) {
  const banks = Object.keys(status.banks)
  const done  = banks.filter(b => status.banks[b].status === 'done').length
  const errors= banks.filter(b => status.banks[b].status === 'error').length
  const total = banks.length

  return (
    <div className="fixed bottom-6 right-6 bg-[#0D0D0D] border border-[#333] rounded-2xl p-5 w-80 shadow-2xl z-50">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          {status.running
            ? <Loader2 size={14} className="animate-spin text-[#86efac]" />
            : <CheckCircle size={14} className="text-[#86efac]" />}
          <span className="text-sm font-semibold text-white">
            {status.running ? 'Парсинг API банков…' : `Готово: ${done}/${total}`}
          </span>
        </div>
        {!status.running && (
          <button onClick={onClose} className="text-[#666] hover:text-[#E7E7E7] transition-colors">
            <X size={15} />
          </button>
        )}
      </div>

      {/* Progress bar */}
      <div className="h-1 bg-[#1A1A1A] rounded-full mb-4 overflow-hidden">
        <div
          className="h-full bg-[#86efac] rounded-full transition-all duration-500"
          style={{ width: `${total > 0 ? ((done + errors) / total) * 100 : 0}%` }}
        />
      </div>

      {/* Per-bank rows */}
      <div>
        {banks.map(bank => (
          <BankStatusRow key={bank} bank={bank} st={status.banks[bank]} />
        ))}
      </div>

      {/* Footer */}
      {!status.running && status.finished_at && (
        <p className="mt-3 text-[10px] text-[#666] text-right">
          Завершено: {status.finished_at}
        </p>
      )}
    </div>
  )
}

function Layout() {
  const [refresh, setRefresh] = useState(0)
  const [showPanel, setShowPanel] = useState(false)
  const [parseStatus, setParseStatus] = useState<ParseStatus | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }, [])

  const pollStatus = useCallback(async () => {
    try {
      const r = await fetch('/api/parse/status')
      const s: ParseStatus = await r.json()
      setParseStatus(s)
      if (!s.running) {
        stopPolling()
        setRefresh(n => n + 1)
      }
    } catch { /* ignore */ }
  }, [stopPolling])

  const startPolling = useCallback(() => {
    stopPolling()
    pollRef.current = setInterval(pollStatus, 3000)
  }, [pollStatus, stopPolling])

  // Cleanup on unmount
  useEffect(() => () => stopPolling(), [stopPolling])

  const triggerParse = useCallback(async () => {
    if (parseStatus?.running) return
    try {
      const r = await fetch('/api/parse', { method: 'POST' })
      const data = await r.json()
      if (data.status === 'started' || data.status === 'already_running') {
        setShowPanel(true)
        await pollStatus()  // immediate first poll
        startPolling()
      }
    } catch (err) {
      console.error('Parse trigger failed:', err)
    }
  }, [parseStatus, pollStatus, startPolling])

  const isRunning = parseStatus?.running ?? false

  return (
    <div className="relative h-screen w-full bg-black text-white overflow-hidden">
      {/* ── Header ── */}
      <header className="absolute top-0 left-0 right-0 z-50 flex items-center justify-between p-6 bg-black/10 backdrop-blur-[120px]">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-[#86efac] rounded-lg flex items-center justify-center">
            <Activity size={15} className="text-black" strokeWidth={2.5} />
          </div>
          <span className="text-base font-bold tracking-widest text-white">API MONITOR</span>
        </div>

        <div className="flex items-center gap-3">
          {/* Running badge */}
          {isRunning && (
            <div
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1A1A1A] border border-[#333] rounded-xl cursor-pointer hover:border-[#86efac]/40 transition-colors"
              onClick={() => setShowPanel(true)}
            >
              <Loader2 size={12} className="animate-spin text-[#86efac]" />
              <span className="text-xs text-[#86efac]">Идёт парсинг…</span>
            </div>
          )}

          <button
            onClick={triggerParse}
            disabled={isRunning}
            className="flex items-center gap-2 px-4 py-2 bg-[#86efac] text-black rounded-xl font-semibold text-sm tracking-wide hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isRunning
              ? <Loader2 size={13} className="animate-spin" />
              : <Play size={13} strokeWidth={2.5} />}
            ПАРСИНГ
          </button>
        </div>
      </header>

      {/* ── Main ── */}
      <div className="h-full overflow-y-auto no-scrollbar">
        <main className="flex gap-6 p-6 pt-24 min-h-full">
          {/* ── Sidebar ── */}
          <aside className="sticky top-24 h-[calc(100vh-8rem)] md:w-48 lg:w-64 bg-[#0D0D0D] rounded-2xl hidden md:flex flex-col p-8 overflow-y-auto shrink-0">
            <nav className="flex flex-col gap-8">
              {NAV.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-4 transition-colors cursor-pointer ${
                      isActive ? 'text-[#E7E7E7]' : 'text-[#919191] hover:text-[#E7E7E7]'
                    }`
                  }
                >
                  <Icon className="h-5 w-5 shrink-0" />
                  <span className="text-sm font-medium tracking-wide">{label}</span>
                </NavLink>
              ))}
            </nav>

            <div className="mt-auto pt-8 border-t border-[#1F1F1F] flex flex-col gap-6">
              <div className="flex flex-col gap-3">
                {Object.entries(BANK_LABELS).map(([key, label]) => (
                  <div key={key} className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: BANK_COLORS[key] }} />
                    <span className="text-xs text-[#919191]">{label}</span>
                  </div>
                ))}
              </div>
              <div className="flex items-center gap-4 text-[#919191] hover:text-[#E7E7E7] transition-colors cursor-pointer">
                <Settings2 className="h-5 w-5 shrink-0" />
                <span className="text-sm font-medium tracking-wide">SETTINGS</span>
              </div>
            </div>
          </aside>

          {/* ── Page content ── */}
          <div className="flex-1 flex flex-col gap-6 min-w-0">
            <Outlet context={{ refresh }} />
            <div className="flex items-center justify-end gap-2 mt-2 pb-2">
              <div className={`w-[10px] h-[10px] rounded-full ${isRunning ? 'bg-[#fbbf24]' : 'bg-[#86efac]'}`} />
              <span className="text-xs text-[#919191]">{isRunning ? 'Parsing' : 'Online'}</span>
            </div>
          </div>
        </main>
      </div>

      {/* ── Parse status panel ── */}
      {showPanel && parseStatus && (
        <ParsePanel
          status={parseStatus}
          onClose={() => setShowPanel(false)}
        />
      )}
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="banks" element={<Banks />} />
          <Route path="changes" element={<Changes />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

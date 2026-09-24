import { useState, type FormEvent } from 'react'
import { Loader2, LogIn } from 'lucide-react'
import { errorText } from '../api'
import { AlfaLogo } from '../components/AlfaLogo'

export default function Login({ onLogin }: { onLogin: (password: string) => Promise<void> }) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!password || busy) return
    setBusy(true)
    setError(null)
    try {
      await onLogin(password)
    } catch (err) {
      setError(errorText(err, 'Не удалось войти, сервер недоступен'))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-page p-6">
      <form
        onSubmit={submit}
        aria-labelledby="login-title"
        className="enter flex w-full max-w-sm flex-col gap-6 rounded-2xl border border-line bg-surface p-7 shadow-raised sm:p-8"
      >
        <div className="flex items-center gap-3">
          <AlfaLogo size={34} className="rounded-lg" />
          <h1 id="login-title" className="text-base font-bold tracking-tight text-ink">
            API Monitor
          </h1>
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-xs font-medium text-ink-muted">Пароль</span>
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            maxLength={200}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={error !== null}
            aria-describedby={error ? 'login-error' : undefined}
            className="rounded-xl border border-line bg-page px-4 py-3 text-sm text-ink outline-none transition-colors duration-150 placeholder:text-ink-faint focus:border-line-strong"
          />
        </label>

        {error && (
          <p id="login-error" role="alert" className="-mt-2 text-sm text-danger">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={!password || busy}
          className="press flex items-center justify-center gap-2 rounded-xl bg-brand-solid px-4 py-3 text-sm font-semibold text-brand-fg transition-[filter] duration-150 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? (
            <Loader2 size={15} className="animate-spin" aria-hidden />
          ) : (
            <LogIn size={15} strokeWidth={2.5} aria-hidden />
          )}
          Войти
        </button>
      </form>
    </div>
  )
}

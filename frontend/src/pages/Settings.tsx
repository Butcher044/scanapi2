import { Loader2, RefreshCw } from 'lucide-react'
import { useAppSettings } from '../hooks/useAppSettings'
import { isUsable, useProxies } from '../hooks/useProxies'
import ScheduleCard from '../components/settings/ScheduleCard'
import ProxyToggle from '../components/settings/ProxyToggle'
import ProxyList from '../components/settings/ProxyList'
import { ghostButton } from '../components/settings/Card'

function ErrorLine({ text }: { text: string | null }) {
  return text ? <p role="alert" className="text-sm text-[#f87171]">{text}</p> : null
}

/** Placeholder for a section whose data is not loaded yet: spinner, or the error with a retry. */
function Pending({ error, onRetry }: { error: string | null; onRetry: () => void }) {
  if (!error) {
    return <div className="flex justify-center py-12"><Loader2 className="animate-spin text-[#86efac]" /></div>
  }
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <ErrorLine text={error} />
      <button type="button" className={ghostButton} onClick={onRetry}>
        <RefreshCw size={12} />
        Повторить
      </button>
    </div>
  )
}

export default function Settings() {
  const { settings, error: settingsError, saving, reload: reloadSettings, save } = useAppSettings()
  const {
    proxies, error: proxyError, checking, deleting, checkingAll,
    reload: reloadProxies, add, remove, check, checkAll,
  } = useProxies()

  return (
    <div className="flex flex-col gap-6 max-w-4xl">
      <h1 className="text-2xl font-bold tracking-wide">Настройки</h1>

      {settings ? (
        <>
          <ErrorLine text={settingsError} />
          <ScheduleCard
            key={settings.scheduler_time}
            settings={settings}
            saving={saving}
            onSave={time => void save({ scheduler_time: time })}
          />
          <ProxyToggle
            enabled={settings.proxy_enabled}
            saving={saving}
            usableCount={proxies ? proxies.filter(isUsable).length : null}
            onChange={enabled => void save({ proxy_enabled: enabled })}
          />
        </>
      ) : (
        <Pending error={settingsError} onRetry={reloadSettings} />
      )}

      {proxies ? (
        <>
          <ErrorLine text={proxyError} />
          <ProxyList
            proxies={proxies}
            checking={checking}
            deleting={deleting}
            checkingAll={checkingAll}
            onAdd={add}
            onCheck={id => void check(id)}
            onCheckAll={() => void checkAll()}
            onDelete={id => void remove(id)}
          />
        </>
      ) : (
        <Pending error={proxyError} onRetry={reloadProxies} />
      )}
    </div>
  )
}

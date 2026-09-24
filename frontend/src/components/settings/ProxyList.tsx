import { Loader2, RefreshCw } from 'lucide-react'
import type { NewProxy, Proxy } from '../../types'
import { Card, ghostButton } from './Card'
import ProxyRow from './ProxyRow'
import AddProxyForm from './AddProxyForm'

interface Props {
  proxies: Proxy[]
  checking: ReadonlySet<number>
  deleting: ReadonlySet<number>
  checkingAll: boolean
  onAdd: (proxy: NewProxy) => Promise<void>
  onCheck: (id: number) => void
  onCheckAll: () => void
  onDelete: (id: number) => void
}

export default function ProxyList({ proxies, checking, deleting, checkingAll, onAdd, onCheck, onCheckAll, onDelete }: Props) {
  const checkAllButton = (
    <button type="button" className={ghostButton} disabled={checkingAll || checking.size > 0 || proxies.length === 0} onClick={onCheckAll}>
      {checkingAll ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
      Проверить все
    </button>
  )

  return (
    <Card title={`ПРОКСИ · ${proxies.length}`} action={checkAllButton}>
      {proxies.length === 0 ? (
        <p className="text-sm text-[#666]">Список пуст. Добавьте первый прокси ниже.</p>
      ) : (
        <ul>
          {proxies.map(p => (
            <ProxyRow
              key={p.id}
              proxy={p}
              checking={checkingAll || checking.has(p.id)}
              deleting={deleting.has(p.id)}
              onCheck={onCheck}
              onDelete={onDelete}
            />
          ))}
        </ul>
      )}
      <AddProxyForm onAdd={onAdd} />
    </Card>
  )
}

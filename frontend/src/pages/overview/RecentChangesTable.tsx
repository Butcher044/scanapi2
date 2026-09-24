import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, ExternalLink } from 'lucide-react'
import ActionBadge from '../../components/ActionBadge'
import BankBadge from '../../components/BankBadge'
import TypeBadge from '../../components/TypeBadge'
import { isSafeHttpUrl } from '../../safeUrl'
import type { Change } from '../../types'

type Props = {
  changes: readonly Change[]
}

const HEADERS = ['Банк', 'Тип', 'Изменение', 'Сущность'] as const

export function RecentChangesTable({ changes }: Props) {
  return (
    <section className="rounded-2xl border border-line bg-surface p-5 shadow-card sm:p-6">
      <div className="mb-4 flex items-center justify-between gap-4">
        <h2 id="recent-changes-title" className="text-base font-semibold text-ink sm:text-lg">
          Последние изменения
        </h2>
        <Link
          to="/changes"
          className="press shrink-0 text-sm text-ink-muted transition-colors hover:text-ink"
        >
          Все →
        </Link>
      </div>

      {/* Bleeds to the card edges so the horizontal scroll on a phone does not
          look like a clipped layout. */}
      <div className="relative -mx-5 overflow-x-auto px-5 sm:-mx-6 sm:px-6">
        <table aria-labelledby="recent-changes-title" className="w-full min-w-[620px] border-collapse">
          <thead>
            <tr className="text-sm text-ink-muted">
              {HEADERS.map((header) => (
                <th key={header} scope="col" className="pb-3 pl-2 text-left font-medium first:pl-2">
                  {header}
                </th>
              ))}
              <th scope="col" className="pb-3 text-right font-medium">
                Дата
              </th>
              <th scope="col" className="pb-3 pr-2 text-right font-medium">
                <span className="sr-only">Ссылка</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {changes.map((change) => (
              <tr
                key={change.id}
                className="border-b border-line transition-colors duration-150 last:border-0 hover:bg-raised"
              >
                <td className="py-3 pl-2">
                  <BankBadge bank={change.bank} label={change.bank_label} />
                </td>
                <td className="py-3 pl-2">
                  <TypeBadge type={change.type} />
                </td>
                <td className="py-3 pl-2">
                  <ActionBadge action={change.action} />
                </td>
                <td className="max-w-[220px] py-3 pl-2">
                  <span className="block truncate font-mono text-xs text-ink" title={change.entity}>
                    {change.entity}
                  </span>
                </td>
                <td className="whitespace-nowrap py-3 text-right text-xs text-ink-muted">
                  {change.detected_at}
                </td>
                <td className="py-3 pr-2 text-right">
                  <div className="flex items-center justify-end gap-1.5">
                    {change.action === 'added' && (
                      <ArrowUp role="img" className="h-4 w-4 text-ok" aria-label="Добавлено" />
                    )}
                    {change.action === 'removed' && (
                      <ArrowDown role="img" className="h-4 w-4 text-danger" aria-label="Удалено" />
                    )}
                    {isSafeHttpUrl(change.url) && (
                      <a
                        href={change.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="Открыть источник"
                        className="press text-ink-faint transition-colors hover:text-ink"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                </td>
              </tr>
            ))}

            {changes.length === 0 && (
              <tr>
                <td colSpan={6} className="py-10 text-center text-sm text-ink-faint">
                  Нет данных — запустите парсинг
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  )
}

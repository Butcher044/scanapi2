import {
  Building2,
  EyeOff,
  GitCompare,
  LayoutDashboard,
  Settings as SettingsIcon,
  Table2,
  type LucideIcon,
} from 'lucide-react'
import type { Role } from '../../types'

export type NavItem = {
  to: string
  icon: LucideIcon
  label: string
}

const BASE_NAV: readonly NavItem[] = [
  { to: '/', icon: LayoutDashboard, label: 'Обзор' },
  { to: '/banks', icon: Building2, label: 'Банки' },
  { to: '/changes', icon: GitCompare, label: 'Изменения' },
  { to: '/benchmark', icon: Table2, label: 'Бенчмарк' },
]

const ADMIN_NAV: readonly NavItem[] = [
  { to: '/hidden', icon: EyeOff, label: 'Скрытые сервисы' },
  { to: '/settings', icon: SettingsIcon, label: 'Настройки' },
]

export function navItemsFor(role: Role): readonly NavItem[] {
  return role === 'admin' ? [...BASE_NAV, ...ADMIN_NAV] : BASE_NAV
}

export const ROLE_LABELS: Record<Role, string> = {
  admin: 'Администратор',
  team: 'Команда',
}

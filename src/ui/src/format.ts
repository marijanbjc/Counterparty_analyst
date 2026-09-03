import type { RiskLevel } from './types'

export const money = (value: number | null | undefined) =>
  value == null
    ? 'Нет данных'
    : new Intl.NumberFormat('ru-RU', {
        style: 'currency',
        currency: 'RUB',
        maximumFractionDigits: 0,
      }).format(value)

export const number = (value: number | null | undefined) =>
  value == null ? '—' : new Intl.NumberFormat('ru-RU').format(value)

export const date = (value: string | null | undefined) =>
  value
    ? new Intl.DateTimeFormat('ru-RU', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
      }).format(new Date(value))
    : 'Нет данных'

export const riskName = (value: RiskLevel) =>
  ({
    LOW: 'Низкий риск',
    MEDIUM: 'Средний риск',
    HIGH: 'Высокий риск',
    UNKNOWN: 'Риск не определён',
  })[value ?? 'UNKNOWN']

export const riskTone = (value: RiskLevel) =>
  ({ LOW: 'good', MEDIUM: 'warning', HIGH: 'danger', UNKNOWN: 'neutral' })[
    value ?? 'UNKNOWN'
  ]

export function entityKind(kind: string | null | undefined): string {
  if (kind === 'sole_proprietor') return 'Индивидуальный предприниматель'
  if (kind === 'organization') return 'Организация'
  return 'Тип не определён'
}

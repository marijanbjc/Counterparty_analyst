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

/** Цвет плашки берётся из вердикта, а не из уровня риска. На плашке написан
 *  вердикт, и красить её светофором банка значило показывать зелёное
 *  «Не рекомендуется»: у контрагента в банкротстве риск остаётся низким
 *  (known_issues.md §17). Уровень риска красится riskTone — там он и написан. */
export const verdictTone = (verdict: string | null | undefined) =>
  ({
    'Работать': 'good',
    'Работать с осторожностью': 'warning',
    'Не рекомендуется': 'danger',
  })[verdict ?? ''] ?? 'neutral'

/** Статус из ЕГРЮЛ приходит кодом. «CURRENT» на экране — тот же технический
 *  термин, что и имена полей в тексте: по-русски лицо «действующее». */
export const statusName = (value: string | null | undefined) =>
  value
    ? ({
        CURRENT: 'Действующее',
        LIQUIDATING: 'В процессе ликвидации',
        LIQUIDATED: 'Ликвидировано',
        BANKRUPT: 'Банкротство',
      }[value] ?? value)
    : 'Нет данных'

export function entityKind(kind: string | null | undefined): string {
  if (kind === 'sole_proprietor') return 'Индивидуальный предприниматель'
  if (kind === 'organization') return 'Организация'
  return 'Тип не определён'
}

export const zskName = (value: 'GREEN' | 'YELLOW' | 'RED' | null | undefined) =>
  value ? { GREEN: 'зелёный', YELLOW: 'жёлтый', RED: 'красный' }[value] : 'нет данных'

/** Доля 0.0109 читается человеком как «1 %», а не как коэффициент. */
export const percent = (value: number | null | undefined) =>
  value == null ? '—' : `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(value * 100)} %`

/** Крупные суммы в рублях нечитаемы целиком: 116 257 852 000 → «116,3 млрд ₽». */
export const compactMoney = (value: number | null | undefined) => {
  if (value == null) return 'Нет данных'
  const abs = Math.abs(value)
  const [scale, suffix] = abs >= 1e9 ? [1e9, 'млрд'] : abs >= 1e6 ? [1e6, 'млн'] : [1, '']
  const digits = suffix ? 1 : 0
  const text = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(value / scale)
  return suffix ? `${text} ${suffix} ₽` : `${text} ₽`
}

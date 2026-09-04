export type RolePreset = 'finance' | 'legal' | 'security' | 'activity' | 'general'

// Роль — свойство сессии, набор — разовое действие на один ход (§7.4).
export type DataSet = 'finance' | 'legal' | 'security' | 'activity' | 'followups' | 'charts'

export type AuthState = {
  token: string
  userId: string
}

export type Session = {
  id: string
  user_id: string
  title: string | null
  role_preset: RolePreset
  created_at: string
}

export type Message = {
  id: number
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  meta: { inn?: string | null; scenario?: string; report?: FactPack; degraded?: boolean } | null
  created_at: string
}

export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'UNKNOWN' | null

export type FactPack = {
  inn: string
  ogrn: string
  short_name: string
  full_name?: string
  as_of: string | null
  verdict_basis: {
    risk_level: RiskLevel
    zsk_risk_level: 'GREEN' | 'YELLOW' | 'RED' | null
    disagreement: boolean
  }
  profile: {
    status: string | null
    registered: string | null
    age_years: number | null
    company_size: string | null
    entity_kind: 'organization' | 'sole_proprietor'
    main_okved: { code: string | null; description: string | null }
    address?: string | null
    email?: string | null
    website?: string | null
    phone?: string | null
    staff?: string | null
    auth_person?: { name: string | null; position: string | null; since: string | null }
  }
  financials: {
    available: boolean
    years: Array<{ year: number; proceeds: number | null; profit: number | null }>
    trend: { proceeds: string | null; profit: string | null }
    balance?: Array<Record<string, number | null>>
  }
  arbitration: {
    total_count: number | null
    total_amount: number | null
    as_defendant?: { count?: number; amount?: number; pending?: number }
    as_plaintiff?: { count?: number; amount?: number; pending?: number }
  }
  execution_proceedings: {
    total: number
    active: number
    total_amount: number | null
    active_amount: number | null
  }
  legal_status: {
    status: string | null
    status_date: string | null
    status_reason: string | null
    reason_code: string
    severity: 'critical' | 'attention' | 'none'
  }
  risk_factors: {
    negative: Array<{ code: string | null; chapter: string | null; name?: string | null }>
    // в режиме slim позитивных факторов и связанных компаний в пакете нет
    positive?: Array<{ code: string | null; chapter: string | null; name?: string | null }>
    negative_total: number
  }
  discrepancies: Array<{ code: string; text: string }>
  related_companies_count: number
  related_companies?: Array<{
    inn: string | null
    name: string | null
    auth_person_name: string | null
  }>
  missing_data: string[]
}

// Переспрос, отказ по квоте и сравнение отчёта не создают — полей разбора у них нет.
export type ChatResponse = {
  session: Session
  messages: Message[]
  answer: string
  verdict: string | null
  summary: string | null
  analysis: string | null
  report: FactPack | null
  contractor: { inn: string; short_name: string } | null
  degraded: boolean
  notice: string | null
}

export type Profile = {
  login: string
  display_name: string | null
  tariff: string
  tariff_label: string
  profile: string
  requests_used: number
  requests_limit: number
  reports_generated: number
}

export type MessagePage = {
  items: Message[]
  total: number
  has_more: boolean
}

export type CompareResult = {
  items: FactPack[]
  count: number
  missing: string[]
  invalid: string[]
}

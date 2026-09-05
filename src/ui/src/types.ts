export type RolePreset = 'finance' | 'legal' | 'security' | 'activity' | 'general'

// Роль — свойство сессии, набор — разовое действие на один ход (§7.4).
export type DataSet = 'finance' | 'legal' | 'security' | 'activity' | 'followups'

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

export type Followup = { question: string; reason: string; trigger: string }

export type ComparisonRow = Record<string, string | number | boolean | null>

export type Comparison = {
  matrix?: ComparisonRow[]
  differences?: { metric: string; text: string }[]
  ranking?: { place: number; inn: string; short_name: string }[]
  not_found?: string[]
  verdicts?: { inn: string; verdict: string }[]
}

/** Блоки, которые рисуются одинаково и в свежем ответе, и в истории. */
export type ContractorBlocks = {
  inn: string
  short_name: string
  key_risks: string[]
  positives: string[]
}

/** Подсказка следующего шага. 'prompt' отправляется сразу — вопрос уже полный;
 *  'draft' подставляется в поле, потому что клиенту надо дописать второй ИНН;
 *  'action' запускает свой сценарий интерфейса (пока только подбор
 *  альтернативы). Собираются кодом на бэкенде, токенов не стоят. */
export type NextStep = {
  code: string
  label: string
  kind: 'prompt' | 'draft' | 'action'
  prompt: string | null
  /** Набор данных, который надо дочитать вместе с этим вопросом.
   *  Вопрос при этом уходит БЕЗ ИНН — в уточнение, где факт-пакета нет
   *  и набор помещается в бюджет (client_path_ideas.md §8). */
  dataset: DataSet | null
}

/** Кандидат из подбора альтернативы. Оценки банка здесь нет намеренно:
 *  её клиент получает обычной проверкой, назвав ИНН сам. */
export type Alternative = {
  inn: string
  short_name: string
  region: string | null
  main_okved: string | null
}

export type AlternativesResponse = {
  items: Alternative[]
  same_region: boolean
  region: string | null
  can_widen: boolean
  okved: string | null
}

export type MessageBlocks = {
  /** Сценарий хода: по нему решаем, показывать ли карточку риск/плюсы.
   *  В уточнении она не нужна — клиент задал вопрос и ждёт ответ. */
  scenario?: string
  /** Кого касается ответ: имя и ИНН уходят в шапку сообщения. */
  subject?: string | null
  inn?: string | null
  verdict?: string | null
  risk_level?: RiskLevel
  zsk_risk_level?: 'GREEN' | 'YELLOW' | 'RED' | null
  key_risks?: string[]
  positives?: string[]
  followups?: Followup[]
  next_steps?: NextStep[]
  /** Темы, реально дочитанные за этот ход: без них кнопка выглядела
   *  сломанной на контрагенте с пустым разделом. */
  datasets?: string[]
  comparison?: Comparison | null
  per_contractor?: ContractorBlocks[]
  report?: FactPack
}

export type Message = {
  id: number
  session_id: string
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  meta:
    | ({ inn?: string | null; scenario?: string; report?: FactPack; degraded?: boolean } & MessageBlocks)
    | null
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
    by_year?: { year: number; plaintiff_count: number | null; defendant_count: number | null }[]
    total_count: number | null
    total_amount: number | null
    as_defendant?: { count?: number; amount?: number; pending_count?: number; pending_amount?: number }
    as_plaintiff?: { count?: number; amount?: number; pending_count?: number; pending_amount?: number }
  }
  execution_proceedings: {
    by_year?: Record<string, number>
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
  debt_burden?: { current_debt: number; net_assets: number | null; debt_to_net_assets: number | null } | null
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
  key_risks: string[]
  positives: string[]
  followups: Followup[]
  next_steps: NextStep[]
  per_contractor: ContractorBlocks[]
  comparison: Comparison | null
  risk_level: RiskLevel
  zsk_risk_level: 'GREEN' | 'YELLOW' | 'RED' | null
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

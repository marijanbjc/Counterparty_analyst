import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '@alfalab/core-components/button'
import { Spinner } from '@alfalab/core-components/spinner'
import { Textarea } from '@alfalab/core-components/textarea'

import { api, ApiError } from '../api'
import { MoreCharts, RevenueChart } from './Charts'
import { Hint, Term } from './Hint'
import type { TermKey } from '../glossary'
import { compactMoney, date, entityKind, money, number, percent, riskName, riskTone, statusName, verdictTone, zskName } from '../format'
import type {
  AlternativesResponse,
  AuthState,
  Comparison,
  ComparisonRow,
  ContractorBlocks,
  DataSet,
  FactPack,
  Message,
  MessageBlocks,
  NextStep,
  Profile,
  RolePreset,
  Session,
} from '../types'

// Подписи описывают, что клиент увидит, а не как раздел называется внутри:
// значения (value) — это пресеты бэкенда и меняться от подписей не должны.
// hint выводится при наведении: без него кнопки читались как набор ярлыков,
// и клиент не понимал, что произойдёт по нажатию (client_path_ideas.md §3).
const ROLES: Array<{ value: RolePreset; label: string; hint: string }> = [
  { value: 'general', label: 'Общий обзор', hint: 'Сбалансированный разбор без перекоса в одну тему' },
  { value: 'finance', label: 'Финансы', hint: 'Акцент на деньгах: динамика выручки, обязательства, долговая нагрузка' },
  { value: 'legal', label: 'Суды и взыскания', hint: 'Акцент на действующих взысканиях, истории производств и арбитраже' },
  { value: 'security', label: 'Статус и владельцы', hint: 'Акцент на статусе в ЕГРЮЛ, отметках ФНС, владельцах и связях' },
  { value: 'activity', label: 'Чем занимается', hint: 'Акцент на видах деятельности, лицензиях, проверках и закупках' },
]

/** Карточки на стартовом экране (client_path_ideas.md §1).
 *
 *  Карточка задаёт ДВЕ вещи: готовую фразу в поле (она и определяет, один
 *  контрагент или несколько) и вектор анализа. Данных карточка не подгружает —
 *  углублённые разборы предлагаются подсказками после первого ответа (§8).
 *
 *  Векторные карточки дублируют ряд кнопок под полем ввода, и это сознательно:
 *  на пустом экране карточка с пояснением ориентирует быстрее, чем кнопка,
 *  подсказка к которой видна только при наведении.
 *
 *  Сценарий — разбор или сравнение — выбирает роутер по числу ИНН в отправленном
 *  сообщении, а не карточка.
 */
type ScenarioCard = {
  key: string
  title: string
  hint: string
  role: RolePreset
  draft: string
  primary: boolean
}

const SCENARIOS: ScenarioCard[] = [
  {
    key: 'check',
    title: 'Проверить контрагента',
    hint: 'Вердикт, риски, сильные стороны и динамика выручки по одному ИНН',
    role: 'general',
    draft: 'Проверь контрагента по ИНН ',
    primary: true,
  },
  {
    key: 'compare',
    title: 'Сравнить нескольких',
    hint: 'Таблица по 2–10 ИНН: деньги, суды, взыскания и вердикт по каждому',
    role: 'general',
    draft: 'Сравни контрагентов по ИНН: ',
    primary: true,
  },
  {
    key: 'finance',
    title: 'Оценить финансы и долги',
    hint: 'Выручка и прибыль по годам, чистые активы, долговая нагрузка',
    role: 'finance',
    draft: 'Оцени финансовое состояние контрагента по ИНН ',
    primary: true,
  },
  {
    key: 'legal',
    title: 'Проверить суды и взыскания',
    hint: 'Действующие взыскания отдельно от истории, арбитраж по годам',
    role: 'legal',
    draft: 'Проверь суды и взыскания у контрагента с ИНН ',
    primary: true,
  },
  {
    key: 'security',
    title: 'Узнать, кто за компанией',
    hint: 'Статус в ЕГРЮЛ, отметки ФНС, владельцы, связанные компании',
    role: 'security',
    draft: 'Кто стоит за компанией с ИНН ',
    primary: false,
  },
  {
    key: 'activity',
    title: 'Узнать, чем занимается',
    hint: 'Виды деятельности, лицензии, проверки и госзакупки',
    role: 'activity',
    draft: 'Расскажи, чем занимается контрагент с ИНН ',
    primary: false,
  },
]

const STAGE_LABELS: Record<string, string> = {
  prefetch: 'Собираю данные',
  verdict: 'Считаю вердикт',
  context: 'Собираю контекст',
  waiting_limit: 'Ожидаю окно модели',
  llm: 'Пишу ответ',
  tools: 'Уточняю по данным',
  repair: 'Проверяю ответ',
  persist: 'Сохраняю',
}

const FOCUSED_STAGE_LABELS: Record<string, string> = {
  finance: 'Углубляю финансовый разбор',
  legal: 'Углубляю юридический разбор',
  security: 'Углубляю проверку безопасности',
  activity: 'Углубляю разбор деятельности',
}

function stageLabel(stage: string) {
  if (stage.startsWith('focused_')) {
    return FOCUSED_STAGE_LABELS[stage.slice('focused_'.length)] || 'Углубляю разбор'
  }
  return STAGE_LABELS[stage] || stage
}

type Props = {
  auth: AuthState
  profile: Profile | null
  sessions: Session[]
  activeSession: Session | null
  messages: Message[]
  currentPack: FactPack | null
  loading: boolean
  onLogout: () => void
  onCreateSession: () => Promise<void>
  onSelectSession: (session: Session) => Promise<void>
  onDeleteSession: (session: Session) => Promise<void>
  onSessionUpdated: (session: Session) => void
  onChatCompleted: (messages: Message[], pack: FactPack | null, session: Session) => void
  hasMore: boolean
  onLoadEarlier: () => Promise<void>
}

type IconName =
  | 'briefcase' | 'card' | 'chevron' | 'close' | 'compare' | 'contractors'
  | 'download' | 'gear' | 'lock' | 'logo' | 'payment' | 'plus' | 'search'
  | 'send' | 'shield' | 'spark' | 'statement' | 'trash' | 'users' | 'arrow'

function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    logo: <><path d="M5 19 12 4l7 15" /><path d="M8 14h8" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    payment: <><rect x="3" y="6" width="18" height="13" rx="2" /><path d="M3 10h18M7 15h4" /></>,
    statement: <><path d="M7 3h8l4 4v14H7z" /><path d="M15 3v5h5M10 13h6M10 17h5" /></>,
    card: <><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18" /></>,
    contractors: <><circle cx="9" cy="8" r="3" /><circle cx="17" cy="9" r="2" /><path d="M3 19c0-4 2-6 6-6s6 2 6 6M15 14c3 0 5 2 5 5" /></>,
    lock: <><rect x="5" y="10" width="14" height="11" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></>,
    briefcase: <><rect x="3" y="7" width="18" height="12" rx="2" /><path d="M9 7V5h6v2M3 12h18" /></>,
    shield: <path d="M12 3 20 6v5c0 5-3 8-8 10-5-2-8-5-8-10V6z" />,
    users: <><circle cx="8" cy="8" r="3" /><circle cx="17" cy="9" r="2" /><path d="M2 20c0-5 2-7 6-7s6 2 6 7M15 14c3 0 5 2 5 6" /></>,
    search: <><circle cx="10" cy="10" r="6" /><path d="m15 15 5 5" /></>,
    spark: <><path d="m12 3 1.7 5.3L19 10l-5.3 1.7L12 17l-1.7-5.3L5 10l5.3-1.7Z" /><path d="m18 16 .7 2.3L21 19l-2.3.7L18 22l-.7-2.3L15 19l2.3-.7Z" /></>,
    gear: <><circle cx="12" cy="12" r="3" /><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.5-2.4 1a8 8 0 0 0-1.7-1L14.5 3h-5L9 6a8 8 0 0 0-1.7 1L5 6 3 9.5 5 11a7 7 0 0 0 0 2l-2 1.5L5 18l2.3-1a8 8 0 0 0 1.7 1l.5 3h5l.4-3a8 8 0 0 0 1.7-1l2.4 1 2-3.5-2.1-1.5a7 7 0 0 0 .1-1Z" /></>,
    arrow: <><path d="M5 12h13" /><path d="m12 6 6 6-6 6" /></>,
    trash: <><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" /><path d="M10 11v6M14 11v6" /></>,
    send: <><path d="m4 4 17 8-17 8 3-8-3-8Z" /><path d="M7 12h14" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    download: <><path d="M12 3v12m0 0 4-4m-4 4-4-4" /><path d="M5 20h14" /></>,
    compare: <><path d="M8 5h12M8 12h9M8 19h6" /><path d="m3 5 1 1 2-2m-3 8 1 1 2-2m-3 8 1 1 2-2" /></>,
    chevron: <path d="m9 6 6 6-6 6" />,
  }
  return (
    <svg className="app-icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  )
}

const NAVIGATION: Array<{ label: string; icon: IconName; active?: boolean }> = [
  { label: 'Новый платёж', icon: 'plus' },
  { label: 'Платежи в работе', icon: 'payment' },
  { label: 'Импорт реестров', icon: 'statement' },
  { label: 'Выписка', icon: 'statement' },
  { label: 'Счета', icon: 'card' },
  { label: 'Контрагенты', icon: 'contractors', active: true },
]

const SERVICES: Array<{ title: string; text: string; icon: IconName; ai?: boolean }> = [
  { title: 'Мои контрагенты', text: 'Работайте с действующими и добавляйте новых', icon: 'users' },
  { title: 'Подбор новых', text: 'Ищите товары и услуги, а также продвигайте свои', icon: 'search' },
  { title: 'Проверка на надёжность', text: 'Оцените риски с помощью Альфа-Банка', icon: 'shield' },
  { title: 'Проверка с ИИ', text: 'Получите анализ рисков и задайте вопросы по отчёту', icon: 'spark', ai: true },
]

function BusinessSidebar() {
  return (
    <aside className="business-sidebar">
      <div className="alfa-wordmark">АльфаБанк</div>
      <nav aria-label="Основное меню">
        {NAVIGATION.map((item) => (
          <Button
            key={item.label}
            view="transparent"
            size={32}
            block
            className={`business-nav-item ${item.active ? 'is-active' : ''}`}
            leftAddons={<Icon name={item.icon} size={15} />}
            aria-current={item.active ? 'page' : undefined}
            disabled={!item.active}
          >
            {item.label}
          </Button>
        ))}
      </nav>
      <p className="nav-section-title">Мои сервисы <span>+</span></p>
      <nav aria-label="Мои сервисы">
        {[
          { label: 'Аккредитивы', icon: 'briefcase' },
          { label: 'Альфа-Безопасность', icon: 'lock', badge: 'НОВОЕ' },
          { label: 'Заказ наличных', icon: 'card' },
          { label: 'Справки', icon: 'statement' },
          { label: 'Карты', icon: 'card' },
          { label: 'Депозиты', icon: 'briefcase' },
        ].map(({ label, icon, badge }) => (
          <Button
            key={label}
            view="transparent"
            size={32}
            block
            className="business-nav-item"
            leftAddons={<Icon name={icon as IconName} size={15} />}
            rightAddons={badge ? <span className="nav-badge">{badge}</span> : undefined}
            disabled
          >
            {label}
          </Button>
        ))}
      </nav>
      <div className="sidebar-spacer" />
      <Button view="secondary" colors="inverted" size={40} block className="all-services" disabled>
        Все сервисы и продукты
      </Button>
      <small>Альфа-Бизнес для смартфона</small>
      <small>Предыдущая версия</small>
    </aside>
  )
}

/** Нулевой лимит на бэкенде значит «без ограничения» (profiles.UNLIMITED):
 *  шкалу в этом случае рисовать нечем, а счётчик израсходованного остаётся. */
function Quota({ used, limit }: { used: number; limit: number }) {
  if (limit === 0) {
    return (
      <div className="quota">
        <div><span>Проверок сделано</span><b>{used}</b></div>
      </div>
    )
  }
  return (
    <div className="quota">
      <div><span>Проверки</span><b>{used} / {limit}</b></div>
      <div className="quota-track">
        <span style={{ width: `${Math.min(100, (used / limit) * 100)}%` }} />
      </div>
    </div>
  )
}

function ProfileMenu({ profile, onLogout }: { profile: Profile | null; onLogout: () => void }) {
  return (
    <div className="profile-menu" id="profile-menu" role="dialog" aria-label="Личный кабинет">
      <div className="profile-heading">
        <span className="avatar">{profile?.login.slice(0, 1).toUpperCase() || 'A'}</span>
        <div>
          <strong>{profile?.display_name || profile?.login || 'Пользователь'}</strong>
          <small>Тариф «{profile?.tariff_label || 'Бесплатный'}»</small>
        </div>
      </div>
      <Quota used={profile?.requests_used ?? 0} limit={profile?.requests_limit ?? 0} />
      <div className="profile-stat"><span>Создано отчётов</span><b>{profile?.reports_generated ?? 0}</b></div>
      <p className="placeholder-note">Управление тарифом появится позже.</p>
      <Button view="secondary" size={40} block onClick={onLogout}>Выйти</Button>
    </div>
  )
}

function ServiceCard({ title, text, icon, ai }: { title: string; text: string; icon: IconName; ai?: boolean }) {
  return (
    <div className={`service-card ${ai ? 'service-card-ai' : ''}`}>
      <span className="service-icon"><Icon name={icon} size={20} /></span>
      <span className="service-copy">
        <strong>{title}</strong>
        <span>{text}</span>
      </span>
    </div>
  )
}

function ContractorsPage({ aiPanel }: { aiPanel: ReactNode }) {
  return (
    <div className="contractors-page">
      <h1>Контрагенты</h1>
      <section className="services-grid" aria-label="Сервисы для контрагентов">
        {SERVICES.map((service) => (
          <ServiceCard key={service.title} {...service} />
        ))}
      </section>

      {aiPanel}
    </div>
  )
}


// Колонки сводки сравнения. Состав фиксирован, а порядок строк приходит с бэкенда
// уже отсортированным по выбранному фокусу анализа (selection.COLUMN_ORDER).
//
// Порядок колонок: сначала показатели, ради которых сравнение и затевали,
// светофоры — в конец. Вердикт стоит отдельной колонкой сразу за именем: он
// один отвечает на вопрос пользователя, а риск и ЗСК его лишь обосновывают
// (known_issues.md §18).
type CompareColumn = {
  key: string
  label: string
  term?: TermKey
  render: (row: ComparisonRow) => string
}

const COMPARE_COLUMNS: CompareColumn[] = [
  { key: 'revenue', label: 'Выручка', render: (r) => compactMoney(r.revenue as number | null) },
  { key: 'profit', label: 'Прибыль', render: (r) => compactMoney(r.profit as number | null) },
  {
    key: 'net_assets',
    label: 'Чистые активы',
    term: 'net_assets',
    render: (r) => compactMoney(r.net_assets as number | null),
  },
  {
    key: 'debt_to_net_assets',
    label: 'Долг к активам',
    term: 'debt_to_net_assets',
    render: (r) => percent(r.debt_to_net_assets as number | null),
  },
  {
    key: 'execproc_active',
    label: 'Взыскания',
    term: 'execproc_active',
    render: (r) => number(r.execproc_active as number | null),
  },
  {
    key: 'arbitration_total',
    label: 'Судов всего',
    term: 'arbitration_pending',
    render: (r) => number(r.arbitration_total as number | null),
  },
  {
    key: 'arbitration_pending_defendant',
    label: 'Текущих исков',
    term: 'arbitration_pending',
    render: (r) => number(r.arbitration_pending_defendant as number | null),
  },
  {
    key: 'negative_factors',
    label: 'Негативных',
    term: 'negative_factors',
    render: (r) => number(r.negative_factors as number | null),
  },
  { key: 'zsk_risk_level', label: 'ЗСК', term: 'zsk', render: (r) => zskName(r.zsk_risk_level as never) },
  {
    key: 'risk_level',
    label: 'Риск',
    term: 'risk_level',
    render: (r) => riskName((r.risk_level as never) ?? null),
  },
]

function ComparisonTable({ data }: { data: Comparison }) {
  const rows = data.matrix ?? []
  if (rows.length === 0) return null
  const verdicts = new Map((data.verdicts ?? []).map((item) => [item.inn, item.verdict]))
  return (
    <div className="msg-compare">
      <div className="msg-compare-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Контрагент</th>
              <th scope="col"><Term term="verdict">Вердикт</Term></th>
              {COMPARE_COLUMNS.map((column) => (
                <th key={column.key} scope="col">
                  {column.term ? (
                    <Term term={column.term}>{column.label}</Term>
                  ) : (
                    column.label
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={String(row.inn)}>
                <th scope="row">
                  {String(row.short_name ?? row.inn)}
                  <small>ИНН {String(row.inn)}</small>
                </th>
                <td>
                  {verdicts.has(String(row.inn)) ? (
                    <span className={`reliability-badge reliability-${verdictTone(verdicts.get(String(row.inn)))}`}>
                      {verdicts.get(String(row.inn))}
                    </span>
                  ) : '—'}
                </td>
                {COMPARE_COLUMNS.map((column) => (
                  <td key={column.key}>{column.render(row)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(data.differences ?? []).length > 0 && (
        <ul className="msg-diff">
          {data.differences!.map((item) => (
            <li key={item.metric}>{item.text}</li>
          ))}
        </ul>
      )}
      {(data.not_found ?? []).length > 0 && (
        <p className="msg-missing">Нет в базе: {data.not_found!.join(', ')}</p>
      )}
    </div>
  )
}

/** Подбор альтернативы (client_path_ideas.md §7).
 *
 *  Кандидаты отбираются по открытым реестрам, оценки банка в ответе нет:
 *  её клиент получает обычной проверкой, нажав «Проверить». Сколько нашлось
 *  всего, не показываем — это раскрыло бы объём базы.
 */
function Alternatives({ inn, token, onPick }: {
  inn: string
  token: string
  onPick: (inn: string) => void
}) {
  const [data, setData] = useState<AlternativesResponse | null>(null)
  const [busy, setBusy] = useState(true)
  const [failed, setFailed] = useState(false)

  const load = async (sameRegion: boolean) => {
    setBusy(true)
    setFailed(false)
    try {
      setData(await api.alternatives(token, inn, sameRegion))
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  // Подбор начинается сразу по нажатию подсказки: вторая кнопка с тем же
  // текстом сбивала с толку — клиент не понимал, что от него хотят (§7).
  useEffect(() => {
    void load(true)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inn])

  if (failed) {
    return (
      <div className="alt-block">
        <p className="alt-empty">Не удалось подобрать.</p>
        <Button view="secondary" size={32} onClick={() => void load(true)}>Попробовать снова</Button>
      </div>
    )
  }

  if (data === null) {
    return <div className="alt-block"><p className="alt-empty">Подбираю…</p></div>
  }

  const where = data.same_region && data.region ? `в регионе «${data.region}»` : 'по всей стране'
  return (
    <div className="alt-block">
      {data.items.length > 0 ? (
        <>
          <p className="alt-lead">
            Вот кто ещё занимается тем же {where}. Все — действующие компании,
            без банкротства, без действующих взысканий и без незавершённых исков
            к ним. По уровню риска я их пока не смотрел.
          </p>
          <div className="alt-cards">
            {data.items.map((item) => (
              <div key={item.inn} className="alt-card">
                <b>{item.short_name}</b>
                <small>
                  ИНН {item.inn}
                  {item.region ? ` · ${item.region}` : ''}
                  {item.main_okved ? ` · ${item.main_okved}` : ''}
                </small>
                <Button view="primary" size={32} loading={busy} onClick={() => onPick(item.inn)}>
                  Проверить
                </Button>
              </div>
            ))}
          </div>
          <p className="alt-note">
            Нажмите «Проверить» — разберу компанию так же, как первую: с вердиктом,
            рисками и оценкой банка.
          </p>
        </>
      ) : (
        <p className="alt-empty">
          {data.same_region && data.region
            ? `В регионе «${data.region}» подходящих компаний того же профиля не нашлось.`
            : 'Подходящих компаний того же профиля не нашлось.'}
        </p>
      )}
      {data.can_widen && (
        <Button view="secondary" size={32} loading={busy} onClick={() => void load(false)}>
          Поискать по всей стране
        </Button>
      )}
    </div>
  )
}

/** Подсказки следующего шага (§4). Клиент не изобретает вопрос, а выбирает. */
function NextSteps({ steps, inn, token, onSend, onDraft }: {
  steps: NextStep[]
  inn: string | null
  token: string
  onSend: (text: string, sets?: DataSet[]) => void
  onDraft: (text: string) => void
}) {
  const [openAction, setOpenAction] = useState<string | null>(null)
  if (steps.length === 0) return null
  const pick = (step: NextStep) => {
    if (step.kind === 'action') return setOpenAction(step.code)
    const text = step.prompt ?? step.label
    // draft — единственный случай, когда вопрос неполон: клиенту надо
    // дописать второй ИНН, отправлять такое сразу нельзя.
    return step.kind === 'draft'
      ? onDraft(text)
      : onSend(text, step.dataset ? [step.dataset] : [])
  }
  return (
    <div className="next-steps">
      <div className="next-steps-row">
        {steps.map((step) => (
          <Button
            key={step.code}
            view="transparent"
            size={32}
            className="next-step"
            onClick={() => pick(step)}
          >
            {step.label}
          </Button>
        ))}
      </div>
      {openAction === 'alternatives' && inn && (
        <Alternatives inn={inn} token={token} onPick={(value) => onSend(`Проверь контрагента по ИНН ${value}`)} />
      )}
    </div>
  )
}

function ContractorBlockList({ rows }: { rows: ContractorBlocks[] }) {
  if (rows.length === 0) return null
  return (
    <div className="msg-per-contractor">
      {rows.map((row) => (
        <section key={row.inn} className="msg-contractor">
          <h4>{row.short_name}</h4>
          <BlockList title="Риски" tone="danger" items={row.key_risks} empty={NO_RISKS} />
          <BlockList title="В порядке" tone="good" items={row.positives} empty={NO_POSITIVES} />
        </section>
      ))}
    </div>
  )
}

/* Пустой список и отсутствие блока выглядели одинаково: клиент не мог понять,
   рисков нет или они не подгрузились (known_issues.md §15.5). Поэтому пустоту
   проговариваем явно — но только там, где точно известно, что проверка прошла. */
const NO_RISKS = 'По статусу, судам, взысканиям и реестрам ФНС отметок нет.'
const NO_POSITIVES = 'Отдельных плюсов в отчёте не нашлось.'

function BlockList({ title, tone, items, empty }: {
  title: string
  tone: string
  items: string[]
  empty?: string
}) {
  if (items.length === 0 && !empty) return null
  return (
    <section className={`msg-block msg-block-${tone}`}>
      <h4>{title}</h4>
      {items.length === 0 ? (
        <p className="msg-block-empty">{empty}</p>
      ) : (
        <ul>
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Стартовый экран (client_path_ideas.md §2).
 *
 *  Было «Кого проверим? Введите ИНН» — клиент не знал ни об одной возможности
 *  системы. Четыре блока: что это, с чего начать, с чем помогу, чего не умею.
 *  Последний кажется лишним, но экономит разочарование на втором сообщении
 *  и сразу задаёт рамку ответственности.
 *
 *  Примеров с реальными ИНН здесь нет намеренно: подставить клиенту компанию
 *  из базы значит показать её состав.
 */
function WelcomeScreen({ onPick }: { onPick: (card: ScenarioCard) => void }) {
  const [all, setAll] = useState(false)
  const cards = all ? SCENARIOS : SCENARIOS.filter((card) => card.primary)
  return (
    <div className="ai-welcome">
      <h3>Разберу отчёт по контрагенту и отвечу на вопросы по нему</h3>
      <p className="welcome-start">
        Вставьте ИНН организации или предпринимателя — или несколько через запятую,
        если нужно сравнить.
      </p>

      <div className="welcome-cards">
        {cards.map((card) => (
          <button key={card.key} type="button" className="welcome-card" onClick={() => onPick(card)}>
            <b>{card.title}</b>
            <small>{card.hint}</small>
          </button>
        ))}
      </div>
      {!all && (
        <Button view="transparent" size={32} onClick={() => setAll(true)}>
          Показать ещё {SCENARIOS.length - cards.length}
        </Button>
      )}

      {/* Свёрнуто: на старте важнее сценарии, развёрнутыми списками они срезали
          карточки за нижний край (§2). Про границы — «не ищу по названию»,
          «не оцениваю сделку» — здесь больше нет: это говорится в ответе на
          сообщение без ИНН, то есть тогда, когда клиент спросил. */}
      <details className="welcome-more">
        <summary>Что делают кнопки под полем ввода</summary>
        <ul className="welcome-notes">
          <li>
            Задают, на чём сосредоточиться в разборе: финансы, суды и взыскания,
            статус и владельцы, чем занимается. По умолчанию — общий обзор.
          </li>
          <li>
            Данных они не добавляют, только меняют акцент ответа. Углубиться
            в тему предложу отдельной кнопкой после разбора.
          </li>
        </ul>
      </details>
    </div>
  )
}

/** Шапка сообщения. Вердикт без имени контрагента безадресен: в сессии их
 *  несколько, а ответ на уточнение вообще не называет, о ком он (§15.6). */
function MessageHeader({ blocks }: { blocks: MessageBlocks }) {
  const compared = (blocks.per_contractor ?? []).map((row) => row.short_name)
  const subject = blocks.subject || (compared.length > 0 ? compared.join(' · ') : null)
  if (!subject && !blocks.verdict) return null
  return (
    <header className="msg-verdict">
      {blocks.verdict && (
        <span className={`reliability-badge reliability-${verdictTone(blocks.verdict)}`}>
          {blocks.verdict}
          <Hint term="verdict" />
        </span>
      )}
      <small>
        {subject && <b className="msg-subject">{subject}</b>}
        {subject && blocks.inn ? ` · ИНН ${blocks.inn}` : ''}
        {blocks.verdict && (
          <>
            {subject ? ' · ' : ''}
            <Term term="risk_level">{riskName(blocks.risk_level ?? null)}</Term>
            {' · '}
            <Term term="zsk">ЗСК {zskName(blocks.zsk_risk_level)}</Term>
          </>
        )}
      </small>
    </header>
  )
}

/** Сообщение ассистента: шапка с вердиктом, текст, затем структурные блоки.
 *  Один путь отрисовки для свежего ответа и для истории — блоки приходят в meta. */
function AssistantMessage({ content, blocks, degraded, token, onSend, onDraft }: {
  content: string
  blocks: MessageBlocks
  degraded?: boolean
  token: string
  onSend: (text: string, sets?: DataSet[]) => void
  onDraft: (text: string) => void
}) {
  const risks = blocks.key_risks ?? []
  const positives = blocks.positives ?? []
  const followups = blocks.followups ?? []
  const perContractor = blocks.per_contractor ?? []
  return (
    <>
      <MessageHeader blocks={blocks} />
      <p>{content}</p>
      {(blocks.datasets ?? []).length > 0 && (
        <p className="msg-datasets">Дополнительно поднял: {(blocks.datasets ?? []).join(', ').toLowerCase()}</p>
      )}
      {blocks.report && <RevenueChart pack={blocks.report} />}
      {blocks.comparison && <ComparisonTable data={blocks.comparison} />}
      {perContractor.length > 0 ? (
        <ContractorBlockList rows={perContractor} />
      ) : (
        <>
          <BlockList title="Риски" tone="danger" items={risks} empty={NO_RISKS} />
          <BlockList title="В порядке" tone="good" items={positives} empty={NO_POSITIVES} />
        </>
      )}
      {followups.length > 0 && (
        <section className="msg-block msg-block-neutral">
          <h4>Что запросить у контрагента</h4>
          <ul>
            {followups.map((item) => (
              <li key={item.trigger}>
                {item.question}
                <small>{item.reason}</small>
              </li>
            ))}
          </ul>
        </section>
      )}
      {blocks.report && <MoreCharts pack={blocks.report} />}
      {degraded && <small>ИИ-разбор недоступен, показаны данные отчёта</small>}
      <NextSteps
        steps={blocks.next_steps ?? []}
        inn={blocks.inn ?? null}
        token={token}
        onSend={onSend}
        onDraft={onDraft}
      />
    </>
  )
}

function Dossier({ pack }: { pack: FactPack | null }) {
  if (!pack) {
    return (
      <aside className="ai-dossier ai-dossier-empty">
        <span><Icon name="statement" size={28} /></span>
        <h3>Здесь появится отчёт</h3>
        <p>Введите ИНН в чате, чтобы собрать сведения о контрагенте.</p>
      </aside>
    )
  }
  const lastFinancial = [...pack.financials.years].reverse().find((item) => item.proceeds != null)
  return (
    <aside className="ai-dossier">
      <header>
        <span className={`reliability-badge reliability-${riskTone(pack.verdict_basis.risk_level)}`}>
          {riskName(pack.verdict_basis.risk_level)}
        </span>
        <h3>{pack.short_name}</h3>
        <p>{entityKind(pack.profile.entity_kind)} · ИНН {pack.inn} · ОГРН {pack.ogrn}</p>
        <div className="zsk-line">
          <span><Term term="zsk">Оценка ЗСК</Term></span>
          <b>{pack.verdict_basis.zsk_risk_level || 'Нет данных'}</b>
        </div>
      </header>
      {pack.discrepancies.length > 0 && (
        <section className="report-warning">
          <strong><Term term="discrepancies">Требует внимания</Term></strong>
          {pack.discrepancies.map((item) => <p key={item.code}>{item.text}</p>)}
        </section>
      )}
      <details open>
        <summary>Финансовые показатели</summary>
        <dl>
          <div><dt>Выручка {lastFinancial?.year || ''}</dt><dd>{money(lastFinancial?.proceeds)}</dd></div>
          <div><dt>Прибыль {lastFinancial?.year || ''}</dt><dd>{money(lastFinancial?.profit)}</dd></div>
        </dl>
      </details>
      <details open>
        <summary>Риски и споры</summary>
        <dl>
          <div>
            <dt><Term term="execproc_active">Действующие взыскания</Term></dt>
            <dd>{number(pack.execution_proceedings.active)}</dd>
          </div>
          <div><dt>Сумма взысканий</dt><dd>{money(pack.execution_proceedings.active_amount)}</dd></div>
          <div>
            <dt><Term term="arbitration_pending">Судебных дел, всего</Term></dt>
            <dd>{number(pack.arbitration.total_count)}</dd>
          </div>
          <div>
            <dt><Term term="negative_factors">Негативные факторы</Term></dt>
            <dd>{number(pack.risk_factors.negative_total)}</dd>
          </div>
        </dl>
      </details>
      <details>
        <summary>Общая информация</summary>
        <dl>
          <div>
            <dt><Term term="egrul_status">Статус</Term></dt>
            <dd>{statusName(pack.profile.status)}</dd>
          </div>
          <div><dt>Регистрация</dt><dd>{date(pack.profile.registered)}</dd></div>
          <div><dt>Руководитель</dt><dd>{pack.profile.auth_person?.name || 'Нет данных'}</dd></div>
          <div>
            <dt><Term term="okved">Вид деятельности</Term></dt>
            <dd>{pack.profile.main_okved.description || 'Нет данных'}</dd>
          </div>
        </dl>
      </details>
      <footer><Term term="as_of">Данные на {date(pack.as_of)}</Term></footer>
    </aside>
  )
}

function AiPanel({
  auth,
  profile,
  sessions,
  activeSession,
  messages,
  currentPack,
  loading,
  onCreateSession,
  onSelectSession,
  onDeleteSession,
  onSessionUpdated,
  onChatCompleted,
  hasMore,
  onLoadEarlier,
}: Omit<Props, 'onLogout'>) {
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [mobileView, setMobileView] = useState<'chat' | 'report'>('chat')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [reportOpen, setReportOpen] = useState(true)
  const [draftUser, setDraftUser] = useState<string | null>(null)
  const [draftAnswer, setDraftAnswer] = useState('')
  const [stage, setStage] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  // Карточка на старте подставляет черновик — курсор должен встать сразу
  // за ним, чтобы клиенту оставалось только вписать ИНН.
  const composerRef = useRef<HTMLTextAreaElement>(null)
  const role = activeSession?.role_preset || 'general'
  const orderedMessages = useMemo(
    () => messages.filter((item) => item.role === 'user' || item.role === 'assistant'),
    [messages],
  )

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    setError(null)
    setNotice(null)
  }, [activeSession?.id])

  const removeSession = async (session: Session) => {
    setConfirmDelete(null)
    try {
      await onDeleteSession(session)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось удалить проверку.')
    }
  }

  const changeRole = async (nextRole: RolePreset) => {
    if (!activeSession || nextRole === role) return
    try {
      onSessionUpdated(await api.updateRole(auth.token, activeSession.id, nextRole))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не удалось сменить роль.')
    }
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void send(message)
  }

  /** Отправка произвольного текста, а не только содержимого поля ввода:
   *  подсказка следующего шага и кнопка «Проверить» шлют готовый вопрос
   *  сразу, без промежуточного клика по «отправить» (§4, §7). */
  const send = async (text: string, sets?: DataSet[]) => {
    if (!activeSession || !text.trim() || sending) return
    const content = text.trim()
    const turnSets = sets ?? []
    const requestSessionId = activeSession.id
    const controller = new AbortController()
    abortRef.current = controller
    setSending(true)
    setError(null)
    setNotice(null)
    setDraftUser(content)
    setDraftAnswer('')
    setStage(null)
    setMessage('')
    try {
      await api.chatStream(
        auth.token,
        activeSession.id,
        content,
        role,
        turnSets,
        {
          onStage: (name) => setStage(name),
          onDelta: (text) => setDraftAnswer((value) => value + text),
          onDone: (response) => {
            setDraftUser(null)
            setDraftAnswer('')
            setStage(null)
            if (response.session.id !== requestSessionId) return
            onChatCompleted(response.messages, response.report, response.session)
            setNotice(response.notice)
            if (response.report) setMobileView('report')
          },
          onError: (detail, degraded) => {
            if (!degraded) setError(detail)
          },
        },
        controller.signal,
      )
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === 'AbortError') {
        setError('Показ остановлен. Расчёт продолжится на сервере и появится после повторного открытия проверки.')
      } else {
        setError(reason instanceof ApiError ? reason.message : 'Сервис временно недоступен.')
        setMessage((value) => value || content)
      }
    } finally {
      abortRef.current = null
      setSending(false)
      setStage(null)
      setDraftUser(null)
      setDraftAnswer('')
    }
  }

  const stop = () => abortRef.current?.abort()

  return (
    <section className="ai-panel" aria-labelledby="ai-panel-title">
      <header className="ai-panel-header">
        <div>
          <span className="ai-title-icon"><Icon name="spark" size={20} /></span>
          <div><h2 id="ai-panel-title">Проверка с ИИ</h2><p>Анализ контрагента по данным отчёта</p></div>
        </div>
        <div className="ai-header-actions">
          <Button
            view="secondary"
            size={40}
            leftAddons={<Icon name="download" size={16} />}
            disabled={!currentPack || !activeSession}
            onClick={() => activeSession && void api.exportReport(auth.token, activeSession.id)}
          >
            Скачать JSON
          </Button>
        </div>
      </header>

        <nav className="ai-mobile-tabs" aria-label="Чат и отчёт" role="tablist">
          <Button role="tab" aria-selected={mobileView === 'chat'} view={mobileView === 'chat' ? 'primary' : 'transparent'} size={32} onClick={() => setMobileView('chat')}>Чат</Button>
          <Button role="tab" aria-selected={mobileView === 'report'} view={mobileView === 'report' ? 'primary' : 'transparent'} size={32} onClick={() => setMobileView('report')}>Отчёт</Button>
        </nav>

        <div className={`ai-panel-body ${reportOpen ? '' : 'report-collapsed'}`}>
          <aside className="ai-sessions">
            <Button view="secondary" size={40} block leftAddons={<Icon name="plus" size={16} />} disabled={sending} onClick={() => void onCreateSession()}>
              Новая проверка
            </Button>
            <p>История</p>
            <div>
              {sessions.map((session, index) => (
                <div key={session.id} className={`session-row ${activeSession?.id === session.id ? 'active' : ''}`}>
                  <Button view="transparent" size={48} block disabled={sending} onClick={() => void onSelectSession(session)}>
                    <span><strong>{session.title || `Проверка ${sessions.length - index}`}</strong><small>{date(session.created_at)}</small></span>
                  </Button>
                  {confirmDelete === session.id ? (
                    <div className="session-confirm">
                      <Button view="primary" size={32} onClick={() => void removeSession(session)}>Да</Button>
                      <Button view="secondary" size={32} onClick={() => setConfirmDelete(null)}>Нет</Button>
                    </div>
                  ) : (
                    <Button
                      view="transparent"
                      size={32}
                      className="session-delete"
                      disabled={sending}
                      aria-label={`Удалить проверку ${session.title || ''}`}
                      onClick={() => setConfirmDelete(session.id)}
                    >
                      <Icon name="trash" size={15} />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </aside>

          <section className={`ai-chat ${mobileView !== 'chat' ? 'mobile-panel-hidden' : ''}`}>
            <div className="ai-messages" aria-live="polite">
              <div className="ai-thread">
              {loading && <div className="loading-state"><Spinner visible preset={24} />Загружаем историю</div>}
              {!loading && hasMore && (
                <Button view="secondary" size={32} className="load-earlier" onClick={() => void onLoadEarlier()}>
                  Показать более ранние
                </Button>
              )}
              {!loading && orderedMessages.length === 0 && (
                <WelcomeScreen
                  onPick={(card) => {
                    setMessage(card.draft)
                    void changeRole(card.role)
                    composerRef.current?.focus()
                  }}
                />
              )}
              {orderedMessages.map((item) => (
                <article key={item.id} className={`ai-message ai-message-${item.role}`}>
                  <span>{item.role === 'user' ? 'Вы' : 'ИИ-проверка'}</span>
                  {item.role === 'assistant' ? (
                    <AssistantMessage
                      content={item.content}
                      blocks={item.meta ?? {}}
                      degraded={item.meta?.degraded}
                      token={auth.token}
                      onSend={(text, sets) => void send(text, sets)}
                      onDraft={(text) => {
                        setMessage(text)
                        composerRef.current?.focus()
                      }}
                    />
                  ) : (
                    <p>{item.content}</p>
                  )}
                </article>
              ))}
              {draftUser && (
                <article className="ai-message ai-message-user">
                  <span>Вы</span>
                  <p>{draftUser}</p>
                </article>
              )}
              {(sending || draftAnswer || stage) && (
                <article className="ai-message ai-message-assistant ai-message-streaming">
                  <span>ИИ-проверка</span>
                  {draftAnswer ? <p>{draftAnswer}</p> : null}
                  {stage && (
                    <small className="ai-stage">{stageLabel(stage)}</small>
                  )}
                </article>
              )}
              </div>
            </div>
            <form className="ai-composer" onSubmit={submit}>
              {error && <div className="composer-error" role="alert">{error}</div>}
              {notice && <div className="composer-notice" role="status">{notice}</div>}
              <div className="composer-row">
                <Textarea
                  block
                  autosize
                  ref={composerRef}
                  minRows={1}
                  maxRows={4}
                  placeholder="Вставьте ИНН — или несколько через запятую"
                  value={message}
                  disabled={!activeSession || sending}
                  onChange={(_, payload) => setMessage(payload.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      event.currentTarget.form?.requestSubmit()
                    }
                  }}
                />
                {sending ? (
                  <Button
                    type="button"
                    view="secondary"
                    size={48}
                    className="send-button"
                    aria-label="Остановить"
                    onClick={stop}
                  >
                    <Icon name="close" size={18} />
                  </Button>
                ) : (
                  <Button
                    type="submit"
                    view="accent"
                    size={48}
                    className="send-button"
                    disabled={!activeSession || !message.trim()}
                    aria-label="Отправить"
                  >
                    <Icon name="send" size={20} />
                  </Button>
                )}
              </div>
              {/* Вектор анализа — единственный ряд управления под полем ввода.
                  Данных не добавляет, только меняет акцент ответа; углублённые
                  разборы предлагаются подсказками после ответа (§8). */}
              <div className="composer-quick" role="group" aria-label="На чём сосредоточиться">
                {ROLES.map((item) => (
                  <Button
                    key={item.value}
                    type="button"
                    view={item.value === role ? 'primary' : 'secondary'}
                    size={32}
                    aria-pressed={item.value === role}
                    disabled={!activeSession || sending}
                    title={item.hint}
                    onClick={() => void changeRole(item.value)}
                  >
                    {item.label}
                  </Button>
                ))}
              </div>
              <small>
                Смотрю: {ROLES.find((item) => item.value === role)?.label.toLowerCase()}.
                {profile?.profile === 'extended' ? ' Могу дозапрашивать данные по ходу разбора.' : ''}
              </small>
            </form>
          </section>
        <div className="report-gutter">
          <button
            type="button"
            className="report-toggle"
            onClick={() => setReportOpen(!reportOpen)}
            aria-expanded={reportOpen}
            aria-label={reportOpen ? 'Скрыть отчёт о контрагенте' : 'Показать отчёт о контрагенте'}
            title={reportOpen ? 'Скрыть отчёт' : 'Показать отчёт'}
          >
            <Icon name="arrow" size={16} />
          </button>
        </div>
        <div className={`ai-report-panel ${mobileView !== 'report' ? 'mobile-panel-hidden' : ''}`}>
          <Dossier pack={currentPack} />
        </div>
      </div>
    </section>
  )
}

export function Workspace(props: Props) {
  const {
    auth, profile, sessions, activeSession, messages, currentPack, loading,
    onLogout, onCreateSession, onSelectSession, onDeleteSession, onSessionUpdated, onChatCompleted,
    hasMore, onLoadEarlier,
  } = props
  const [profileOpen, setProfileOpen] = useState(false)
  const profileRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (profileOpen && !profileRef.current?.contains(event.target as Node)) setProfileOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [profileOpen])

  return (
    <div className="business-app">
      <div className="business-shell">
        <BusinessSidebar />
        <main className="business-main">
          <header className="business-mobile-header">
            <span className="alfa-wordmark">АльфаБанк</span>
            <span>Контрагенты</span>
          </header>
          <div className="business-profile" ref={profileRef}>
            <Button
              view="secondary"
              size={40}
              aria-label="Личный кабинет"
              aria-haspopup="dialog"
              aria-expanded={profileOpen}
              aria-controls="profile-menu"
              onClick={() => setProfileOpen(!profileOpen)}
            >
              <Icon name="gear" size={18} />
            </Button>
            {profileOpen && <ProfileMenu profile={profile} onLogout={onLogout} />}
          </div>
          <ContractorsPage
            aiPanel={(
              <AiPanel
                auth={auth}
                profile={profile}
                sessions={sessions}
                activeSession={activeSession}
                messages={messages}
                currentPack={currentPack}
                loading={loading}
                onCreateSession={onCreateSession}
                onSelectSession={onSelectSession}
                onDeleteSession={onDeleteSession}
                onSessionUpdated={onSessionUpdated}
                onChatCompleted={onChatCompleted}
                hasMore={hasMore}
                onLoadEarlier={onLoadEarlier}
              />
            )}
          />
        </main>
      </div>
    </div>
  )
}

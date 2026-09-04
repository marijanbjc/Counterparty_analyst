import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '@alfalab/core-components/button'
import { Spinner } from '@alfalab/core-components/spinner'
import { Textarea } from '@alfalab/core-components/textarea'

import { api, ApiError } from '../api'
import { date, entityKind, money, number, riskName, riskTone } from '../format'
import type {
  AuthState,
  DataSet,
  FactPack,
  Message,
  Profile,
  RolePreset,
  Session,
} from '../types'

const ROLES: Array<{ value: RolePreset; label: string }> = [
  { value: 'general', label: 'Общий' },
  { value: 'finance', label: 'Финансы' },
  { value: 'legal', label: 'Юридический' },
  { value: 'security', label: 'Безопасность' },
  { value: 'activity', label: 'Деятельность' },
]

const DATASETS: Array<{ value: DataSet; label: string }> = [
  { value: 'finance', label: 'Финансы' },
  { value: 'legal', label: 'Юридический' },
  { value: 'security', label: 'Безопасность' },
  { value: 'activity', label: 'Деятельность' },
  { value: 'followups', label: 'Что запросить' },
  { value: 'charts', label: 'Графики' },
]

// Потолок наборов за ход — ExecutionProfile.max_buttons на бэкенде (§8.4).
const MAX_DATASETS: Record<string, number> = { basic: 2, extended: 6 }

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
      <div className="quota">
        <div><span>Запросы</span><b>{profile?.requests_used ?? 0} / {profile?.requests_limit ?? 100}</b></div>
        <div className="quota-track">
          <span style={{ width: `${Math.min(100, ((profile?.requests_used ?? 0) / (profile?.requests_limit || 100)) * 100)}%` }} />
        </div>
      </div>
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
          <span>Оценка ЗСК</span>
          <b>{pack.verdict_basis.zsk_risk_level || 'Нет данных'}</b>
        </div>
      </header>
      {pack.discrepancies.length > 0 && (
        <section className="report-warning">
          <strong>Требует внимания</strong>
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
          <div><dt>Активные взыскания</dt><dd>{number(pack.execution_proceedings.active)}</dd></div>
          <div><dt>Сумма взысканий</dt><dd>{money(pack.execution_proceedings.active_amount)}</dd></div>
          <div><dt>Арбитраж</dt><dd>{number(pack.arbitration.total_count)}</dd></div>
          <div><dt>Негативные факторы</dt><dd>{number(pack.risk_factors.negative_total)}</dd></div>
        </dl>
      </details>
      <details>
        <summary>Общая информация</summary>
        <dl>
          <div><dt>Статус</dt><dd>{pack.profile.status || 'Нет данных'}</dd></div>
          <div><dt>Регистрация</dt><dd>{date(pack.profile.registered)}</dd></div>
          <div><dt>Руководитель</dt><dd>{pack.profile.auth_person?.name || 'Нет данных'}</dd></div>
          <div><dt>ОКВЭД</dt><dd>{pack.profile.main_okved.description || 'Нет данных'}</dd></div>
        </dl>
      </details>
      <footer>Данные на {date(pack.as_of)}</footer>
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
  const [mobileView, setMobileView] = useState<'chat' | 'report'>('chat')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [datasets, setDatasets] = useState<DataSet[]>([])
  const [reportOpen, setReportOpen] = useState(true)
  const settingsRef = useRef<HTMLDivElement>(null)
  const role = activeSession?.role_preset || 'general'
  const maxDatasets = MAX_DATASETS[profile?.profile ?? ''] ?? MAX_DATASETS.basic
  const orderedMessages = useMemo(
    () => messages.filter((item) => item.role === 'user' || item.role === 'assistant'),
    [messages],
  )

  useEffect(() => {
    if (!settingsOpen) return
    const close = (event: PointerEvent) => {
      if (!settingsRef.current?.contains(event.target as Node)) setSettingsOpen(false)
    }
    document.addEventListener('pointerdown', close)
    return () => document.removeEventListener('pointerdown', close)
  }, [settingsOpen])

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

  const toggleDataset = (value: DataSet) => {
    setDatasets((items) => (
      items.includes(value)
        ? items.filter((item) => item !== value)
        : items.length < maxDatasets ? [...items, value] : items
    ))
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!activeSession || !message.trim()) return
    setSending(true)
    setError(null)
    try {
      const content = message.trim()
      const response = await api.chat(auth.token, activeSession.id, content, role, datasets)
      onChatCompleted(response.messages, response.report, response.session)
      setMessage('')
      // Набор действует один ход: следующий вопрос начинается с чистой отметки (§7.4).
      setDatasets([])
      // На переспрос и сравнение отчёта нет — переключать мобильный вид не на что.
      if (response.report) setMobileView('report')
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : 'Сервис временно недоступен.')
    } finally {
      setSending(false)
    }
  }

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
            <Button view="secondary" size={40} block leftAddons={<Icon name="plus" size={16} />} onClick={() => void onCreateSession()}>
              Новая проверка
            </Button>
            <p>История</p>
            <div>
              {sessions.map((session, index) => (
                <div key={session.id} className={`session-row ${activeSession?.id === session.id ? 'active' : ''}`}>
                  <Button view="transparent" size={48} block onClick={() => void onSelectSession(session)}>
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
                <div className="ai-welcome">
                  <span><Icon name="spark" size={24} /></span>
                  <h3>Кого проверим?</h3>
                  <p>Введите ИНН организации или предпринимателя. Отчёт появится справа.</p>
                  <Button view="secondary" size={40} onClick={() => setMessage('Проверь контрагента по ИНН ')}>
                    Ввести ИНН
                  </Button>
                </div>
              )}
              {orderedMessages.map((item) => (
                <article key={item.id} className={`ai-message ai-message-${item.role}`}>
                  <span>{item.role === 'user' ? 'Вы' : 'ИИ-проверка'}</span>
                  <p>{item.content}</p>
                  {item.meta?.degraded && <small>Детерминированный отчёт · без языковой модели</small>}
                </article>
              ))}
              </div>
            </div>
            <form className="ai-composer" onSubmit={submit}>
              {error && <div className="composer-error" role="alert">{error}</div>}
              <div>
                <div className="composer-settings" ref={settingsRef}>
                  <Button
                    view="transparent"
                    size={48}
                    className="settings-button"
                    aria-label={datasets.length > 0
                      ? `Настройки анализа, выбрано наборов: ${datasets.length}`
                      : 'Настройки анализа'}
                    aria-haspopup="menu"
                    aria-expanded={settingsOpen}
                    disabled={!activeSession}
                    onClick={() => setSettingsOpen(!settingsOpen)}
                  >
                    <Icon name="gear" size={18} />
                  </Button>
                  {/* поповер закрыт чаще, чем открыт, — иначе выбранное невидимо */}
                  {datasets.length > 0 && <span className="settings-count" aria-hidden="true">{datasets.length}</span>}
                  {settingsOpen && (
                    <div className="settings-popover" role="menu">
                      <p>Фокус анализа</p>
                      {ROLES.map((item) => (
                        <Button
                          key={item.value}
                          role="menuitemradio"
                          aria-checked={item.value === role}
                          view={item.value === role ? 'primary' : 'transparent'}
                          size={32}
                          block
                          onClick={() => {
                            setSettingsOpen(false)
                            void changeRole(item.value)
                          }}
                        >
                          {item.label}
                        </Button>
                      ))}
                      <p className="settings-divider">Добавить к проверке</p>
                      <div className="settings-sets">
                        {DATASETS.map((item) => {
                          const checked = datasets.includes(item.value)
                          const capped = !checked && datasets.length >= maxDatasets
                          return (
                            <Button
                              key={item.value}
                              role="menuitemcheckbox"
                              aria-checked={checked}
                              view={checked ? 'primary' : 'transparent'}
                              size={32}
                              block
                              disabled={capped}
                              title={capped ? `За один ход дочитывается до ${maxDatasets} наборов` : undefined}
                              onClick={() => toggleDataset(item.value)}
                            >
                              {item.label}
                            </Button>
                          )
                        })}
                      </div>
                      <small className="settings-hint">
                        {datasets.length >= maxDatasets
                          ? `Потолок тарифа: ${maxDatasets} за ход. Снимите отметку, чтобы выбрать другой набор.`
                          : `Отмечено ${datasets.length} из ${maxDatasets}. Действует на одно сообщение.`}
                      </small>
                    </div>
                  )}
                </div>
                <Textarea
                  block
                  autosize
                  minRows={1}
                  maxRows={4}
                  placeholder="Введите ИНН и задачу проверки"
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
                <Button
                  type="submit"
                  view="accent"
                  size={48}
                  className="send-button"
                  loading={sending}
                  disabled={!activeSession || !message.trim()}
                  aria-label="Отправить"
                >
                  <Icon name="send" size={20} />
                </Button>
              </div>
              <small>
                Фокус анализа: {ROLES.find((item) => item.value === role)?.label}. Пока отвечает
                детерминированный backend, агент будет подключён позже.
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

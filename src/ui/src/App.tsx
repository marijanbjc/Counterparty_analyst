import { useCallback, useEffect, useState } from 'react'

import { api } from './api'
import { LoginScreen } from './components/LoginScreen'
import { Workspace } from './components/Workspace'
import type { AuthState, FactPack, Message, Profile, Session } from './types'
import './App.css'

const AUTH_KEY = 'contractor-control-auth'

function readAuth(): AuthState | null {
  try {
    const value = localStorage.getItem(AUTH_KEY)
    return value ? JSON.parse(value) as AuthState : null
  } catch {
    return null
  }
}

function App() {
  const [auth, setAuth] = useState<AuthState | null>(readAuth)
  const [profile, setProfile] = useState<Profile | null>(null)
  const [sessions, setSessions] = useState<Session[]>([])
  const [activeSession, setActiveSession] = useState<Session | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [currentPack, setCurrentPack] = useState<FactPack | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)

  const selectSession = useCallback(async (session: Session, token = auth?.token) => {
    if (!token) return
    setLoading(true)
    try {
      const history = await api.messages(token, session.id)
      setActiveSession(session)
      setMessages(history.items)
      setHasMore(history.has_more)
      const report = await api.sessionReport(token, session.id).catch(() => null)
      setCurrentPack(report?.report ?? null)
    } finally {
      setLoading(false)
    }
  }, [auth?.token])

  const loadEarlier = useCallback(async () => {
    if (!auth || !activeSession || messages.length === 0) return
    const page = await api.messages(auth.token, activeSession.id, 50, messages[0].id)
    setMessages((items) => [...page.items, ...items])
    setHasMore(page.has_more)
  }, [auth, activeSession, messages])

  const bootstrap = useCallback(async (state: AuthState) => {
    setLoading(true)
    try {
      const [userProfile, userSessions] = await Promise.all([
        api.profile(state.token),
        api.sessions(state.token),
      ])
      setProfile(userProfile)
      let available = userSessions
      if (available.length === 0) {
        available = [await api.createSession(state.token)]
      }
      setSessions(available)
      await selectSession(available[0], state.token)
    } catch {
      localStorage.removeItem(AUTH_KEY)
      setAuth(null)
      setLoginError('Сессия истекла. Войдите снова.')
    } finally {
      setLoading(false)
    }
  }, [selectSession])

  useEffect(() => {
    // Авторизация из localStorage — внешний источник состояния приложения.
    // oxlint-disable-next-line react/set-state-in-effect
    if (auth) void bootstrap(auth)
  }, [auth, bootstrap])

  const login = async (loginValue: string, password: string) => {
    setLoading(true)
    setLoginError(null)
    try {
      const state = await api.login(loginValue, password)
      localStorage.setItem(AUTH_KEY, JSON.stringify(state))
      setAuth(state)
    } catch (reason) {
      setLoginError(reason instanceof Error ? reason.message : 'Не удалось войти.')
    } finally {
      setLoading(false)
    }
  }

  const logout = () => {
    localStorage.removeItem(AUTH_KEY)
    setAuth(null)
    setProfile(null)
    setSessions([])
    setActiveSession(null)
    setMessages([])
    setCurrentPack(null)
  }

  const createSession = async () => {
    if (!auth) return
    const created = await api.createSession(auth.token)
    setSessions((items) => [created, ...items])
    await selectSession(created)
  }

  const removeSession = async (target: Session) => {
    if (!auth) return
    await api.deleteSession(auth.token, target.id)
    const rest = sessions.filter((item) => item.id !== target.id)
    setSessions(rest)
    if (activeSession?.id !== target.id) return
    if (rest.length > 0) {
      await selectSession(rest[0])
      return
    }
    const created = await api.createSession(auth.token)
    setSessions([created])
    await selectSession(created)
  }

  const updateSession = (updated: Session) => {
    setSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
    setActiveSession(updated)
  }

  const applyChat = (saved: Message[], pack: FactPack | null, session: Session) => {
    setMessages((items) => [...items, ...saved])
    // Переспрос и сравнение отчёта не приносят — ранее открытый оставляем на месте.
    if (pack) setCurrentPack(pack)
    updateSession(session)
  }

  if (!auth) {
    return <LoginScreen loading={loading} error={loginError} onLogin={login} />
  }

  return (
    <Workspace
      auth={auth}
      profile={profile}
      sessions={sessions}
      activeSession={activeSession}
      messages={messages}
      currentPack={currentPack}
      loading={loading}
      onLogout={logout}
      onCreateSession={createSession}
      onSelectSession={selectSession}
      onDeleteSession={removeSession}
      onSessionUpdated={updateSession}
      onChatCompleted={applyChat}
      hasMore={hasMore}
      onLoadEarlier={loadEarlier}
    />
  )
}

export default App

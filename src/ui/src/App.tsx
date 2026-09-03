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
  const [loading, setLoading] = useState(false)
  const [loginError, setLoginError] = useState<string | null>(null)

  const selectSession = useCallback(async (session: Session, token = auth?.token) => {
    if (!token) return
    setLoading(true)
    try {
      const history = await api.messages(token, session.id)
      setActiveSession(session)
      setMessages(history)
      const lastReport = [...history].reverse().find((item) => item.meta?.report)?.meta?.report
      setCurrentPack(lastReport || null)
    } finally {
      setLoading(false)
    }
  }, [auth?.token])

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

  const updateSession = (updated: Session) => {
    setSessions((items) => items.map((item) => item.id === updated.id ? updated : item))
    setActiveSession(updated)
  }

  const addMessage = (message: Message, pack: FactPack) => {
    setMessages((items) => [...items, message])
    setCurrentPack(pack)
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
      onSessionUpdated={updateSession}
      onMessageAdded={addMessage}
    />
  )
}

export default App

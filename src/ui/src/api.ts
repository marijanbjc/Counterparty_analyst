import type {
  ChatResponse,
  FactPack,
  Message,
  Profile,
  RolePreset,
  Session,
} from './types'

const API_URL = import.meta.env.VITE_API_URL ?? ''

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function errorText(payload: unknown): string {
  if (typeof payload === 'object' && payload && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail
    return typeof detail === 'string' ? detail : JSON.stringify(detail)
  }
  return 'Не удалось выполнить запрос.'
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    let payload: unknown
    try {
      payload = await response.json()
    } catch {
      payload = null
    }
    throw new ApiError(errorText(payload), response.status)
  }
  return response.json() as Promise<T>
}

export const api = {
  login(login: string, password: string) {
    return request<{ user_id: string; token: string; expires_at: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ login, password }),
    }).then(({ token, user_id }) => ({ token, userId: user_id }))
  },

  profile(token: string) {
    return request<Profile>('/api/me', {}, token)
  },

  sessions(token: string) {
    return request<Session[]>('/api/sessions', {}, token)
  },

  createSession(token: string, role_preset: RolePreset = 'general') {
    return request<Session>(
      '/api/sessions',
      { method: 'POST', body: JSON.stringify({ role_preset }) },
      token,
    )
  },

  updateRole(token: string, sessionId: string, role_preset: RolePreset) {
    return request<Session>(
      `/api/sessions/${sessionId}`,
      { method: 'PATCH', body: JSON.stringify({ role_preset }) },
      token,
    )
  },

  messages(token: string, sessionId: string) {
    return request<Message[]>(`/api/sessions/${sessionId}/messages`, {}, token)
  },

  chat(token: string, sessionId: string, message: string, role_preset: RolePreset) {
    return request<ChatResponse>(
      '/api/chat',
      {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, message, role_preset }),
      },
      token,
    )
  },

  contractor(token: string, inn: string, role: RolePreset) {
    return request<FactPack>(
      `/api/contractors/${inn}?role=${role}`,
      {},
      token,
    )
  },

  compare(token: string, inns: string[], role_preset: RolePreset) {
    return request<{ items: FactPack[]; count: number }>(
      '/api/compare',
      { method: 'POST', body: JSON.stringify({ inns, role_preset }) },
      token,
    )
  },

  async exportReport(token: string, sessionId: string, format: 'json' | 'md') {
    const response = await fetch(
      `${API_URL}/api/sessions/${sessionId}/report/export?format=${format}`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!response.ok) throw new ApiError('Отчёт пока недоступен.', response.status)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `report.${format}`
    anchor.click()
    URL.revokeObjectURL(url)
  },
}

import type {
  ChatResponse,
  CompareResult,
  DataSet,
  FactPack,
  MessagePage,
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

function fileNameFrom(disposition: string | null, format: string): string {
  const match = disposition?.match(/filename="([^"]+)"/)
  return match ? match[1] : `report.${format}`
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

  async deleteSession(token: string, sessionId: string) {
    const response = await fetch(`${API_URL}/api/sessions/${sessionId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new ApiError('Не удалось удалить проверку.', response.status)
  },

  messages(token: string, sessionId: string, limit = 50, beforeId?: number) {
    const query = new URLSearchParams({ limit: String(limit) })
    if (beforeId) query.set('before_id', String(beforeId))
    return request<MessagePage>(`/api/sessions/${sessionId}/messages?${query}`, {}, token)
  },

  sessionReport(token: string, sessionId: string) {
    return request<{ report: FactPack }>(`/api/sessions/${sessionId}/report`, {}, token)
  },

  chat(
    token: string,
    sessionId: string,
    message: string,
    role_preset: RolePreset,
    buttons: DataSet[] = [],
  ) {
    return request<ChatResponse>(
      '/api/chat',
      {
        method: 'POST',
        body: JSON.stringify({ session_id: sessionId, message, role_preset, buttons }),
      },
      token,
    )
  },

  async chatStream(
    token: string,
    sessionId: string,
    message: string,
    role_preset: RolePreset,
    buttons: DataSet[] = [],
    handlers: {
      onStage?: (name: string) => void
      onDelta?: (text: string) => void
      onDone: (response: ChatResponse) => void
      onError?: (detail: string, degraded: boolean) => void
    },
    signal?: AbortSignal,
  ) {
    const response = await fetch(`${API_URL}/api/chat/stream`, {
      method: 'POST',
      signal,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ session_id: sessionId, message, role_preset, buttons }),
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
    if (!response.body) {
      throw new ApiError('Поток ответа недоступен.', 502)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let completed = false
    let failed = false
    let failureDetail = ''

    const consume = (block: string) => {
      const lines = block.split(/\r?\n/)
      let eventName = 'message'
      const data: string[] = []
      for (const line of lines) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      if (!data.length) return
      let parsed: Record<string, unknown>
      try {
        parsed = JSON.parse(data.join('\n')) as Record<string, unknown>
      } catch {
        throw new ApiError('Сервер вернул повреждённое событие потока.', 502)
      }
      if (eventName === 'stage' && typeof parsed.name === 'string') handlers.onStage?.(parsed.name)
      else if (eventName === 'delta' && typeof parsed.text === 'string') handlers.onDelta?.(parsed.text)
      else if (eventName === 'error') {
        failed = true
        failureDetail = typeof parsed.detail === 'string' ? parsed.detail : 'Ошибка хода.'
        handlers.onError?.(failureDetail, Boolean(parsed.degraded))
      } else if (eventName === 'done') {
        completed = true
        handlers.onDone(parsed as ChatResponse)
      }
    }

    try {
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split(/\r?\n\r?\n/)
        buffer = parts.pop() ?? ''
        for (const block of parts) consume(block)
      }
      buffer += decoder.decode()
      if (buffer.trim()) consume(buffer)
    } finally {
      reader.releaseLock()
    }
    if (failed && !completed) {
      throw new ApiError(failureDetail || 'Ошибка хода.', 422)
    }
    if (!completed) {
      throw new ApiError('Поток оборвался до завершения хода.', 502)
    }
  },

  contractor(token: string, inn: string, role: RolePreset) {
    return request<FactPack>(
      `/api/contractors/${inn}?role=${role}`,
      {},
      token,
    )
  },

  compare(token: string, inns: string[], role_preset: RolePreset) {
    return request<CompareResult>(
      '/api/compare',
      { method: 'POST', body: JSON.stringify({ inns, role_preset }) },
      token,
    )
  },

  async exportReport(token: string, sessionId: string, format: 'json' | 'md' = 'json') {
    const response = await fetch(
      `${API_URL}/api/sessions/${sessionId}/report/export?format=${format}`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!response.ok) throw new ApiError('Отчёт пока недоступен.', response.status)
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = fileNameFrom(response.headers.get('Content-Disposition'), format)
    anchor.click()
    URL.revokeObjectURL(url)
  },
}

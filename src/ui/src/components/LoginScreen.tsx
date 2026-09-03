import { useState, type FormEvent } from 'react'
import { Button } from '@alfalab/core-components/button'
import { Input } from '@alfalab/core-components/input'
import { PasswordInput } from '@alfalab/core-components/password-input'

type Props = {
  loading: boolean
  error: string | null
  onLogin: (login: string, password: string) => Promise<void>
}

export function LoginScreen({ loading, error, onLogin }: Props) {
  const [login, setLogin] = useState('admin')
  const [password, setPassword] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    void onLogin(login, password)
  }

  return (
    <main className="login-shell">
      <section className="login-story" aria-labelledby="product-title">
        <div className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <h1 id="product-title">Контрагент<br />под контролем</h1>
        <p>
          Факты, риски и финансовая динамика в одном рабочем досье.
          Все показатели рассчитаны по данным отчёта.
        </p>
        <div className="login-proof">
          <span>Закрытая база</span>
          <span>Детерминированные расчёты</span>
          <span>Без домыслов</span>
        </div>
      </section>

      <section className="login-form-wrap">
        <form className="login-form" onSubmit={submit}>
          <header>
            <span className="wordmark">Альфа Банк</span>
            <h2>Вход в Альфа-Бизнес</h2>
            <p>Используйте учётные данные рабочего пространства.</p>
          </header>
          <Input
            block
            label="Логин"
            labelView="outer"
            value={login}
            disabled={loading}
            onChange={(_, payload) => setLogin(payload.value)}
          />
          <PasswordInput
            block
            label="Пароль"
            labelView="outer"
            value={password}
            disabled={loading}
            onChange={(_, payload) => setPassword(payload.value)}
          />
          {error && <div className="form-error" role="alert">{error}</div>}
          <Button
            type="submit"
            view="accent"
            size={56}
            block
            loading={loading}
            disabled={!login}
          >
            Войти
          </Button>
          <small>Доступ к данным фиксируется в истории системы.</small>
        </form>
      </section>
    </main>
  )
}

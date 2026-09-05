import { useMemo } from 'react'

import { compactMoney, number } from '../format'
import type { FactPack } from '../types'

/** Точек меньше двух — это не график, а одно значение: рисовать нечего. */
const MIN_POINTS = 2
const VIEW_W = 560
const VIEW_H = 160
const PAD_X = 8
const PAD_Y = 12

type Point = { label: string; value: number | null }
type Series = { name: string; tone: 'ink' | 'accent' | 'muted'; points: Point[] }

function known(points: Point[]): number[] {
  return points.map((p) => p.value).filter((v): v is number => v != null)
}

function enough(series: Series[]): boolean {
  return series.some((s) => known(s.points).length >= MIN_POINTS)
}

/** Линия с разрывами: пропуск — это «данных нет», а не ноль (§10). */
function Line({ series, scale }: { series: Series; scale: (v: number) => number }) {
  const step = series.points.length > 1 ? (VIEW_W - PAD_X * 2) / (series.points.length - 1) : 0
  const segments: string[] = []
  let current: string[] = []
  series.points.forEach((point, index) => {
    if (point.value == null) {
      if (current.length > 1) segments.push(current.join(' '))
      current = []
      return
    }
    current.push(`${PAD_X + index * step},${scale(point.value)}`)
  })
  if (current.length > 1) segments.push(current.join(' '))
  return (
    <g className={`chart-series chart-series-${series.tone}`}>
      {segments.map((points) => (
        <polyline key={points} points={points} fill="none" />
      ))}
      {series.points.map((point, index) =>
        point.value == null ? null : (
          <circle key={point.label} cx={PAD_X + index * step} cy={scale(point.value)} r={3} />
        ),
      )}
    </g>
  )
}

function Chart({ title, series, format }: {
  title: string
  series: Series[]
  format: (value: number | null) => string
}) {
  const labels = series[0]?.points.map((p) => p.label) ?? []
  const values = series.flatMap((s) => known(s.points))
  const max = Math.max(...values, 0)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const scale = (value: number) => VIEW_H - PAD_Y - ((value - min) / span) * (VIEW_H - PAD_Y * 2)

  return (
    <figure className="chart">
      <figcaption>
        {title}
        <span>
          {series.map((s) => (
            <b key={s.name} className={`chart-key chart-key-${s.tone}`}>{s.name}</b>
          ))}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="img" aria-label={title} preserveAspectRatio="none">
        {min < 0 && (
          <line className="chart-zero" x1={PAD_X} x2={VIEW_W - PAD_X} y1={scale(0)} y2={scale(0)} />
        )}
        {series.map((s) => (
          <Line key={s.name} series={s} scale={scale} />
        ))}
      </svg>
      <div className="chart-axis">
        {labels.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>
      <dl className="chart-last">
        {series.map((s) => {
          const last = [...s.points].reverse().find((p) => p.value != null)
          return (
            <div key={s.name}>
              <dt>{s.name}</dt>
              <dd>{format(last?.value ?? null)}</dd>
            </div>
          )
        })}
      </dl>
    </figure>
  )
}

/** Ряды собираются из факт-пакета, который и так пришёл: запросов и токенов не стоит. */
function build(pack: FactPack) {
  const years = pack.financials.years ?? []
  const balance = pack.financials.balance ?? []
  const arbitration = pack.arbitration.by_year ?? []
  const execproc = pack.execution_proceedings.by_year ?? {}
  const burden = pack.debt_burden

  const revenue: Series[] = [
    { name: 'Выручка', tone: 'accent', points: years.map((y) => ({ label: String(y.year), value: y.proceeds })) },
    { name: 'Прибыль', tone: 'ink', points: years.map((y) => ({ label: String(y.year), value: y.profit })) },
  ]
  const balanceSeries: Series[] = [
    { name: 'Активы', tone: 'accent', points: balance.map((row) => ({ label: String(row.year), value: row.total_assets ?? null })) },
    { name: 'Чистые активы', tone: 'ink', points: balance.map((row) => ({ label: String(row.year), value: row.net_assets ?? null })) },
  ]
  const execYears = Object.keys(execproc).sort()
  const execSeries: Series[] = [
    { name: 'Возбуждено', tone: 'accent', points: execYears.map((year) => ({ label: year, value: execproc[year] })) },
  ]
  const arbitrationSeries: Series[] = [
    { name: 'Истец', tone: 'ink', points: arbitration.map((row) => ({ label: String(row.year), value: row.plaintiff_count ?? null })) },
    { name: 'Ответчик', tone: 'accent', points: arbitration.map((row) => ({ label: String(row.year), value: row.defendant_count ?? null })) },
  ]
  const debtSeries: Series[] =
    burden && burden.net_assets != null
      ? [{
          name: 'Сумма',
          tone: 'accent',
          points: [
            { label: 'Текущий долг', value: burden.current_debt },
            { label: 'Чистые активы', value: burden.net_assets },
          ],
        }]
      : []

  return { revenue, balanceSeries, execSeries, arbitrationSeries, debtSeries }
}

export function RevenueChart({ pack }: { pack: FactPack }) {
  const { revenue } = useMemo(() => build(pack), [pack])
  if (!enough(revenue)) return null
  return <Chart title="Выручка и прибыль" series={revenue} format={compactMoney} />
}

/** Остальные графики — по клику: сразу показывается только выручка (§10). */
export function MoreCharts({ pack }: { pack: FactPack }) {
  const { balanceSeries, execSeries, arbitrationSeries, debtSeries } = useMemo(() => build(pack), [pack])
  const charts = [
    enough(balanceSeries) && <Chart key="balance" title="Активы и капитал" series={balanceSeries} format={compactMoney} />,
    enough(execSeries) && <Chart key="exec" title="Возбуждено исполнительных производств" series={execSeries} format={number} />,
    enough(arbitrationSeries) && <Chart key="arb" title="Арбитраж: истец и ответчик" series={arbitrationSeries} format={number} />,
    enough(debtSeries) && <Chart key="debt" title="Текущий долг против чистых активов" series={debtSeries} format={compactMoney} />,
  ].filter(Boolean)

  if (charts.length === 0) return null
  return (
    <details className="chart-more">
      <summary>Ещё графики ({charts.length})</summary>
      {charts}
    </details>
  )
}

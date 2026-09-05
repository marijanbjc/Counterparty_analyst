import { useMemo } from 'react'
import type { ReactNode } from 'react'

import { compactMoney, number } from '../format'
import type { FactPack } from '../types'

/** Точек меньше двух — это не график, а одно значение: рисовать нечего. */
const MIN_POINTS = 2

/* Геометрия в единицах viewBox. Подписи осей и значений живут внутри svg,
   поэтому поля считаются под них: слева — деления оси, сверху — значения
   у точек, снизу — категории. preserveAspectRatio не задаём: растяжение
   по одной оси искажает текст. */
const VIEW_W = 560
const VIEW_H = 210
const PAD_L = 58
const PAD_R = 14
const PAD_T = 20
const PAD_B = 26
const TICKS = 3
/** Воздух над максимумом, чтобы подпись значения не упиралась в край. */
const HEADROOM = 0.1

type Tone = 'ink' | 'accent' | 'muted'
type Point = { label: string; value: number | null }
type Series = { name: string; tone: Tone; points: Point[] }
type Format = (value: number | null) => string
type Scale = { min: number; max: number; y: (value: number) => number }

function known(points: Point[]): number[] {
  return points.map((p) => p.value).filter((v): v is number => v != null)
}

function enough(series: Series[]): boolean {
  return series.some((s) => known(s.points).length >= MIN_POINTS)
}

/** Хотя бы одно значение — уже есть что показать столбиками (двух точек им не нужно). */
function any(series: Series[]): boolean {
  return series.some((s) => known(s.points).length > 0)
}

const top = PAD_T
const bottom = VIEW_H - PAD_B

/** Своя шкала на ряд. Ноль в основании обязателен: столбик или линия, начатые
 *  от минимума, врут о масштабе. Отрицательные значения опускают основание. */
function makeScale(values: number[]): Scale {
  const high = Math.max(...values, 0)
  const low = Math.min(...values, 0)
  const span = high - low || Math.abs(high) || 1
  const max = high + span * HEADROOM
  const min = low < 0 ? low - span * HEADROOM : 0
  const range = max - min || 1
  return { min, max, y: (value) => bottom - ((value - min) / range) * (bottom - top) }
}

function ticks(scale: Scale): number[] {
  const step = (scale.max - scale.min) / (TICKS - 1)
  return Array.from({ length: TICKS }, (_, i) => scale.min + step * i)
}

function anchor(index: number, count: number): 'start' | 'middle' | 'end' {
  if (index === 0) return 'start'
  if (index === count - 1) return 'end'
  return 'middle'
}

/** Ось значений. Слева — первый ряд, справа — второй, когда шкалы разные. */
function Axis({ scale, format, tone, side }: {
  scale: Scale
  format: Format
  tone: Tone
  side: 'left' | 'right'
}) {
  const x = side === 'left' ? PAD_L - 6 : VIEW_W - PAD_L + 6
  return (
    <g className={`chart-axis-y chart-axis-${tone}`} textAnchor={side === 'left' ? 'end' : 'start'}>
      {ticks(scale).map((value) => (
        <text key={value} x={x} y={scale.y(value) + 3}>
          {format(value)}
        </text>
      ))}
    </g>
  )
}

function Grid({ scale, right }: { scale: Scale; right: number }) {
  return (
    <g className="chart-grid">
      {ticks(scale).map((value) => (
        <line key={value} x1={PAD_L} x2={right} y1={scale.y(value)} y2={scale.y(value)} />
      ))}
    </g>
  )
}

/** Линия с разрывами: пропуск — это «данных нет», а не ноль (§10). */
function Line({ series, scale, right, labelBelow, format }: {
  series: Series
  scale: Scale
  right: number
  labelBelow: boolean
  format: Format
}) {
  const count = series.points.length
  const width = right - PAD_L
  const step = count > 1 ? width / (count - 1) : 0
  const x = (index: number) => PAD_L + index * step
  const segments: string[] = []
  let current: string[] = []
  series.points.forEach((point, index) => {
    if (point.value == null) {
      if (current.length > 1) segments.push(current.join(' '))
      current = []
      return
    }
    current.push(`${x(index)},${scale.y(point.value)}`)
  })
  if (current.length > 1) segments.push(current.join(' '))

  return (
    <g className={`chart-series chart-series-${series.tone}`}>
      {segments.map((points) => (
        <polyline key={points} points={points} fill="none" />
      ))}
      {series.points.map((point, index) =>
        point.value == null ? null : (
          <g key={point.label}>
            <circle cx={x(index)} cy={scale.y(point.value)} r={3} />
            <text
              className="chart-value"
              x={x(index)}
              y={scale.y(point.value) + (labelBelow ? 15 : -9)}
              textAnchor={anchor(index, count)}
            >
              {format(point.value)}
            </text>
          </g>
        ),
      )}
    </g>
  )
}

function Categories({ labels, right }: { labels: string[]; right: number }) {
  const step = labels.length > 1 ? (right - PAD_L) / (labels.length - 1) : 0
  return (
    <g className="chart-categories">
      {labels.map((label, index) => (
        <text
          key={label}
          x={PAD_L + index * step}
          y={VIEW_H - 8}
          textAnchor={anchor(index, labels.length)}
        >
          {label}
        </text>
      ))}
    </g>
  )
}

function Frame({ title, series, children }: {
  title: string
  series: Series[]
  children: ReactNode
}) {
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
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} role="img" aria-label={title}>
        {children}
      </svg>
    </figure>
  )
}

/** Линейный график по годам. dual — своя шкала на каждый ряд: выручка и прибыль
 *  отличаются на порядок, на общей оси прибыль ложится в ноль и график пустой. */
function LineChart({ title, series, format, dual = false }: {
  title: string
  series: Series[]
  format: Format
  dual?: boolean
}) {
  const right = dual ? VIEW_W - PAD_L : VIEW_W - PAD_R
  const shared = makeScale(series.flatMap((s) => known(s.points)))
  const scales = series.map((s) => (dual ? makeScale(known(s.points)) : shared))
  const labels = series[0]?.points.map((p) => p.label) ?? []

  return (
    <Frame title={title} series={series}>
      <Grid scale={scales[0]} right={right} />
      <Axis scale={scales[0]} format={format} tone={dual ? series[0].tone : 'muted'} side="left" />
      {dual && series[1] && (
        <Axis scale={scales[1]} format={format} tone={series[1].tone} side="right" />
      )}
      {series.map((s, index) => (
        <Line
          key={s.name}
          series={s}
          scale={scales[index]}
          right={right}
          labelBelow={index > 0}
          format={format}
        />
      ))}
      <Categories labels={labels} right={right} />
    </Frame>
  )
}

/** Столбики. Две величины на одну дату сравнивают по высоте, а не по наклону:
 *  линия между «долгом» и «чистыми активами» соединяет несоединимое. */
function BarChart({ title, series, format }: {
  title: string
  series: Series[]
  format: Format
}) {
  const right = VIEW_W - PAD_R
  const scale = makeScale(series.flatMap((s) => known(s.points)))
  const labels = series[0]?.points.map((p) => p.label) ?? []
  const slot = (right - PAD_L) / Math.max(labels.length, 1)
  const width = Math.min((slot * 0.62) / series.length, 46)
  const base = scale.y(0)

  return (
    <Frame title={title} series={series}>
      <Grid scale={scale} right={right} />
      <Axis scale={scale} format={format} tone="muted" side="left" />
      {series.map((s, order) =>
        s.points.map((point, index) => {
          if (point.value == null) return null
          const center = PAD_L + slot * (index + 0.5)
          const x = center + (order - (series.length - 1) / 2) * width - width / 2
          const y = scale.y(point.value)
          return (
            <g key={`${s.name}-${point.label}`} className={`chart-bar chart-bar-${s.tone}`}>
              <rect x={x} y={Math.min(y, base)} width={width} height={Math.max(Math.abs(base - y), 1)} />
              <text
                className="chart-value"
                x={center + (order - (series.length - 1) / 2) * width}
                y={(point.value < 0 ? Math.max(y, base) + 13 : Math.min(y, base) - 6)}
                textAnchor="middle"
              >
                {format(point.value)}
              </text>
            </g>
          )
        }),
      )}
      {scale.min < 0 && <line className="chart-zero" x1={PAD_L} x2={right} y1={base} y2={base} />}
      <g className="chart-categories">
        {labels.map((label, index) => (
          <text key={label} x={PAD_L + slot * (index + 0.5)} y={VIEW_H - 8} textAnchor="middle">
            {label}
          </text>
        ))}
      </g>
    </Frame>
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
    // В строках баланса поле называется capitals; net_assets живёт только
    // в debt_burden. Ряд по net_assets молча выходил пустым, и график
    // «активы и капитал» показывал одну линию вместо двух.
    { name: 'Собственный капитал', tone: 'ink', points: balance.map((row) => ({ label: String(row.year), value: row.capitals ?? null })) },
  ]
  const execYears = Object.keys(execproc).sort()
  const execSeries: Series[] = [
    { name: 'Возбуждено', tone: 'accent', points: execYears.map((year) => ({ label: year, value: execproc[year] })) },
  ]
  const arbitrationSeries: Series[] = [
    { name: 'Истец', tone: 'ink', points: arbitration.map((row) => ({ label: String(row.year), value: row.plaintiff_count ?? null })) },
    { name: 'Ответчик', tone: 'accent', points: arbitration.map((row) => ({ label: String(row.year), value: row.defendant_count ?? null })) },
  ]
  // Долг и капитал — не ряд по времени, а две величины на одну дату: столбики.
  const debtSeries: Series[] =
    burden && burden.net_assets != null
      ? [
          { name: 'Текущий долг', tone: 'accent', points: [{ label: 'Текущий долг', value: burden.current_debt }] },
          { name: 'Чистые активы', tone: 'ink', points: [{ label: 'Чистые активы', value: burden.net_assets }] },
        ]
      : []

  return { revenue, balanceSeries, execSeries, arbitrationSeries, debtSeries }
}

/** Столбики долга и капитала стоят рядом, поэтому подписи рядов дублируют
 *  категории под ними: в легенде их не показываем. */
function debtBars(series: Series[]): Series[] {
  const labels = series.map((s) => s.points[0]?.label ?? s.name)
  return series.map((s, index) => ({
    ...s,
    points: labels.map((label, position) => ({
      label,
      value: position === index ? (s.points[0]?.value ?? null) : null,
    })),
  }))
}

export function RevenueChart({ pack }: { pack: FactPack }) {
  const { revenue } = useMemo(() => build(pack), [pack])
  if (!enough(revenue)) return null
  return <LineChart title="Выручка и прибыль" series={revenue} format={compactMoney} dual />
}

/** Остальные графики — по клику: сразу показывается только выручка (§10). */
export function MoreCharts({ pack }: { pack: FactPack }) {
  const { balanceSeries, execSeries, arbitrationSeries, debtSeries } = useMemo(() => build(pack), [pack])
  const charts = [
    enough(balanceSeries) && (
      <LineChart key="balance" title="Активы и капитал" series={balanceSeries} format={compactMoney} />
    ),
    enough(execSeries) && (
      <BarChart key="exec" title="Возбуждено исполнительных производств" series={execSeries} format={number} />
    ),
    enough(arbitrationSeries) && (
      <BarChart key="arb" title="Арбитраж: истец и ответчик" series={arbitrationSeries} format={number} />
    ),
    any(debtSeries) && (
      <BarChart
        key="debt"
        title="Текущий долг против чистых активов"
        series={debtBars(debtSeries)}
        format={compactMoney}
      />
    ),
  ].filter(Boolean)

  if (charts.length === 0) return null
  return (
    <details className="chart-more">
      <summary>Ещё графики ({charts.length})</summary>
      {charts}
    </details>
  )
}

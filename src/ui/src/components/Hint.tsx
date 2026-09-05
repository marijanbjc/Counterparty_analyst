import { useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { GLOSSARY, type TermKey } from '../glossary'

/** Ширина окна и отступ от краёв экрана — в тех же единицах, что и CSS. */
const WIDTH = 240
const EDGE = 12
const GAP = 8
/** Ниже этого запаса под иконкой окно раскрывается вверх. */
const BELOW_MIN = 150

/** Сноска с определением термина (ARCHITECTURE.md).
 *
 *  Окно рисуется через портал в body с `position: fixed`, а не absolute внутри
 *  строки. Абсолютное позиционирование срезали и прокручиваемые контейнеры
 *  (лента сообщений, досье, таблица сравнения), и края экрана: окно шириной
 *  280px не помещается ни у левой границы сообщения, ни у правой границы
 *  таблицы. Портал снимает обе проблемы разом, а координаты считаются по
 *  месту иконки и зажимаются в границы окна браузера.
 *
 *  Кнопка, а не span с title: подсказка должна открываться и по клику — на
 *  телефоне наведения нет, — и по клавиатуре.
 */
export function Hint({ term }: { term: TermKey }) {
  const entry = GLOSSARY[term]
  const ref = useRef<HTMLButtonElement>(null)
  const [box, setBox] = useState<{ top: number; left: number; above: boolean } | null>(null)

  const open = () => {
    const anchor = ref.current?.getBoundingClientRect()
    if (!anchor) return
    const width = Math.min(WIDTH, window.innerWidth - EDGE * 2)
    const centered = anchor.left + anchor.width / 2 - width / 2
    const left = Math.min(Math.max(EDGE, centered), window.innerWidth - width - EDGE)
    const above = window.innerHeight - anchor.bottom < BELOW_MIN
    setBox({
      top: above ? anchor.top - GAP : anchor.bottom + GAP,
      left,
      above,
    })
  }

  return (
    <button
      ref={ref}
      type="button"
      className="hint"
      aria-label={`Что такое «${entry.title}»`}
      // Клик по сноске не должен доходить до строки, на которой она стоит:
      // иначе иконка внутри details или карточки переключает их.
      onClick={(event) => {
        event.stopPropagation()
        box ? setBox(null) : open()
      }}
      onMouseEnter={open}
      onMouseLeave={() => setBox(null)}
      onFocus={open}
      onBlur={() => setBox(null)}
    >
      <span aria-hidden="true">?</span>
      {box &&
        createPortal(
          <span
            className={`hint-bubble${box.above ? ' hint-bubble-above' : ''}`}
            role="tooltip"
            style={{ top: box.top, left: box.left, maxWidth: WIDTH }}
          >
            <b>{entry.title}</b>
            {entry.text}
          </span>,
          document.body,
        )}
    </button>
  )
}

/** Термин вместе со сноской — чтобы иконка не отрывалась от слова переносом. */
export function Term({ term, children }: { term: TermKey; children: ReactNode }) {
  return (
    <span className="term">
      {children}
      <Hint term={term} />
    </span>
  )
}

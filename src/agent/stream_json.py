_SEEK_KEY, _KEY, _COLON, _VALUE, _TEXT, _ESCAPE, _UNICODE, _STOP = range(8)

_SIMPLE_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_HIGH_SURROGATE = range(0xD800, 0xDC00)
_LOW_SURROGATE = range(0xDC00, 0xE000)


class FirstFieldExtractor:
    """Отдаёт значение первого ключа JSON по мере поступления чанков (§13.2).

    Второго парсера JSON здесь нет: сырой поток копится в buffered и разбирается
    json.loads один раз в конце.
    """

    def __init__(self, field: str) -> None:
        self._field = field
        self._raw: list[str] = []
        self._state = _SEEK_KEY
        self._key: list[str] = []
        self._hex = ""
        self._high: str | None = None
        self._done = False
        self._fell_back = False

    @property
    def done(self) -> bool:
        return self._done

    @property
    def fell_back(self) -> bool:
        return self._fell_back

    @property
    def buffered(self) -> str:
        return "".join(self._raw)

    def feed(self, chunk: str) -> str:
        self._raw.append(chunk)
        if self._state == _STOP:
            return ""
        out: list[str] = []
        for char in chunk:
            if self._state == _STOP:
                break
            self._step(char, out)
        return "".join(out)

    def _step(self, char: str, out: list[str]) -> None:
        state = self._state
        if state == _SEEK_KEY:
            if char == '"':
                self._state = _KEY
        elif state == _KEY:
            if char == '"':
                if "".join(self._key) == self._field:
                    self._state = _COLON
                else:
                    self._fall_back()
            else:
                self._key.append(char)
        elif state == _COLON:
            if char == ":":
                self._state = _VALUE
        elif state == _VALUE:
            if char == '"':
                self._state = _TEXT
            elif not char.isspace():
                self._fall_back()  # значение поля — не строка, стримить нечего
        elif state == _TEXT:
            if char == "\\":
                self._state = _ESCAPE
            elif char == '"':
                self._flush_high(out)
                self._done = True
                self._state = _STOP
            else:
                self._emit(out, char)
        elif state == _ESCAPE:
            if char == "u":
                self._hex = ""
                self._state = _UNICODE
            else:
                self._emit(out, _SIMPLE_ESCAPES.get(char, char))
                self._state = _TEXT
        elif state == _UNICODE:
            self._hex += char
            if len(self._hex) == 4:
                self._emit_code(out, int(self._hex, 16))
                self._hex = ""
                self._state = _TEXT

    def _emit(self, out: list[str], text: str) -> None:
        self._flush_high(out)
        out.append(text)

    def _emit_code(self, out: list[str], code: int) -> None:
        if code in _LOW_SURROGATE and self._high is not None:
            pair = (self._high + chr(code)).encode("utf-16", "surrogatepass").decode("utf-16")
            self._high = None
            out.append(pair)
            return
        self._flush_high(out)
        if code in _HIGH_SURROGATE:
            self._high = chr(code)  # пара может приехать следующим \uXXXX
        else:
            out.append(chr(code))

    def _flush_high(self, out: list[str]) -> None:
        if self._high is not None:
            out.append(self._high)
            self._high = None

    def _fall_back(self) -> None:
        self._fell_back = True
        self._state = _STOP

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache

WINDOW_SECONDS = 60.0
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 30.0
WAKE_MARGIN_SECONDS = 0.05


class TokenRateLimiter:
    """Скользящее минутное окно расхода токенов: ждёт освобождения вместо ошибки."""

    def __init__(self, tpm_limit: int) -> None:
        self._tpm_limit = tpm_limit
        self._window: deque[list[float]] = deque()
        self._pending: deque[list[float]] = deque()
        self._lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()

    @asynccontextmanager
    async def serialized_call(self) -> AsyncIterator[None]:
        """Не даёт ответам завершиться не в порядке резервов.

        Иначе FIFO в record() сопоставит usage чужой оценке, а суммарное окно
        начнёт дрейфовать на границе минуты.
        """
        async with self._call_lock:
            yield

    async def reserve(self, estimated_tokens: int) -> None:
        # Лок держится и во время ожидания: иначе параллельные ходы вместе пробьют лимит.
        async with self._lock:
            while True:
                self._prune()
                if not self._window or self._used() + estimated_tokens <= self._tpm_limit:
                    break
                wait = self._window[0][0] + WINDOW_SECONDS - time.monotonic()
                await asyncio.sleep(max(wait, 0.0) + WAKE_MARGIN_SECONDS)
            entry = [time.monotonic(), float(estimated_tokens)]
            self._window.append(entry)
            self._pending.append(entry)

    def record(self, actual_tokens: int) -> None:
        """Замена оценки фактом из usage ответа; порядок FIFO — вызовы сериализованы."""
        self._prune()
        edge = time.monotonic() - WINDOW_SECONDS
        while self._pending:
            entry = self._pending.popleft()
            if entry[0] >= edge:  # запись всё ещё в окне — правим её, объект общий с _window
                entry[1] = float(actual_tokens)
                return
        self._window.append([time.monotonic(), float(actual_tokens)])

    async def backoff(self, attempt: int, retry_after: float | None = None) -> float:
        delay = retry_after if retry_after is not None else BACKOFF_BASE_SECONDS * 2**attempt
        delay = min(max(delay, 0.0), BACKOFF_MAX_SECONDS)
        async with self._lock:
            await asyncio.sleep(delay)
        return delay

    @property
    def used(self) -> int:
        self._prune()
        return int(self._used())

    def _used(self) -> float:
        return sum(entry[1] for entry in self._window)

    def _prune(self) -> None:
        edge = time.monotonic() - WINDOW_SECONDS
        while self._window and self._window[0][0] < edge:
            self._window.popleft()


@lru_cache
def get_limiter(tpm_limit: int) -> TokenRateLimiter:
    return TokenRateLimiter(tpm_limit)

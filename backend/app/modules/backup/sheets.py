"""Google Sheets transport for the backup feature.

The backup service only talks to the :class:`SheetsClient` protocol, so tests
(and any future provider) can swap in an in-memory implementation. The real
client uses a Google service-account key and retries transient API failures
with exponential backoff.

`gspread` / `google-auth` are imported lazily so the application still boots
when the optional backup dependency is not installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("mj.backup.sheets")

# HTTP statuses worth retrying: rate limiting and transient server errors.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class SheetsError(RuntimeError):
    """Raised when a Google Sheets operation cannot be completed."""


@runtime_checkable
class SheetsClient(Protocol):
    """Minimal spreadsheet surface the backup service depends on."""

    async def list_tabs(self) -> list[str]: ...

    async def get_header(self, title: str) -> list[str]: ...

    async def set_header(self, title: str, header: list[str]) -> None: ...

    async def append_rows(self, title: str, rows: list[list[Any]]) -> None: ...

    async def get_rows(self, title: str) -> list[list[Any]]: ...


class InMemorySheetsClient:
    """A spreadsheet backed by a dict — used by tests and dry runs."""

    def __init__(self) -> None:
        self.tabs: dict[str, list[list[Any]]] = {}

    async def list_tabs(self) -> list[str]:
        return list(self.tabs.keys())

    async def get_header(self, title: str) -> list[str]:
        rows = self.tabs.get(title) or []
        return [str(value) for value in rows[0]] if rows else []

    async def set_header(self, title: str, header: list[str]) -> None:
        rows = self.tabs.setdefault(title, [])
        if rows:
            rows[0] = list(header)
        else:
            rows.append(list(header))

    async def append_rows(self, title: str, rows: list[list[Any]]) -> None:
        self.tabs.setdefault(title, []).extend([list(row) for row in rows])

    async def get_rows(self, title: str) -> list[list[Any]]:
        return [list(row) for row in self.tabs.get(title, [])]


class GSpreadSheetsClient:
    """Service-account Google Sheets client with retry/backoff.

    Every blocking `gspread` call is dispatched to a worker thread so the async
    scheduler/API event loop is never blocked. Transient API failures (HTTP 429
    / 5xx and network errors) are retried with exponential backoff.
    """

    def __init__(
        self,
        spreadsheet_id: str,
        service_account_info: dict[str, Any],
        *,
        max_attempts: int = 4,
        backoff_base: float = 1.0,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.service_account_info = service_account_info
        self.max_attempts = max(1, int(max_attempts))
        self.backoff_base = max(0.0, float(backoff_base))
        self._client = None
        self._book = None
        self._worksheets: dict[str, Any] = {}

    # ------------------------------------------------------------- transport

    def _load(self):
        if self._book is not None:
            return self._book
        try:
            import gspread  # noqa: PLC0415 - optional dependency
        except ImportError as exc:  # pragma: no cover - exercised only when dep missing
            raise SheetsError(
                "The Google Sheets client library is not installed on the server."
            ) from exc
        try:
            self._client = gspread.service_account_from_dict(self.service_account_info)
            self._book = self._client.open_by_key(self.spreadsheet_id)
        except Exception as exc:  # noqa: BLE001 - surfaced as a friendly SheetsError
            raise SheetsError(f"Could not open the Google Spreadsheet: {exc}") from exc
        return self._book

    def _worksheet(self, title: str):
        book = self._load()
        cached = self._worksheets.get(title)
        if cached is not None:
            return cached
        import gspread  # noqa: PLC0415

        try:
            worksheet = book.worksheet(title)
        except gspread.WorksheetNotFound:
            worksheet = book.add_worksheet(title=title, rows=1000, cols=30)
        self._worksheets[title] = worksheet
        return worksheet

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(status, int):
            return status in _RETRYABLE_STATUS
        # gspread wraps transport failures (connection reset, timeout) without a
        # response object; those are safe to retry.
        name = type(exc).__name__
        return name in {"ConnectionError", "Timeout", "ReadTimeout", "ConnectTimeout"}

    async def _run(self, label: str, fn, *args, **kwargs):
        delay = self.backoff_base
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except SheetsError:
                raise
            except Exception as exc:  # noqa: BLE001 - retry/translate below
                last_exc = exc
                if attempt >= self.max_attempts or not self._is_retryable(exc):
                    break
                logger.warning(
                    "Google Sheets %s failed (attempt %s/%s): %s",
                    label,
                    attempt,
                    self.max_attempts,
                    exc,
                )
                if delay:
                    await asyncio.sleep(delay)
                delay *= 2
        raise SheetsError(f"Google Sheets {label} failed: {last_exc}") from last_exc

    # ------------------------------------------------------------ operations

    async def list_tabs(self) -> list[str]:
        def _list() -> list[str]:
            return [ws.title for ws in self._load().worksheets()]

        return await self._run("list_tabs", _list)

    async def get_header(self, title: str) -> list[str]:
        def _get() -> list[str]:
            values = self._worksheet(title).row_values(1)
            return [str(value) for value in values]

        return await self._run(f"get_header[{title}]", _get)

    async def set_header(self, title: str, header: list[str]) -> None:
        def _set() -> None:
            self._worksheet(title).update(values=[list(header)], range_name="A1")

        await self._run(f"set_header[{title}]", _set)

    async def append_rows(self, title: str, rows: list[list[Any]]) -> None:
        if not rows:
            return

        def _append() -> None:
            self._worksheet(title).append_rows(rows, value_input_option="RAW")

        await self._run(f"append_rows[{title}]", _append)

    async def get_rows(self, title: str) -> list[list[Any]]:
        def _get() -> list[list[Any]]:
            return self._worksheet(title).get_all_values()

        return await self._run(f"get_rows[{title}]", _get)


def parse_service_account_json(raw: str) -> dict[str, Any]:
    """Validate and parse the stored service-account JSON key."""
    text = (raw or "").strip()
    if not text:
        raise SheetsError("A Google service-account key is required.")
    try:
        info = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SheetsError("The Google service-account key is not valid JSON.") from exc
    if not isinstance(info, dict) or not info.get("client_email") or not info.get("private_key"):
        raise SheetsError(
            "The Google service-account key is missing client_email or private_key."
        )
    return info

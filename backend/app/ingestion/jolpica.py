"""Jolpica (Ergast-compatible) HTTP client with throttling, retry/backoff and an on-disk raw cache.

The raw cache makes ingestion repeatable and resumable: a response that has been fetched once is
never requested again (delete data/raw_cache to force a refresh).
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import get_settings
from app.logging_setup import get_logger

log = get_logger("jolpica")
PAGE_LIMIT = 100


class SourceError(RuntimeError):
    """The upstream data source failed or returned unusable data."""


class JolpicaClient:
    def __init__(self, client: httpx.Client | None = None, cache_dir: Path | None = None) -> None:
        s = get_settings()
        self.base = s.jolpica_base_url.rstrip("/")
        self.min_interval = s.http_min_interval_s
        self.max_retries = s.http_max_retries
        self.cache_dir = cache_dir if cache_dir is not None else s.raw_cache_dir
        self._client = client or httpx.Client(timeout=s.http_timeout_s, headers={"User-Agent": "f1-strategy-research/0.1"})
        self._last = 0.0

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:32]}.json"

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base}/{path.lstrip('/')}"
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        cache = self._cache_path(key)
        if cache.exists():
            return json.loads(cache.read_text(encoding="utf-8"))
        for attempt in range(self.max_retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                log.warning("http_error", url=url, attempt=attempt, error=str(exc))
                time.sleep(min(2**attempt, 30))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                delay = float(r.headers.get("Retry-After", min(2**attempt * 2, 60)))
                log.warning("backoff", status=r.status_code, delay=delay, url=url)
                time.sleep(delay)
                continue
            if r.status_code != 200:
                raise SourceError(f"{url} -> HTTP {r.status_code}")
            data = r.json()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
            return data  # type: ignore[no-any-return]
        raise SourceError(f"{url}: gave up after {self.max_retries} attempts")

    def paged(self, path: str, extract: Any) -> list[Any]:
        """Fetch all pages of a list endpoint; ``extract(MRData)`` returns the page's rows."""
        rows: list[Any] = []
        offset = 0
        while True:
            mr = self.get_json(path, {"limit": PAGE_LIMIT, "offset": offset})["MRData"]
            rows.extend(extract(mr))
            offset += PAGE_LIMIT
            if offset >= int(mr["total"]):
                return rows

    # -- endpoints ---------------------------------------------------------------------------
    def schedule(self, season: int) -> list[dict[str, Any]]:
        return self.get_json(f"{season}.json", {"limit": 100})["MRData"]["RaceTable"]["Races"]  # type: ignore[no-any-return]

    def results(self, season: int, rnd: int) -> list[dict[str, Any]]:
        mr = self.get_json(f"{season}/{rnd}/results.json", {"limit": 100})["MRData"]
        races = mr["RaceTable"]["Races"]
        return races[0]["Results"] if races else []  # type: ignore[no-any-return]

    def pitstops(self, season: int, rnd: int) -> list[dict[str, Any]]:
        def ex(mr: dict[str, Any]) -> list[Any]:
            races = mr["RaceTable"]["Races"]
            return races[0]["PitStops"] if races else []

        return self.paged(f"{season}/{rnd}/pitstops.json", ex)

    def laps(self, season: int, rnd: int) -> list[dict[str, Any]]:
        """Returns [{'number': int, 'Timings': [...]}, ...]; laps split across pages are merged."""
        merged: dict[int, list[Any]] = {}

        def ex(mr: dict[str, Any]) -> list[Any]:
            races = mr["RaceTable"]["Races"]
            for lap in races[0]["Laps"] if races else []:
                merged.setdefault(int(lap["number"]), []).extend(lap["Timings"])
            return []

        self.paged(f"{season}/{rnd}/laps.json", ex)
        return [{"number": n, "Timings": t} for n, t in sorted(merged.items())]

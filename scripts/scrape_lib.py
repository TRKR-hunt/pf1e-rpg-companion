"""Shared HTTP-fetch + concurrency + name-disambiguation primitives for
d20pfsrd scrapers.

Settings per the v2 session brief:
  - 4 concurrent worker pool
  - 0.5 s per-worker delay between its own consecutive requests
  - Effective rate: roughly 8 req/s peak
  - Real, non-spoofing User-Agent identifying this as a one-time PF1e
    content scrape with a contact reference
  - Disk-cached responses (sha1 of URL)
  - HARD STOP on HTTP 429 / 503 or persistent blocking — drains the
    executor and raises so the caller halts and reports
  - Display-name disambiguation: the bundled compiler emits the per-
    resource output filename by slugifying the `name` stat, NOT the id.
    When two instances share a name (d20pfsrd has 13 trait name
    collisions, many more for feats/spells), one of them silently
    overwrites the other in `releases/dev_tool_output/<system>/resources/`.
    The bundle still has both — but per-resource URL access (deep links,
    eventual gh-pages publish) loses one. `disambiguate_names` rewrites
    colliding names so each instance gets a unique compiler slug.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence, TypeVar
from urllib.parse import urlparse

import requests

# Identify clearly. d20pfsrd's nginx returns 410 to bare/empty UAs but
# accepts named UAs that include a Mozilla token; we keep that token for
# basic compatibility but the identifying portion is unambiguous.
UA = (
    "Mozilla/5.0 (compatible; PF1e-RPGCompanion-Builder/0.2; "
    "one-time PF1e content scrape; "
    "+https://github.com/Blastervla/rpg-companion-app; "
    "contact tylerjgiddings@gmail.com)"
)

WORKERS = 4
PER_WORKER_DELAY = 0.5          # seconds between this worker's GETs
REQUEST_TIMEOUT = 30

CACHE_DIR = Path(__file__).parent / ".cache"

# Hard-stop status codes per session brief. 403 added because d20pfsrd's
# CDN can sub a 403 for what is effectively a soft block.
HARD_STOP_STATUSES = {403, 429, 503}


class HardStop(RuntimeError):
    """Raised when an anti-abuse signal is detected. Caller drains and aborts."""


# Per-worker last-fetch timestamp, keyed by threading.get_ident().
_last_fetch_by_thread: dict[int, float] = {}
_last_fetch_lock = threading.Lock()

# Set when any worker raises HardStop. Other workers check and short-circuit.
_hard_stop = threading.Event()


def _sleep_to_budget() -> None:
    """Per-worker rate limit: ensure at least PER_WORKER_DELAY between
    this thread's own consecutive fetches."""
    tid = threading.get_ident()
    now = time.monotonic()
    with _last_fetch_lock:
        last = _last_fetch_by_thread.get(tid, 0.0)
        wait = (last + PER_WORKER_DELAY) - now
    if wait > 0:
        time.sleep(wait)
    with _last_fetch_lock:
        _last_fetch_by_thread[tid] = time.monotonic()


def reset_hard_stop() -> None:
    """Clear the hard-stop flag between full scraper runs."""
    _hard_stop.clear()


def fetch(url: str, session: Optional[requests.Session] = None) -> str:
    """Fetch URL, returning text. Uses disk cache; respects per-worker
    rate limit; raises HardStop on anti-abuse signals.

    Idempotent and thread-safe."""
    if _hard_stop.is_set():
        raise HardStop("aborted: hard-stop flag set by another worker")
    CACHE_DIR.mkdir(exist_ok=True)
    key = hashlib.sha1(url.encode("utf-8")).hexdigest()
    cache_file = CACHE_DIR / f"{key}.html"
    if cache_file.exists():
        return cache_file.read_text(encoding="utf-8")

    _sleep_to_budget()
    if _hard_stop.is_set():
        raise HardStop("aborted: hard-stop flag set during sleep")

    s = session or requests
    print(f"  GET {url}")
    resp = s.get(url, headers={"User-Agent": UA}, timeout=REQUEST_TIMEOUT)
    if resp.status_code in HARD_STOP_STATUSES:
        _hard_stop.set()
        raise HardStop(
            f"HTTP {resp.status_code} from {url} — halting scrape per v2 guardrails"
        )
    resp.raise_for_status()
    cache_file.write_text(resp.text, encoding="utf-8")
    return resp.text


T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    items: Iterable[T],
    fn: Callable[[T], R],
    workers: int = WORKERS,
    label: str = "items",
) -> list[Optional[R]]:
    """Run fn(item) across a worker pool. Order of results matches order of
    input. Items that raise HardStop drain the pool; their exception
    propagates after collection. Other exceptions are caught per-item,
    logged, and the result slot is set to None.
    """
    items_list = list(items)
    if not items_list:
        return []
    results: list[Optional[R]] = [None] * len(items_list)
    fatal: list[BaseException] = []

    def _wrap(idx: int, item: T) -> None:
        if _hard_stop.is_set():
            return
        try:
            results[idx] = fn(item)
        except HardStop as e:
            fatal.append(e)
        except Exception as e:
            print(f"  ! [{label}#{idx}] {item!r}: {e}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures: list[Future] = [
            pool.submit(_wrap, i, it) for i, it in enumerate(items_list)
        ]
        for f in futures:
            f.result()

    if fatal:
        raise fatal[0]
    return results


# ---------------------------------------------------------------- name disambiguation

def compiler_slug(name: str) -> str:
    """Approximates the bundled compiler's per-resource filename slug rule:
    lowercase, runs of non-alphanumeric → single underscore, trim.

    The compiler derives the per-resource `.rpg` output filename from the
    `name` stat (not from the resource id). Two instances whose names
    produce the same compiler_slug will collide in the output directory —
    one silently overwrites the other. Use `disambiguate_names` upstream
    to ensure uniqueness before writing.
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


_CONNECTOR_WORDS = {
    "regional", "combat", "faith", "magic", "social", "religion", "race",
    "mount", "campaign", "trait", "traits", "feat", "feats", "spell",
    "spells", "item", "items",
}
_MAX_DISC_WORDS = 4


def _url_distinguisher(url: str, name: str) -> str | None:
    """Pull a human-readable hint from the URL beyond the bare name slug.

    Returns None when no useful residue exists (URL tail == name, or the
    residue is only connector words). Caps to MAX_DISC_WORDS to keep
    display names readable."""
    if not url:
        return None
    path = urlparse(url).path.rstrip("/")
    if not path:
        return None
    tail = path.rsplit("/", 1)[-1]
    # Normalize URL slug into tokens.
    url_tokens = [t for t in tail.replace("_", "-").split("-") if t]
    # Tokenize the name the same way for substring comparison.
    name_tokens = [
        t for t in re.split(r"[^a-z0-9]+", name.lower()) if t
    ]
    if not url_tokens:
        return None
    # Drop any URL token that matches a name token (handles start/end/middle).
    name_set = set(name_tokens)
    residue = [t for t in url_tokens if t not in name_set]
    # Drop connector words that don't add information by themselves.
    residue = [t for t in residue if t not in _CONNECTOR_WORDS]
    # Dedup tokens while preserving first-occurrence order (some URLs
    # repeat the same word, e.g. mana-wastes-...-mana-wastes).
    seen: set[str] = set()
    deduped: list[str] = []
    for t in residue:
        if t in seen:
            continue
        seen.add(t)
        deduped.append(t)
    if not deduped:
        return None
    # Cap to MAX_DISC_WORDS, preserving order.
    return " ".join(deduped[:_MAX_DISC_WORDS]).title()


def disambiguate_names(
    triples: Sequence[tuple[str, str, str | None]],
) -> list[str]:
    """Given parallel (name, url, category|None) tuples, return a list of
    unique display names (parallel to input) such that
    `compiler_slug(out[i])` is unique across the result.

    Disambiguation strategy is greedy in this order — for each item it
    accepts the first candidate that is not already taken by an earlier
    item in the same colliding group:

      1.  `Name`                          — bare (only the first wins)
      2.  `Name (UrlDiscriminator)`       — when the URL tail beyond
                                             the name contains a hint
      3.  `Name (Category)`               — pretty-printed category
      4.  `Name (Category: UrlDisc)`      — combined fallback
      5.  `Name #N`                       — numeric fallback (rare)

    Items not in a colliding group are returned unchanged.
    """
    n = len(triples)
    if n == 0:
        return []
    slugs = [compiler_slug(t[0]) for t in triples]
    groups: dict[str, list[int]] = {}
    for i, sl in enumerate(slugs):
        groups.setdefault(sl, []).append(i)

    out: list[str] = [t[0] for t in triples]
    taken: set[str] = set()
    # First pass: items NOT in a collision group keep their names.
    for sl, idxs in groups.items():
        if len(idxs) == 1:
            taken.add(sl)

    # Second pass: assign disambiguators within each collision group.
    for sl, idxs in groups.items():
        if len(idxs) == 1:
            continue
        # Sort idxs for deterministic assignment — by URL ascending.
        idxs_sorted = sorted(idxs, key=lambda i: triples[i][1] or "")
        for i in idxs_sorted:
            name, url, category = triples[i]
            disc = _url_distinguisher(url, name)
            cat_pretty = (category or "").replace("_", " ").title() if category else None
            candidates: list[str] = [name]
            if disc:
                candidates.append(f"{name} ({disc})")
            if cat_pretty:
                candidates.append(f"{name} ({cat_pretty})")
            if disc and cat_pretty:
                candidates.append(f"{name} ({cat_pretty}: {disc})")
            chosen: str | None = None
            for cand in candidates:
                cand_sl = compiler_slug(cand)
                if cand_sl not in taken:
                    chosen = cand
                    taken.add(cand_sl)
                    break
            if chosen is None:
                # Numeric fallback. Start at 2 to keep first instance bare.
                k = 2
                while True:
                    cand = f"{name} #{k}"
                    cand_sl = compiler_slug(cand)
                    if cand_sl not in taken:
                        chosen = cand
                        taken.add(cand_sl)
                        break
                    k += 1
            out[i] = chosen
    return out

#!/usr/bin/env python3
"""AZS WATCH — local Army+ fuel dashboard."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DATA = ROOT / "data"
PARTNERS = DATA / "partners.json"


def is_hosted() -> bool:
    return bool(os.environ.get("VERCEL") or os.environ.get("AZS_HOSTED"))


def runtime_dir() -> Path:
    raw = os.environ.get("AZS_RUNTIME_DIR")
    if raw:
        path = Path(raw)
    elif os.environ.get("VERCEL"):
        path = Path("/tmp/azs-watch")
    else:
        path = DATA
    path.mkdir(parents=True, exist_ok=True)
    return path


CACHE = runtime_dir() / "cache.json"
OVERRIDES = (
    DATA / "discounts.local.json"
    if os.environ.get("VERCEL")
    else runtime_dir() / "discounts.local.json"
)
FUEL_KEYS = ("a95plus", "a95", "a92", "diesel", "dieselplus", "lpg")

MINFIN_TM = "https://index.minfin.com.ua/ua/markets/fuel/tm/"
MINFIN_DETAIL = "https://index.minfin.com.ua/ua/markets/fuel/detail/"
OKKO_FUELS = "https://www.okko.ua/fuels"
WOG_FUELS = "https://wog.ua/ua/fuels/"
SHINA_PRICES = "https://shinapro.in.ua/tsiny-na-palne/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
REFRESH_SEC = 60 * 60
NATIONAL = "Україна"
ALT_MAX_AGE_HOURS = 48
UA_MONTHS = {
    "січня": 1,
    "лютого": 2,
    "березня": 3,
    "квітня": 4,
    "травня": 5,
    "червня": 6,
    "липня": 7,
    "серпня": 8,
    "вересня": 9,
    "жовтня": 10,
    "листопада": 11,
    "грудня": 12,
}
SHINA_ALIASES = {
    "ОККО": ("ОККО", "OKKO"),
    "OKKO": ("ОККО", "OKKO"),
    "WOG": ("WOG",),
    "UPG": ("UPG",),
    "KLO": ("KLO",),
}

_lock = threading.RLock()
_state: dict[str, Any] = {}
_next_at = 0.0
_wake = threading.Event()
_listen_port = 8765


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def next_iso() -> str | None:
    if not _next_at:
        return None
    return datetime.fromtimestamp(_next_at).astimezone().isoformat(timespec="seconds")


def schedule_next() -> None:
    global _next_at
    with _lock:
        _next_at = time.time() + REFRESH_SEC
    _wake.set()


def attach_schedule(payload: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        nxt = next_iso()
    payload["refresh_every_sec"] = REFRESH_SEC
    payload["next_refresh_at"] = nxt
    return payload


def load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def fetch(url: str, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": UA, "Accept-Language": "uk,en;q=0.8"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_number(text: str) -> float | None:
    cleaned = re.sub(r"[^\d,.\-]", "", (text or "").replace("\xa0", "").strip())
    if not cleaned:
        return None
    cleaned = cleaned.replace(",", ".")
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def kopiyky_to_uah(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num >= 200:
        num = num / 100.0
    if num < 10 or num > 200:
        return None
    return round(num, 2)


def parse_page_stamp(html: str) -> datetime | None:
    iso = re.search(r'"dateModified"\s*:\s*"([^"]+)"', html)
    if iso:
        raw = iso.group(1).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    uk = re.search(r"на\s+(\d{1,2})\s+([а-яіїєґ]+)\s+(\d{4})", html, re.I)
    if uk:
        month = UA_MONTHS.get(uk.group(2).lower())
        if month:
            try:
                return datetime(int(uk.group(3)), month, int(uk.group(1)), tzinfo=timezone.utc)
            except ValueError:
                return None
    return None


def stamp_is_fresh(stamp: datetime | None) -> bool:
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)
    return age.total_seconds() <= ALT_MAX_AGE_HOURS * 3600


def classify_official_fuel(kind: str, brand: str = "") -> str | None:
    blob = f"{kind} {brand}".lower()
    if "adblue" in blob or "адблу" in blob:
        return None
    if "газ" in blob or blob.strip() in {"lpg", "газ"}:
        return "lpg"
    if any(x in blob for x in ("100", "а-98", "а98", "mustang100")):
        return None
    dieselish = "дп" in blob or "дизель" in blob or "diesel" in blob
    if dieselish:
        if any(x in blob for x in ("mustang", "pulls", "ventus", "evox", "perfekt", "upgdiesel", "upg diesel", "energy", "extro", "преміум", "премиум", "+", "фірм")):
            return "dieselplus"
        return "diesel"
    if "92" in blob:
        return "a92"
    if "95" in blob:
        if any(x in blob for x in ("mustang", "pulls", "ventus", "evox", "perfekt", "upg95", "upg 95", "energy", "extro", "преміум", "премиум", "+")):
            return "a95plus"
        return "a95"
    if "energy" in blob:
        return "a95plus"
    return None


def parse_wog_official(html: str) -> dict[str, float]:
    fuels: dict[str, float] = {}
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        return fuels
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return fuels

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("i_am_page_element") == "block.fuels_fuel" and "price" in node:
                key = classify_official_fuel(str(node.get("type") or ""), str(node.get("brand") or ""))
                price = kopiyky_to_uah(node.get("price"))
                if key and price is not None:
                    fuels[key] = price
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(payload)
    return fuels


def parse_okko_official(html: str) -> dict[str, float]:
    fuels: dict[str, float] = {}
    face = re.search(r'class="face".*?</ul>', html, re.S)
    chunk = face.group(0) if face else html
    pairs = re.findall(
        r'text-anchor="middle"[^>]*>([^<]+)</text>.*?class="price"[^>]*>\s*(\d+)\s*<sup[^>]*>\s*(\d+)',
        chunk,
        re.S | re.I,
    )
    seen_dp = 0
    seen_95 = 0
    for mask, whole, frac in pairs:
        label = re.sub(r"\s+", " ", mask).strip().lower()
        price = parse_number(f"{whole}.{frac}")
        if price is None:
            continue
        if "adblue" in label or label == "100":
            continue
        if "газ" in label:
            fuels["lpg"] = price
            continue
        if "дп" in label:
            seen_dp += 1
            fuels["dieselplus" if seen_dp == 1 else "diesel"] = price
            continue
        if label == "95":
            seen_95 += 1
            fuels["a95plus" if seen_95 == 1 else "a95"] = price
    return fuels


def parse_shinapro(html: str) -> tuple[dict[str, dict[str, float]], str | None]:
    stamp = parse_page_stamp(html)
    if not stamp_is_fresh(stamp):
        return {}, None
    stamp_label = stamp.astimezone().strftime("%d.%m.%Y") if stamp else None
    table = re.search(r'class="fp-tbl".*?</table>', html, re.S | re.I)
    chunk = table.group(0) if table else html
    body = re.search(r"<tbody>(.*?)</tbody>", chunk, re.S | re.I)
    if not body:
        return {}, stamp_label
    out: dict[str, dict[str, float]] = {}
    keys = ("a95", "a95plus", "a92", "diesel", "dieselplus", "a100", "lpg")
    for row in re.finditer(r"<tr>(.*?)</tr>", body.group(1), re.S | re.I):
        name_m = re.search(r"<th[^>]*>(.*?)</th>", row.group(1), re.S | re.I)
        if not name_m:
            continue
        name = re.sub(r"<[^>]+>", "", name_m.group(1)).strip()
        aliases = SHINA_ALIASES.get(name)
        if not aliases:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S | re.I)
        fuels: dict[str, float] = {}
        for key, cell in zip(keys, cells):
            if key == "a100":
                continue
            if re.search(r"—|&mdash;|&ndash;|^[\s\-]*$", cell):
                continue
            raw = re.sub(r'<span class="d">.*?</span>', "", cell, flags=re.S | re.I)
            found = re.search(r"(\d+[.,]\d{2})", raw)
            price = parse_number(found.group(1) if found else raw)
            if price is not None:
                fuels[key] = price
        if fuels:
            for alias in aliases:
                out[alias] = dict(fuels)
    return out, stamp_label


def fetch_alt_prices() -> tuple[dict[str, dict[str, float]], dict[str, str], list[str]]:
    """Official network sites first, then a same-day aggregator."""
    merged: dict[str, dict[str, float]] = {}
    sources: dict[str, str] = {}
    notes: list[str] = []

    jobs = [
        ("okko", OKKO_FUELS, "okko.ua"),
        ("wog", WOG_FUELS, "wog.ua"),
        ("shina", SHINA_PRICES, "shinapro.in.ua"),
    ]

    def load_one(job: tuple[str, str, str]) -> tuple[str, str, str, str]:
        kind, url, label = job
        try:
            return kind, label, fetch(url, timeout=18), ""
        except Exception as exc:
            return kind, label, "", str(exc)

    pages: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for kind, label, html, err in pool.map(load_one, jobs):
            if html:
                pages[kind] = (label, html)
            elif err:
                notes.append(f"{label}: {err}")

    official = [
        ("okko", ("ОККО", "OKKO"), parse_okko_official),
        ("wog", ("WOG",), parse_wog_official),
    ]
    for kind, aliases, parser in official:
        if kind not in pages:
            continue
        label, html = pages[kind]
        fuels = parser(html)
        if not fuels:
            continue
        for alias in aliases:
            merged[alias] = dict(fuels)
            sources[alias] = f"{label} · сьогодні"
        notes.append(f"{'/'.join(aliases)} · {label}")

    if "shina" in pages:
        label, html = pages["shina"]
        extra, stamp = parse_shinapro(html)
        for alias, fuels in extra.items():
            if alias in merged:
                gap = {k: v for k, v in fuels.items() if k not in merged[alias]}
                if gap:
                    merged[alias].update(gap)
            else:
                merged[alias] = dict(fuels)
                sources[alias] = f"{label} · {stamp}" if stamp else label
                notes.append(f"{alias} · {label}")
    return merged, sources, notes


def needs_alt_price(current: float | None, alt: float | None, regular: float | None) -> bool:
    if alt is None:
        return False
    if current is None:
        return True
    if regular is not None and current == regular and alt != regular:
        return True
    return False


def overlay_alt_prices(
    national: dict[str, dict[str, float | None]],
    regional: dict[str, dict[str, dict[str, float | None]]],
    alt: dict[str, dict[str, float]],
    alt_sources: dict[str, str],
) -> dict[str, dict[str, str]]:
    used: dict[str, dict[str, str]] = {}
    for name, prices in national.items():
        extra = alt.get(name)
        if not extra:
            continue
        for key in FUEL_KEYS:
            regular = prices.get("diesel") if key == "dieselplus" else prices.get("a95") if key == "a95plus" else None
            if needs_alt_price(prices.get(key), extra.get(key), regular):
                prices[key] = extra[key]
                used.setdefault(name, {})[key] = alt_sources.get(name, "сайт мережі")

    for mapping in regional.values():
        for name, prices in mapping.items():
            nat = national.get(name, {})
            extra = alt.get(name)
            for key in ("dieselplus", "a95plus"):
                regular_key = "diesel" if key == "dieselplus" else "a95"
                current = prices.get(key)
                regular = prices.get(regular_key)
                nat_branded = nat.get(key)
                nat_regular = nat.get(regular_key)
                if current is not None and (regular is None or current != regular):
                    continue
                if (
                    nat_branded is not None
                    and nat_regular is not None
                    and regular is not None
                    and nat_branded != nat_regular
                ):
                    prices[key] = round(regular + (nat_branded - nat_regular), 2)
                    if name in used and key in used[name]:
                        used.setdefault(name, {})[key] = used[name][key]
                    elif extra and extra.get(key) is not None:
                        used.setdefault(name, {})[key] = alt_sources.get(name, "сайт мережі")
                elif extra and needs_alt_price(current, extra.get(key), regular):
                    prices[key] = extra[key]
                    used.setdefault(name, {})[key] = alt_sources.get(name, "сайт мережі")
    return used


class ZebraParser(HTMLParser):
    """Parse Minfin zebra tables: operator + A95+ / A95 / A92 / diesel / LPG."""

    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.in_caption = False
        self.in_cell = False
        self.cell_tag = ""
        self.colspan = 1
        self.cell_parts: list[str] = []
        self.row: list[tuple[str, str, int]] = []
        self.caption = ""
        self.page_updated = ""
        self.national: dict[str, dict[str, float | None]] = {}
        self.regional: dict[str, dict[str, dict[str, float | None]]] = {}
        self.region = NATIONAL
        self._seen_data = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k: (v or "") for k, v in attrs}
        if tag == "table" and "zebra" in ad.get("class", ""):
            self.in_table = True
            return
        if not self.in_table:
            return
        if tag == "caption":
            self.in_caption = True
            return
        if tag == "tr":
            self.row = []
            return
        if tag in {"td", "th"}:
            self.in_cell = True
            self.cell_tag = tag
            self.colspan = int(ad.get("colspan") or "1")
            self.cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "caption" and self.in_caption:
            self.in_caption = False
            return
        if tag in {"td", "th"} and self.in_cell:
            text = re.sub(r"\s+", " ", "".join(self.cell_parts)).strip()
            self.row.append((self.cell_tag, text, self.colspan))
            self.in_cell = False
            return
        if tag == "tr" and self.in_table and self.row:
            self._consume_row(self.row)
            self.row = []
            return
        if tag == "table" and self.in_table:
            self.in_table = False

    def handle_data(self, data: str) -> None:
        if self.in_caption:
            self.caption += data
        if self.in_cell:
            self.cell_parts.append(data)
        if "останнє оновлення" in data.lower() or "останнє оновлення" in data:
            self.page_updated = data.strip()
        if "оновлення" in data and re.search(r"\d{2}\.\d{2}\.\d{4}", data):
            if not self.page_updated:
                self.page_updated = data.strip()

    def _consume_row(self, row: list[tuple[str, str, int]]) -> None:
        texts = [cell[1] for cell in row]
        if not texts:
            return
        joined = " ".join(texts)
        if "Оператор" in joined and any(x in joined for x in ("А 95", "ДП", "Газ")):
            return
        first = row[0]
        if first[0] == "th" and "обл" in first[1].lower():
            self.region = first[1]
            self.regional.setdefault(self.region, {})
            return
        if first[0] != "td":
            return
        name = texts[0]
        if not name or name == "Оператор":
            return
        nums = [parse_number(t) for t in texts[1:] if t != name]
        # Skip the empty logo/discount column if present (None first after name).
        if nums and nums[0] is None and len(nums) >= 6:
            nums = nums[1:]
        elif len(nums) > 5:
            nums = nums[-5:]
        while len(nums) < 5:
            nums.append(None)
        payload = {
            "a95plus": nums[0],
            "a95": nums[1],
            "a92": nums[2],
            "diesel": nums[3],
            "dieselplus": None,
            "lpg": nums[4],
        }
        if self.region == NATIONAL:
            self.national[name] = payload
        else:
            self.regional.setdefault(self.region, {})[name] = payload
        self._seen_data = True


def scrape_minfin() -> dict[str, Any]:
    tm_html = fetch(MINFIN_TM)
    tm = ZebraParser()
    tm.feed(tm_html)
    tm.close()

    detail = ZebraParser()
    try:
        detail.feed(fetch(MINFIN_DETAIL))
        detail.close()
    except (URLError, TimeoutError, OSError):
        pass

    attach_branded_diesel(tm.national, detail.regional, load_json(PARTNERS, {"partners": []}))
    alt, alt_sources, alt_notes = fetch_alt_prices()
    price_sources = overlay_alt_prices(tm.national, detail.regional, alt, alt_sources)

    date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", tm.caption or tm.page_updated or "")
    upd = re.search(r"останнє оновлення:\s*([\d.\s:]+)", tm_html, re.I)
    caption = re.sub(r"\s+", " ", tm.caption).strip()
    if alt_notes:
        extra = " · ".join(alt_notes)
        caption = f"{caption} · ДП+ з мереж: {extra}" if caption else f"ДП+ з мереж: {extra}"
    return {
        "fetched_at": now_iso(),
        "source": "Мінфін + сайти мереж" if price_sources else "Мінфін / Консалтингова група А-95",
        "source_url": MINFIN_TM,
        "source_date": (upd.group(1).strip() if upd else None) or (date_match.group(1) if date_match else None),
        "caption": caption,
        "national": tm.national,
        "regional": detail.regional,
        "price_sources": price_sources,
        "alt_notes": alt_notes,
        "live": bool(tm.national),
    }


def _overrides_map(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict) and isinstance(raw.get("overrides"), dict):
        return raw["overrides"]
    return raw if isinstance(raw, dict) else {}


def load_overrides() -> dict[str, Any]:
    for path in (DATA / "discounts.local.json", OVERRIDES):
        found = _overrides_map(load_json(path, {}))
        if found:
            return found
    try:
        from discounts_bundled import BUNDLED_OVERRIDES
    except ImportError:
        return {}
    return _overrides_map(BUNDLED_OVERRIDES)


def parse_cut(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def same_cut(a: Any, b: Any) -> bool:
    left, right = parse_cut(a), parse_cut(b)
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return abs(left - right) < 0.001


def merge_partners(doc: dict[str, Any]) -> dict[str, Any]:
    overrides = load_overrides()
    merged = json.loads(json.dumps(doc))
    for partner in merged.get("partners", []):
        discounts = dict(partner.get("discounts") or {})
        over = overrides.get(partner.get("id"), {})
        if isinstance(over, dict):
            for key in FUEL_KEYS:
                if key in over:
                    discounts[key] = parse_cut(over[key])
        partner["discounts"] = discounts
    return merged


def discounts_editor() -> dict[str, Any]:
    catalog = load_json(PARTNERS, {"partners": []})
    overrides = load_overrides()
    rows = []
    dirty = False
    for partner in catalog.get("partners", []):
        current = dict(partner.get("discounts") or {})
        over = overrides.get(partner["id"], {})
        if isinstance(over, dict):
            for key in FUEL_KEYS:
                if key in over:
                    current[key] = parse_cut(over[key])
                    dirty = True
        rows.append(
            {
                "id": partner["id"],
                "name": partner["name"],
                "accent": partner.get("accent"),
                "branded": partner.get("branded") or {},
                "catalog": partner.get("discounts") or {},
                "current": current,
                "overridden": bool(over),
            }
        )
    return {"ok": True, "rows": rows, "keys": list(FUEL_KEYS), "customized": dirty}


def save_overrides(form: dict[str, Any]) -> dict[str, Any]:
    catalog = {p["id"]: p.get("discounts") or {} for p in load_json(PARTNERS, {"partners": []}).get("partners", [])}
    overrides: dict[str, Any] = {}
    for pid, vals in form.items():
        if pid not in catalog or not isinstance(vals, dict):
            continue
        diff = {}
        for key in FUEL_KEYS:
            if key not in vals:
                continue
            incoming = parse_cut(vals.get(key))
            if not same_cut(incoming, catalog[pid].get(key)):
                diff[key] = incoming
        if "diesel" in diff and "dieselplus" not in diff and "dieselplus" not in vals:
            diff["dieselplus"] = diff["diesel"]
        if diff:
            overrides[pid] = diff
    payload = {"updated": now_iso(), "overrides": overrides}
    save_json(OVERRIDES, payload)
    write_bundled_overrides(payload)
    return sync_discounts_to_origin()


def reset_overrides() -> dict[str, Any]:
    payload = {"updated": now_iso(), "overrides": {}}
    save_json(OVERRIDES, payload)
    write_bundled_overrides(payload)
    return sync_discounts_to_origin()


def write_bundled_overrides(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=4)
    body = body.replace(": true", ": True").replace(": false", ": False").replace(": null", ": None")
    (ROOT / "discounts_bundled.py").write_text(
        '"""Local Army+ cuts shipped with the app so Vercel cannot miss the JSON file."""\n\n'
        f"BUNDLED_OVERRIDES = {body}\n",
        encoding="utf-8",
    )


def sync_discounts_to_origin() -> dict[str, Any]:
    if is_hosted() or not (ROOT / ".git").exists():
        return {"synced": False, "detail": "no git"}
    files = ["data/discounts.local.json", "discounts_bundled.py"]
    try:
        subprocess.run(["git", "add", "--", *files], cwd=ROOT, check=True, capture_output=True, text=True)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet", "--", *files], cwd=ROOT)
        if staged.returncode != 0:
            commit = subprocess.run(
                ["git", "commit", "-m", "Sync local Army+ discounts to production."],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            if commit.returncode != 0:
                return {"synced": False, "detail": (commit.stderr or commit.stdout).strip()}
        push = subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT, capture_output=True, text=True)
        if push.returncode != 0:
            return {"synced": False, "detail": (push.stderr or push.stdout).strip() or "push failed"}
        return {"synced": True}
    except Exception as exc:
        return {"synced": False, "detail": str(exc)}


def rebuild_prices() -> dict[str, Any]:
    partners_doc = merge_partners(load_json(PARTNERS, {"partners": []}))
    cache = load_json(CACHE, {})
    state = build_state(cache if cache.get("national") else None, partners_doc)
    attach_schedule(state)
    with _lock:
        _state.clear()
        _state.update(state)
    return attach_schedule(dict(_state))


def classify_fuel_name(name: str) -> str | None:
    n = re.sub(r"<[^>]+>", "", name).lower()
    n = n.replace("&shy;", "").replace("\xa0", " ")
    if "газ" in n:
        return "lpg"
    if "дизель" in n or n.startswith("дп") or " дп" in n:
        if any(token in n for token in ("преміум", "премиум", "pulls", "mustang", "evox", "ventus", "perfekt", "upgdiesel", "energy", "extro", "фірм", "plus", "дп+", "must")):
            return "dieselplus"
        return "diesel"
    if "92" in n:
        return "a92"
    if "95" in n and any(token in n for token in ("+", "преміум", "премиум", "pulls", "mustang", "evox", "ventus", "perfekt", "upg95", "energy", "extro")):
        return "a95plus"
    if "95" in n:
        return "a95"
    return None


def parse_brand_card(html: str) -> dict[str, float]:
    fuels: dict[str, float] = {}
    for match in re.finditer(
        r"<td align='left'>(.*?)</td>\s*<td.*?</td>\s*<td[^>]*><big>(.*?)</big>",
        html,
        re.I | re.S,
    ):
        key = classify_fuel_name(match.group(1))
        price = parse_number(match.group(2))
        if key and price is not None:
            fuels[key] = price
    return fuels


def attach_branded_diesel(
    national: dict[str, dict[str, float | None]],
    regional: dict[str, dict[str, dict[str, float | None]]],
    partners_doc: dict[str, Any],
) -> None:
    jobs = []
    for partner in partners_doc.get("partners", []):
        slug = partner.get("slug")
        if not slug:
            continue
        for alias in partner.get("minfin", []):
            jobs.append((alias, slug))

    extras: dict[str, dict[str, float]] = {}

    def load_one(item: tuple[str, str]) -> tuple[str, dict[str, float]]:
        alias, slug = item
        try:
            return alias, parse_brand_card(fetch(f"https://index.minfin.com.ua/ua/markets/fuel/tm/{slug}/"))
        except Exception:
            return alias, {}

    if jobs:
        with ThreadPoolExecutor(max_workers=6) as pool:
            for alias, fuels in pool.map(load_one, jobs):
                extras[alias] = fuels

    for name, prices in national.items():
        branded = extras.get(name, {}).get("dieselplus")
        prices["dieselplus"] = branded if branded is not None else prices.get("diesel")

    for mapping in regional.values():
        for name, prices in mapping.items():
            nat = national.get(name, {})
            if prices.get("dieselplus") is not None:
                continue
            if (
                nat.get("dieselplus") is not None
                and nat.get("diesel") is not None
                and prices.get("diesel") is not None
                and nat["dieselplus"] != nat["diesel"]
            ):
                prices["dieselplus"] = round(prices["diesel"] + (nat["dieselplus"] - nat["diesel"]), 2)
            else:
                prices["dieselplus"] = prices.get("diesel")


def partner_prices(partner: dict[str, Any], price_map: dict[str, dict[str, float | None]]) -> dict[str, float | None]:
    empty = {"a95plus": None, "a95": None, "a92": None, "diesel": None, "dieselplus": None, "lpg": None}
    for alias in partner.get("minfin", []):
        if alias in price_map:
            found = dict(empty)
            found.update(price_map[alias])
            if found.get("dieselplus") is None:
                found["dieselplus"] = found.get("diesel")
            return found
    return empty


def apply_discounts(
    partner: dict[str, Any],
    prices: dict[str, float | None],
    sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    discounts = partner.get("discounts", {})
    real: dict[str, float | None] = {}
    for key, retail in prices.items():
        cut = discounts.get(key)
        if cut is None and key == "dieselplus":
            cut = discounts.get("diesel")
        if retail is None or cut is None:
            real[key] = None
        else:
            real[key] = round(max(0.0, retail - float(cut)), 2)
    return {"retail": prices, "discount": discounts, "real": real, "sources": sources or {}}


def partner_sources(partner: dict[str, Any], sources_map: dict[str, Any]) -> dict[str, str]:
    for alias in partner.get("minfin", []):
        found = sources_map.get(alias)
        if isinstance(found, dict) and found:
            return {k: str(v) for k, v in found.items()}
    return {}


def ensure_dieselplus(data: dict[str, Any]) -> None:
    for prices in (data.get("national") or {}).values():
        if isinstance(prices, dict) and prices.get("dieselplus") is None:
            prices["dieselplus"] = prices.get("diesel")
    for mapping in (data.get("regional") or {}).values():
        for prices in mapping.values():
            if isinstance(prices, dict) and prices.get("dieselplus") is None:
                prices["dieselplus"] = prices.get("diesel")


def build_state(scraped: dict[str, Any] | None, partners_doc: dict[str, Any], error: str | None = None) -> dict[str, Any]:
    cache = load_json(CACHE, {})
    data = scraped if scraped and scraped.get("national") else cache
    ensure_dieselplus(data)
    used_live = bool(scraped and scraped.get("national"))
    if used_live:
        save_json(CACHE, scraped)

    national = data.get("national") or {}
    regional = data.get("regional") or {}
    sources_map = data.get("price_sources") or {}
    partners_out = []
    for partner in partners_doc.get("partners", []):
        src = partner_sources(partner, sources_map)
        by_region: dict[str, Any] = {
            NATIONAL: apply_discounts(partner, partner_prices(partner, national), src)
        }
        for region, mapping in regional.items():
            by_region[region] = apply_discounts(partner, partner_prices(partner, mapping), src)
        partners_out.append(
            {
                "id": partner["id"],
                "name": partner["name"],
                "accent": partner.get("accent"),
                "branded": partner.get("branded") or {},
                "extras": partner.get("extras", []),
                "limit": partner.get("limit"),
                "shareable": bool(partner.get("shareable")),
                "regions": by_region,
            }
        )

    regions = [NATIONAL] + sorted(regional.keys())
    return {
        "ok": True,
        "live": used_live or bool(data.get("live")),
        "from_cache": not used_live,
        "error": error,
        "fetched_at": data.get("fetched_at"),
        "built_at": now_iso(),
        "source": data.get("source"),
        "source_url": data.get("source_url"),
        "source_date": data.get("source_date"),
        "price_sources": data.get("price_sources") or {},
        "alt_notes": data.get("alt_notes") or [],
        "caption": data.get("caption"),
        "program": partners_doc.get("program"),
        "disclaimer": partners_doc.get("disclaimer"),
        "partners_updated": partners_doc.get("updated"),
        "customized": bool(load_overrides()),
        "hosted": is_hosted(),
        "regions": regions,
        "partners": partners_out,
    }


def refresh(force: bool = False) -> dict[str, Any]:
    partners_doc = merge_partners(load_json(PARTNERS, {"partners": []}))
    error = None
    scraped = None
    try:
        scraped = scrape_minfin()
    except Exception as exc:  # network / parse — keep last cache
        error = str(exc)
    state = build_state(scraped, partners_doc, error)
    schedule_next()
    attach_schedule(state)
    with _lock:
        _state.clear()
        _state.update(state)
    print(f"prices synced  next auto {state.get('next_refresh_at')}", flush=True)
    return state


def cache_age_sec(payload: dict[str, Any] | None) -> float | None:
    raw = (payload or {}).get("fetched_at")
    if not raw:
        return None
    try:
        stamp = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()


def current_state() -> dict[str, Any]:
    cache = load_json(CACHE, {})
    age = cache_age_sec(cache)
    if cache.get("national") and age is not None and age < REFRESH_SEC:
        return rebuild_prices()
    return refresh()


def public_state(do_refresh: bool = False, rebuild: bool = False) -> dict[str, Any]:
    if is_hosted() and not rebuild:
        do_refresh = True
    if do_refresh:
        payload = refresh(force=True)
    elif rebuild:
        payload = rebuild_prices()
    else:
        payload = current_state()
    out = dict(payload)
    out["hosted"] = is_hosted()
    if is_hosted():
        out.pop("access", None)
        return out
    return with_access(out)


def monitor_loop() -> None:
    while True:
        with _lock:
            deadline = _next_at or (time.time() + REFRESH_SEC)
        wait = max(0.25, deadline - time.time())
        _wake.wait(timeout=wait)
        _wake.clear()
        with _lock:
            due = time.time() >= (_next_at or 0) - 0.1
        if not due:
            continue
        try:
            refresh()
        except Exception:
            schedule_next()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _json(self, payload: Any, code: int = 200) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            self._json(public_state())
            return
        if path == "/api/refresh":
            self._json(public_state(do_refresh=True))
            return
        if path == "/api/discounts":
            if is_hosted():
                self._json({"ok": False, "error": "Редактор знижок лише локально"}, 404)
                return
            self._json(discounts_editor())
            return
        if path in {"/", "/index.html"}:
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "Некоректний JSON"}, 400)
            return
        if path in {"/api/discounts", "/api/discounts/reset"}:
            if is_hosted():
                self._json({"ok": False, "error": "Редактор знижок лише локально"}, 404)
                return
        if path == "/api/discounts":
            published = save_overrides(body.get("overrides") or {})
            self._json({"ok": True, "published": published, "editor": discounts_editor(), "state": public_state(rebuild=True)})
            return
        if path == "/api/discounts/reset":
            published = reset_overrides()
            self._json({"ok": True, "published": published, "editor": discounts_editor(), "state": public_state(rebuild=True)})
            return
        self._json({"ok": False, "error": "unknown endpoint"}, 404)


def lan_ip() -> str | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def _ip_kind(ip: str) -> str:
    a, b, *_ = (int(p) for p in ip.split("."))
    if a == 100 and 64 <= b <= 127:
        return "mesh"
    return "lan"


def local_ipv4s() -> list[str]:
    found: list[str] = []
    primary = lan_ip()
    if primary:
        found.append(primary)
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def access_info() -> dict[str, Any]:
    links = []
    for ip in local_ipv4s():
        kind = _ip_kind(ip)
        links.append({
            "kind": kind,
            "label": "Tailscale / mesh" if kind == "mesh" else "Wi-Fi / LAN",
            "url": f"http://{ip}:{_listen_port}/",
            "ip": ip,
        })
    phone = next((x["url"] for x in links if x["kind"] == "lan"), None)
    mesh = next((x["url"] for x in links if x["kind"] == "mesh"), None)
    return {
        "local": f"http://127.0.0.1:{_listen_port}/",
        "phone": phone or mesh,
        "mesh": mesh,
        "links": links,
        "host": socket.gethostname(),
        "port": _listen_port,
    }


def with_access(state: dict[str, Any]) -> dict[str, Any]:
    out = dict(state)
    out["access"] = access_info()
    return out


def main() -> None:
    global _listen_port
    parser = argparse.ArgumentParser(description="AZS WATCH dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    _listen_port = args.port

    DATA.mkdir(parents=True, exist_ok=True)
    print("AZS WATCH // ARMY+  —  loading prices...", flush=True)
    refresh()
    threading.Thread(target=monitor_loop, daemon=True).start()

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    info = access_info()
    print(f"AZS WATCH online  {info['local']}", flush=True)
    if info["phone"]:
        print(f"iPhone            {info['phone']}", flush=True)
    if info.get("mesh"):
        print(f"away / Tailscale  {info['mesh']}", flush=True)
    print("same Wi-Fi, iPhone hotspot, or Tailscale. If Safari fails, run allow-phone.bat as admin.", flush=True)
    print("Stop: Ctrl+C", flush=True)
    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(0.6), webbrowser.open(info["local"])), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nAZS WATCH offline")


if __name__ == "__main__":
    main()

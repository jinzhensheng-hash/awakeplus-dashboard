from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path


BASE_URL = "https://www.awakeplus.co.kr"
SOURCES = {
    "todaytop15": f"{BASE_URL}/home/todaytop15",
    "sin": f"{BASE_URL}/board/sin",
    "allnewhigh": f"{BASE_URL}/board/allnewhigh",
}

MARKET_SYMBOLS = [
    {"group": "한국", "name": "KOSPI", "symbol": "^KS11", "kind": "index"},
    {"group": "한국", "name": "KOSDAQ", "symbol": "^KQ11", "kind": "index"},
    {"group": "미국", "name": "S&P500", "symbol": "^GSPC", "kind": "index"},
    {"group": "미국", "name": "NASDAQ", "symbol": "^IXIC", "kind": "index"},
    {"group": "미국", "name": "DOW", "symbol": "^DJI", "kind": "index"},
    {"group": "일본", "name": "Nikkei225", "symbol": "^N225", "kind": "index"},
    {"group": "중국", "name": "Shanghai", "symbol": "000001.SS", "kind": "index"},
    {"group": "대만", "name": "TAIEX", "symbol": "^TWII", "kind": "index"},
    {"group": "환율", "name": "USD/KRW", "symbol": "KRW=X", "kind": "fx"},
    {"group": "환율", "name": "JPY/KRW", "symbol": "JPYKRW=X", "kind": "fx"},
    {"group": "환율", "name": "CNY/KRW", "symbol": "CNYKRW=X", "kind": "fx"},
]


@dataclass
class Link:
    href: str
    text: str


class TextAndLinksParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.links: list[Link] = []
        self._href_stack: list[str | None] = []
        self._link_text: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "a":
            href = dict(attrs).get("href")
            self._href_stack.append(href)
            self._link_text.append("")
        elif tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3"}:
            self._push_line("")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "a" and self._href_stack:
            href = self._href_stack.pop()
            text = normalize_ws(self._link_text.pop()) if self._link_text else ""
            if href and text:
                self.links.append(Link(href=urllib.parse.urljoin(BASE_URL, href), text=text))
        elif tag in {"p", "div", "li", "tr", "h1", "h2", "h3"}:
            self._push_line("")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = html.unescape(data)
        if self._href_stack and self._link_text:
            self._link_text[-1] += " " + text
        self._push_line(text)

    def _push_line(self, text: str) -> None:
        text = normalize_ws(text)
        if text:
            self.lines.append(text)


def normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fetch(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AWAKEPLUS-Dashboard/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    cookie = os.environ.get("AWAKEPLUS_COOKIE", "").strip()
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_html(content: str) -> TextAndLinksParser:
    parser = TextAndLinksParser()
    parser.feed(content)
    return parser


def ensure_dirs(root: Path) -> None:
    for path in [
        root / "awakeplus" / "raw" / "todaytop15",
        root / "awakeplus" / "raw" / "sin",
        root / "awakeplus" / "raw" / "allnewhigh",
        root / "awakeplus" / "data",
        root / "data",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_unique_csv(
    path: Path,
    rows: list[dict[str, str]],
    key_fields: list[str],
    replace_scope_fields: list[str] | None = None,
) -> None:
    if not rows:
        return

    merged: dict[tuple[str, ...], dict[str, str]] = {}
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                merged[tuple(row.get(field, "") for field in key_fields)] = row
    if replace_scope_fields:
        scopes = {tuple(row.get(field, "") for field in replace_scope_fields) for row in rows}
        merged = {
            key: row
            for key, row in merged.items()
            if tuple(row.get(field, "") for field in replace_scope_fields) not in scopes
        }
    for row in rows:
        merged[tuple(row.get(field, "") for field in key_fields)] = row

    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged.values())


def parse_date_from_lines(lines: list[str]) -> tuple[str, str]:
    for line in lines:
        match = re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*기준", line)
        if match:
            return match.group(1), match.group(2)
    for line in lines:
        match = re.search(r"작성일\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})", line)
        if match:
            return match.group(1), match.group(2)
    for line in lines:
        match = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", line)
        if match:
            y, m, d = map(int, match.groups())
            return f"{y:04d}-{m:02d}-{d:02d}", ""
    return datetime.now().strftime("%Y-%m-%d"), ""


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def in_date_range(value: str, start: date | None, end: date | None) -> bool:
    try:
        current = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False
    return (start is None or current >= start) and (end is None or current <= end)


def extract_date_from_text(text: str) -> str:
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return "-".join(match.groups())
    match = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", text)
    if match:
        y, m, d = map(int, match.groups())
        return f"{y:04d}-{m:02d}-{d:02d}"
    return ""


def extract_available_top15_dates(content: str) -> list[str]:
    match = re.search(r"const\s+dates\s*=\s*\[([^\]]+)\]", content)
    if match:
        dates = re.findall(r'"(\d{4}-\d{2}-\d{2})"', match.group(1))
        return list(dict.fromkeys(dates))
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", content)
    return list(dict.fromkeys(dates))


def clean_stock_header(line: str) -> tuple[str, str, str]:
    stars = str(line.count("⭐"))
    theme = ""
    if "#" in line:
        theme = "#".join(line.split("#")[1:]).strip()
    name = re.split(r"\s*⭐|#", line, maxsplit=1)[0].strip()
    return name, stars, theme


def top15_header_at(lines: list[str], index: int) -> tuple[int | None, list[str]]:
    line = lines[index] if index < len(lines) else ""
    if not line or line.startswith("#") or line in {"←", "→", "❗", "❗️"}:
        return None, []
    theme_lines: list[str] = []
    for lookahead in range(index + 1, min(index + 5, len(lines))):
        candidate = lines[lookahead]
        if re.match(r"^[+-]?\d+(?:\.\d+)?%$", candidate):
            return lookahead, theme_lines
        if candidate.startswith("#"):
            theme_lines.append(candidate)
            continue
        return None, []
    return None, []


def parse_top15(content: str, collected_at: str) -> tuple[list[dict[str, str]], dict[str, object]]:
    parser = parse_html(content)
    lines = [line for line in parser.lines if line not in {"‹", "›"}]
    date, time_text = parse_date_from_lines(lines)
    start = 0
    for i, line in enumerate(lines):
        if re.match(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*기준", line):
            start = i + 1
            break

    rows: list[dict[str, str]] = []
    rank = 1
    i = start
    while i < len(lines) - 1:
        line = lines[i]
        if line.startswith("#") or line in {"←", "→"}:
            i += 1
            continue
        pct_index, theme_lines = top15_header_at(lines, i)
        if pct_index is not None:
            name, stars, inline_theme = clean_stock_header(line)
            theme = "#".join([part.strip("# ") for part in ([inline_theme] if inline_theme else []) + theme_lines if part.strip("# ")])
            change_pct = lines[pct_index].replace("+", "").replace("%", "")
            market_cap = ""
            trading_value = ""
            special_signals: list[str] = []
            reasons: list[str] = []
            i = pct_index + 1
            while i < len(lines):
                candidate = lines[i]
                if top15_header_at(lines, i)[0] is not None:
                    break
                if "AWAKEPLUS Financial" in candidate:
                    break
                cap_match = re.search(r"시총\s*([^·]+)(?:·\s*거래대금\s*(.+))?", candidate.replace("📊", ""))
                if cap_match:
                    market_cap = normalize_ws(cap_match.group(1))
                    trading_value = normalize_ws(cap_match.group(2) or "")
                elif candidate in {"❗️", "❗"}:
                    if i + 1 < len(lines):
                        special_signals.append(lines[i + 1].strip())
                        i += 1
                elif candidate.startswith("❗"):
                    signal = candidate.replace("❗️", "").replace("❗", "").strip()
                    if signal:
                        special_signals.append(signal)
                elif candidate and not re.match(r"^←|^#|^오늘의|^⚡", candidate):
                    reasons.append(candidate.lstrip("* ").strip())
                i += 1

            rows.append(
                {
                    "date": date,
                    "time": time_text,
                    "rank": str(rank),
                    "stock": name,
                    "theme": theme,
                    "change_pct": change_pct,
                    "market_cap": market_cap,
                    "trading_value": trading_value,
                    "stars": stars,
                    "special_signal": "; ".join(special_signals),
                    "reason": " / ".join(reasons[:3]),
                    "source": "todaytop15",
                    "collected_at": collected_at,
                }
            )
            rank += 1
            continue
        i += 1

    meta = {"date": date, "time": time_text, "count": len(rows), "top_themes": theme_counts(rows)}
    return rows, meta


def theme_counts(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    counts: dict[str, int] = {}
    for row in rows:
        raw = row.get("theme", "")
        for theme in [part.strip() for part in raw.split("#") if part.strip()]:
            counts[theme] = counts.get(theme, 0) + 1
    return [{"theme": theme, "count": count} for theme, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def latest_post_links(
    content: str,
    source: str,
    limit: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[Link]:
    parser = parse_html(content)
    expected = f"/board/{source}/"
    seen: set[str] = set()
    links: list[Link] = []
    for link in parser.links:
        if expected in urllib.parse.urlparse(link.href).path and "신고가" in link.text:
            link_date = extract_date_from_text(link.text)
            if start_date or end_date:
                if not link_date or not in_date_range(link_date, start_date, end_date):
                    continue
            if link.href not in seen:
                seen.add(link.href)
                links.append(link)
        if limit and len(links) >= limit:
            break
    return links


def parse_newhigh_detail(content: str, source: str, url: str, collected_at: str) -> tuple[list[dict[str, str]], dict[str, str]]:
    parser = parse_html(content)
    lines = parser.lines
    date, time_text = parse_date_from_lines(lines)
    title = next((line for line in lines if "\uc2e0\uace0\uac00" in line and ("\uc885\ubaa9" in line or "\ub3cc\ud30c" in line)), "")
    rows: list[dict[str, str]] = []
    category = ""

    def split_summary_stock(value: str, explicit_type: str | None = None) -> tuple[str, str]:
        value = normalize_ws(value)
        types: list[str] = []
        if explicit_type:
            types.append(explicit_type.strip())
        if "/" in value:
            value, trailing = value.split("/", 1)
            if trailing.strip():
                types.append(trailing.strip())
        embedded = re.match(r"^(.+?)\(([^)]+)\)$", value)
        if embedded:
            value = embedded.group(1).strip()
            if embedded.group(2).strip():
                types.insert(0, embedded.group(2).strip())
        return value.strip(), " / ".join(dict.fromkeys(part for part in types if part))

    for line in lines:
        if line.startswith("\u2705") and "(" not in line and not re.search(r"\[\s*[+-]?\d", line):
            category = line.replace("\u2705", "").strip()
            continue
        match = re.match(r"\[\s*([+-]?\d+(?:\.\d+)?)%\s*/\s*([^\]]+)\]\s*(.+?)(?:\(([^)]+)\))?$", line)
        if match:
            change_pct, trading_value, stock_text, newhigh_type = match.groups()
            stock, merged_type = split_summary_stock(stock_text, newhigh_type)
            rows.append(
                {
                    "date": date,
                    "time": time_text,
                    "stock": stock,
                    "category": category,
                    "newhigh_type": merged_type,
                    "change_pct": change_pct,
                    "trading_value": trading_value.strip(),
                    "market_cap": "",
                    "current_price": "",
                    "investment_point": "",
                    "recent_results": "",
                    "source": source,
                    "detail_url": url,
                    "collected_at": collected_at,
                }
            )

    by_stock = {row["stock"]: row for row in rows}
    i = 0
    while i < len(lines):
        header = re.match(r"^\s*(?:\u2705\s*)?(.+?)\(([+-]?\d+(?:\.\d+)?)%\)", lines[i])
        if not header:
            i += 1
            continue
        stock = header.group(1).strip()
        row = by_stock.get(stock)
        if not row:
            row = {
                "date": date,
                "time": time_text,
                "stock": stock,
                "category": category,
                "newhigh_type": "",
                "change_pct": header.group(2),
                "trading_value": "",
                "market_cap": "",
                "current_price": "",
                "investment_point": "",
                "recent_results": "",
                "source": source,
                "detail_url": url,
                "collected_at": collected_at,
            }
            rows.append(row)
            by_stock[stock] = row

        points: list[str] = []
        results: list[str] = []
        mode = ""
        i += 1
        while i < len(lines) and not re.match(r"^\s*(?:\u2705\s*)?.+?\([+-]?\d", lines[i]):
            line = lines[i]
            if line.startswith("\u2757"):
                row["newhigh_type"] = row["newhigh_type"] or line.replace("\u2757\ufe0f", "").replace("\u2757", "").strip()
            elif line.startswith("\uac70\ub798\ub300\uae08"):
                row["trading_value"] = line.split(":", 1)[-1].strip()
            elif line.startswith("\uc2dc\uac00\ucd1d\uc561"):
                row["market_cap"] = line.split(":", 1)[-1].strip()
            elif "\ud604\uc7ac\uac00" in line:
                row["current_price"] = line.split(":", 1)[-1].strip()
            elif "\ud22c\uc790\ud3ec\uc778\ud2b8" in line:
                mode = "points"
            elif "\uc8fc\uc694\uc9c0\ud45c" in line:
                mode = ""
            elif "\ucd5c\uadfc\uc2e4\uc801" in line:
                mode = "results"
            elif mode == "points" and line and not line.startswith("\ucd5c\uadfc\uc2e4\uc801"):
                points.append(line.lstrip("- ").strip())
            elif mode == "results" and re.match(r"^\d{4}\.\dQ\b", line):
                results.append(line.lstrip("- ").strip())
            i += 1
        row["investment_point"] = " / ".join(points[:3])
        row["recent_results"] = " / ".join(results[:5])

    meta = {"date": date, "time": time_text, "title": title, "url": url, "count": str(len(rows))}
    return rows, meta


def merge_newhigh_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        stock = normalize_ws(row.get("stock", ""))
        if not stock:
            continue
        key = (row.get("date", ""), stock)
        if key not in merged:
            merged[key] = dict(row)
            merged[key]["stock"] = stock
            continue
        current = merged[key]
        sources = [part for part in re.split(r"[+,]", current.get("source", "")) if part]
        if row.get("source") and row.get("source") not in sources:
            sources.append(row.get("source", ""))
        current["source"] = "+".join(sources)
        for field in ["category", "newhigh_type", "trading_value", "market_cap", "current_price", "investment_point", "recent_results", "detail_url", "time"]:
            if not current.get(field) and row.get(field):
                current[field] = row.get(field, "")
        if row.get("investment_point") and len(row.get("investment_point", "")) > len(current.get("investment_point", "")):
            current["investment_point"] = row.get("investment_point", "")
        if row.get("recent_results") and len(row.get("recent_results", "")) > len(current.get("recent_results", "")):
            current["recent_results"] = row.get("recent_results", "")
    return list(merged.values())

def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def fetch_market_snapshot() -> dict[str, object]:
    items: list[dict[str, object]] = []
    errors: list[str] = []
    for item in MARKET_SYMBOLS:
        symbol = item["symbol"]
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1y&interval=1d"
        try:
            payload = json.loads(fetch(url))
            result = (payload.get("chart", {}).get("result") or [])[0]
            quote = result.get("indicators", {}).get("quote", [{}])[0]
            opens = quote.get("open", [])
            highs = quote.get("high", [])
            lows = quote.get("low", [])
            closes = [value for value in quote.get("close", []) if isinstance(value, (int, float))]
            if not closes:
                raise ValueError("empty close data")
            current = float(closes[-1])
            previous = float(closes[-2]) if len(closes) > 1 else current
            change = current - previous
            change_pct = (change / previous * 100) if previous else 0
            timestamps = result.get("timestamp") or []
            asof = datetime.fromtimestamp(timestamps[-1]).strftime("%Y-%m-%d %H:%M") if timestamps else ""
            history = []
            for idx, (ts, close) in enumerate(zip(timestamps, quote.get("close", []), strict=False)):
                if isinstance(close, (int, float)):
                    open_value = opens[idx] if idx < len(opens) and isinstance(opens[idx], (int, float)) else close
                    high_value = highs[idx] if idx < len(highs) and isinstance(highs[idx], (int, float)) else max(open_value, close)
                    low_value = lows[idx] if idx < len(lows) and isinstance(lows[idx], (int, float)) else min(open_value, close)
                    history.append(
                        {
                            "date": datetime.fromtimestamp(ts).strftime("%m-%d"),
                            "open": round(float(open_value), 4 if item["kind"] == "fx" else 2),
                            "high": round(float(high_value), 4 if item["kind"] == "fx" else 2),
                            "low": round(float(low_value), 4 if item["kind"] == "fx" else 2),
                            "close": round(float(close), 4 if item["kind"] == "fx" else 2),
                            "value": round(float(close), 4 if item["kind"] == "fx" else 2),
                        }
                    )
            items.append(
                {
                    "group": item["group"],
                    "name": item["name"],
                    "symbol": symbol,
                    "kind": item["kind"],
                    "value": round(current, 4 if item["kind"] == "fx" else 2),
                    "change": round(change, 4 if item["kind"] == "fx" else 2),
                    "change_pct": round(change_pct, 2),
                    "asof": asof,
                    "history": history[-260:],
                }
            )
        except Exception as exc:  # noqa: BLE001 - snapshot should never break stock collection.
            errors.append(f"{symbol}: {exc}")
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "Yahoo Finance chart API",
        "items": items,
        "errors": errors[:5],
    }


def build_leader_scores(today_rows: list[dict[str, str]], newhigh_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    scores: dict[str, dict[str, object]] = {}

    def item(stock: str) -> dict[str, object]:
        if stock not in scores:
            scores[stock] = {"stock": stock, "score": 0, "sources": set(), "signals": [], "theme": ""}
        return scores[stock]

    for row in today_rows:
        target = item(row["stock"])
        target["score"] = int(target["score"]) + 3
        target["sources"].add("TOP15")
        if row.get("theme") and not target.get("theme"):
            target["theme"] = row["theme"]
        try:
            if float(row.get("change_pct") or 0) >= 10:
                target["score"] = int(target["score"]) + 1
                target["signals"].append("상승률 10%+")
        except ValueError:
            pass
        if row.get("special_signal"):
            target["score"] = int(target["score"]) + 2
            target["signals"].append(row["special_signal"])

    appearances: dict[str, int] = {}
    for row in newhigh_rows:
        stock = row.get("stock", "")
        appearances[stock] = appearances.get(stock, 0) + 1
        target = item(stock)
        target["score"] = int(target["score"]) + (4 if "신규" in row.get("newhigh_type", "") else 3)
        target["sources"].add(row.get("source", "newhigh"))
        if row.get("category") and not target.get("theme"):
            target["theme"] = row["category"]

    for stock, count in appearances.items():
        if count >= 2:
            target = item(stock)
            target["score"] = int(target["score"]) + min(5, count)
            target["signals"].append(f"신고가 {count}회")

    result = []
    for value in scores.values():
        result.append(
            {
                "stock": value["stock"],
                "score": value["score"],
                "sources": sorted(value["sources"]),
                "signals": list(dict.fromkeys(value["signals"]))[:4],
                "theme": value.get("theme", ""),
            }
        )
    return sorted(result, key=lambda row: (-int(row["score"]), str(row["stock"])))[:30]


def write_dashboard_data(root: Path, start_date: date | None = None, end_date: date | None = None) -> None:
    today_rows = read_csv_rows(root / "awakeplus" / "data" / "todaytop15.csv")
    newhigh_rows = read_csv_rows(root / "awakeplus" / "data" / "newhigh.csv")
    posts = read_csv_rows(root / "awakeplus" / "data" / "posts.csv")
    if start_date or end_date:
        today_rows = [row for row in today_rows if in_date_range(row.get("date", ""), start_date, end_date)]
        newhigh_rows = [row for row in newhigh_rows if in_date_range(row.get("date", ""), start_date, end_date)]
        posts = [row for row in posts if in_date_range(row.get("date", ""), start_date, end_date)]
    latest_today_date = max((row.get("date", "") for row in today_rows), default="")
    latest_newhigh_date = max((row.get("date", "") for row in newhigh_rows), default="")
    newhigh_raw_count = len(newhigh_rows)
    newhigh_rows = merge_newhigh_rows(newhigh_rows)
    unique_newhigh_count = len(newhigh_rows)
    today_rows = sorted(today_rows, key=lambda row: (row.get("date", ""), int(row.get("rank") or 999)), reverse=True)
    newhigh_rows = sorted(newhigh_rows, key=lambda row: (row.get("date", ""), row.get("stock", "")), reverse=True)

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "todaytop15": today_rows,
        "newhigh": newhigh_rows,
        "posts": posts[-20:],
        "leader_scores": build_leader_scores(today_rows, newhigh_rows),
        "market_snapshot": fetch_market_snapshot(),
        "summary": {
            "range_start": start_date.isoformat() if start_date else "",
            "range_end": end_date.isoformat() if end_date else "",
            "todaytop15_date": latest_today_date,
            "todaytop15_count": len(today_rows),
            "newhigh_date": latest_newhigh_date,
            "newhigh_count": unique_newhigh_count,
            "newhigh_raw_count": newhigh_raw_count,
            "post_count": len(posts),
        },
    }
    js = "window.awakeplusData = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    write_text(root / "data" / "awakeplus_data.js", js)
    embed_dashboard_data(root, js)


def embed_dashboard_data(root: Path, js: str) -> None:
    dashboard = root / "dashboard" / "dashboard.html"
    if not dashboard.exists():
        return
    html_text = dashboard.read_text(encoding="utf-8")
    data_script = f"<script>\n{js}</script>"
    external = '<script src="../data/awakeplus_data.js"></script>'
    inline_pattern = re.compile(r"<script>\s*window\.awakeplusData\s*=\s*[\s\S]*?</script>")
    if inline_pattern.search(html_text):
        html_text = inline_pattern.sub(data_script, html_text, count=1)
    elif external in html_text:
        html_text = html_text.replace(external, data_script, 1)
    else:
        html_text = html_text.replace("<script>", data_script + "\n  <script>", 1)
    dashboard.write_text(html_text, encoding="utf-8")


def collect(root: Path, latest_count: int, start_date: date | None = None, end_date: date | None = None, board_pages: int = 1) -> None:
    ensure_dirs(root)
    collected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    seed_today_html = fetch(SOURCES["todaytop15"])
    available_dates = extract_available_top15_dates(seed_today_html)
    if start_date or end_date:
        target_dates = [value for value in available_dates if in_date_range(value, start_date, end_date)]
    else:
        seed_rows, seed_meta = parse_top15(seed_today_html, collected_at)
        target_dates = [str(seed_meta["date"])]

    total_today_rows = 0
    for target_date in target_dates:
        if target_date == parse_date_from_lines(parse_html(seed_today_html).lines)[0] and not (start_date or end_date):
            today_html = seed_today_html
        else:
            today_html = fetch(f"{SOURCES['todaytop15']}?date={target_date}")
        today_rows, today_meta = parse_top15(today_html, collected_at)
        today_date = str(today_meta["date"])
        if start_date or end_date:
            if not in_date_range(today_date, start_date, end_date):
                continue
        write_text(root / "awakeplus" / "raw" / "todaytop15" / f"{today_date}.html", today_html)
        append_unique_csv(
            root / "awakeplus" / "data" / "todaytop15.csv",
            today_rows,
            ["date", "stock", "source"],
            ["date", "source"],
        )
        total_today_rows += len(today_rows)
        time.sleep(0.35)

    post_rows: list[dict[str, str]] = []
    for source in ["sin", "allnewhigh"]:
        links: list[Link] = []
        for page in range(1, max(1, board_pages) + 1):
            board_url = SOURCES[source] if page == 1 else f"{SOURCES[source]}?page={page}"
            board_html = fetch(board_url)
            board_date = datetime.now().strftime("%Y-%m-%d")
            write_text(root / "awakeplus" / "raw" / source / f"{board_date}_page{page}_list.html", board_html)
            links.extend(latest_post_links(board_html, source, 0, start_date, end_date))
            time.sleep(0.35)
        deduped_links: list[Link] = []
        seen_links: set[str] = set()
        for link in links:
            if link.href not in seen_links:
                seen_links.add(link.href)
                deduped_links.append(link)
        links = deduped_links[:latest_count] if latest_count and not (start_date or end_date) else deduped_links
        for link in links:
            time.sleep(0.5)
            try:
                detail_html = fetch(link.href)
            except urllib.error.URLError as exc:
                print(f"WARN: failed to fetch {link.href}: {exc}", file=sys.stderr)
                continue
            detail_rows, meta = parse_newhigh_detail(detail_html, source, link.href, collected_at)
            detail_date = meta.get("date") or board_date
            write_text(root / "awakeplus" / "raw" / source / f"{detail_date}.html", detail_html)
            append_unique_csv(
                root / "awakeplus" / "data" / "newhigh.csv",
                detail_rows,
                ["date", "stock", "source"],
                ["date", "source"],
            )
            post_rows.append(
                {
                    "source": source,
                    "date": detail_date,
                    "time": meta.get("time", ""),
                    "title": meta.get("title", link.text),
                    "url": link.href,
                    "row_count": str(len(detail_rows)),
                    "collected_at": collected_at,
                }
            )

    append_unique_csv(root / "awakeplus" / "data" / "posts.csv", post_rows, ["source", "url"])
    write_dashboard_data(root, start_date, end_date)
    print(
        json.dumps(
            {
                "todaytop15": {"dates": target_dates, "rows": total_today_rows},
                "posts": len(post_rows),
                "dashboard_data": "data/awakeplus_data.js",
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect AWAKEPLUS leader and new-high data.")
    parser.add_argument("--root", default=".", help="Workspace root")
    parser.add_argument("--latest-count", type=int, default=1, help="How many latest posts to fetch per board")
    parser.add_argument("--start-date", help="Start date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date, YYYY-MM-DD")
    parser.add_argument("--board-pages", type=int, default=1, help="How many board list pages to scan")
    args = parser.parse_args()
    collect(
        Path(args.root).resolve(),
        max(1, args.latest_count),
        parse_iso_date(args.start_date),
        parse_iso_date(args.end_date),
        max(1, args.board_pages),
    )


if __name__ == "__main__":
    main()

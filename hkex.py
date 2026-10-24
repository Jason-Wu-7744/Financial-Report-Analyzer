from __future__ import annotations

import html
import json
import re
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from cninfo import CninfoAnnouncement, _safe_filename


HKEX_ROOT = "https://www1.hkexnews.hk"
HKEX_COMPANY_LIST = f"{HKEX_ROOT}/ncms/script/eds/activestock_sehk_c.json"
HKEX_PREFIX = f"{HKEX_ROOT}/search/prefix.do"
HKEX_TITLE_SEARCH = f"{HKEX_ROOT}/search/titleSearchServlet.do"

_HK_NAME_TRANSLATION = str.maketrans(
    {
        "車": "车", "騰": "腾", "訊": "讯", "匯": "汇", "滙": "汇", "豐": "丰", "國": "国",
        "團": "团", "華": "华", "聯": "联", "電": "电", "網": "网", "銀": "银",
        "業": "业", "實": "实", "藥": "药", "醫": "医", "製": "制", "礦": "矿",
        "產": "产", "發": "发", "達": "达", "龍": "龙", "長": "长", "東": "东",
        "廣": "广", "萬": "万", "證": "证", "險": "险", "貿": "贸", "運": "运",
        "務": "务", "創": "创", "際": "际", "環": "环", "資": "资", "訊": "讯",
        "設": "设", "亞": "亚", "極": "极", "潤": "润", "啤": "啤",
    }
)


def _company_name_key(value: object) -> str:
    """Normalise simplified/traditional names and remove HK share-class suffixes."""
    text = str(value or "").upper().translate(str.maketrans({"－": "-", "Ｗ": "W", "Ｒ": "R", "Ｓ": "S", "Ｂ": "B"}))
    text = re.sub(r"-(?:WR|SW|W|S|B)$", "", text)
    text = re.sub(r"[\s*()（）·‧\-]", "", text).lower()
    return text.translate(_HK_NAME_TRANSLATION)


def normalise_hk_code(value: object) -> str:
    """Return the canonical five-digit HK ticker with a .HK suffix."""
    text = str(value or "").strip().upper().replace(" ", "")
    if text.startswith("HK"):
        text = text[2:]
    if text.endswith(".HK"):
        text = text[:-3]
    text = text[:-2] if text.endswith(".0") else text
    if not re.fullmatch(r"\d{1,5}", text):
        raise ValueError(f"无法识别港股代码：{value}")
    return f"{int(text):05d}.HK"


def is_hk_stock_code(value: object) -> bool:
    text = str(value or "").strip().upper().replace(" ", "")
    if text.endswith(".HK") or text.startswith("HK"):
        try:
            normalise_hk_code(text)
            return True
        except ValueError:
            return False
    return bool(re.fullmatch(r"\d{3,5}(?:\.0)?", text))


def _plain(value: object) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))).strip()


def _search_window(report_year: int, report_type: str) -> tuple[str, str]:
    """Use a broad publication window because HK issuers have non-calendar fiscal years."""
    if report_type == "年度报告":
        start, end = date(report_year - 1, 1, 1), date(report_year + 1, 12, 31)
    elif report_type == "半年度报告":
        start, end = date(report_year - 1, 1, 1), date(report_year + 1, 12, 31)
    elif report_type == "一季度报告":
        start, end = date(report_year - 1, 1, 1), date(report_year + 1, 12, 31)
    else:
        start, end = date(report_year - 1, 1, 1), date(report_year + 1, 12, 31)
    end = min(end, date.today())
    if end < start:
        end = start
    return f"{start:%Y%m%d}", f"{end:%Y%m%d}"


def _iter_records(value: object) -> Iterable[dict]:
    if isinstance(value, list):
        for item in value:
            yield from _iter_records(item)
    elif isinstance(value, dict):
        if any(key in value for key in ("FILE_LINK", "fileLink", "file_link")):
            yield value
        for child in value.values():
            if isinstance(child, (list, dict)):
                yield from _iter_records(child)


def _year_matches(title: str, report_year: int) -> bool:
    years = {int(item) for item in re.findall(r"20\d{2}", title)}
    # HK issuers commonly label a non-calendar financial year as "2024/25".
    # Treat the abbreviated trailing year as 2025 instead of rejecting it as 2024.
    for first, trailing in re.findall(r"(20\d{2})\s*[/／-]\s*(\d{2})(?!\d)", title):
        century = int(first) // 100 * 100
        expanded = century + int(trailing)
        if expanded < int(first):
            expanded += 100
        years.add(expanded)
    return not years or report_year in years


def _is_wanted_report(
    title: str,
    report_year: int,
    report_type: str,
    category_text: str = "",
) -> bool:
    """Accept only formal HKEX report categories, never preliminary results announcements."""
    compact = re.sub(r"\s+", "", title).lower()
    category = re.sub(r"\s+", "", _plain(category_text)).lower()
    blocked = (
        "摘要", "summary", "業績公告", "业绩公告", "resultsannouncement",
        "通函", "circular", "委任表格", "proxyform",
    )
    if not compact or any(word in compact for word in blocked) or not _year_matches(title, report_year):
        return False
    wanted = {
        "年度报告": ("年報", "年度報告", "年度报告", "annualreport"),
        "半年度报告": ("中期報告", "中期报告", "半年度報告", "半年度报告", "interimreport"),
        "一季度报告": ("第一季度報告", "第一季度报告", "firstquarterlyreport", "1stquarterlyreport"),
        "三季度报告": ("第三季度報告", "第三季度报告", "thirdquarterlyreport", "3rdquarterlyreport"),
    }
    category_markers = {
        # HKEX sometimes combines the formal report and ESG classification, e.g.
        # "[年報 / 環境、社會及管治資料/報告]".  The report marker itself is
        # authoritative; ESG wording in the category must not reject that record.
        "年度报告": ("年報", "年报", "annualreport"),
        "半年度报告": ("中期/半年度報告", "中期/半年度报告", "interim/half-yearreport"),
        "一季度报告": ("季度報告", "季度报告", "quarterlyreport"),
        "三季度报告": ("季度報告", "季度报告", "quarterlyreport"),
    }
    # A combined annual + ESG report is still a complete annual report when
    # HKEX classifies it as such. A standalone ESG document never qualifies.
    if any(word in compact for word in ("esg", "環境、社會", "环境、社会")):
        if not (report_type == "年度报告" and category and
                any(marker in category for marker in category_markers["年度报告"]) and
                any(word in compact for word in wanted["年度报告"])):
            return False
    if category:
        # HSBC labels its formal interim report "中期業績報告". Accept
        # that wording only when HKEX explicitly classifies it as a report.
        if report_type == "半年度报告" and any(word in compact for word in ("中期業績報告", "中期业绩报告")):
            return any(marker in category for marker in category_markers[report_type])
        return any(marker in category for marker in category_markers.get(report_type, ())) and any(
            word in compact for word in wanted.get(report_type, ())
        )
    return any(word in compact for word in wanted.get(report_type, ()))


class HkexClient:
    """Cached HKEXnews client for primary equities and formally classified reports."""

    def __init__(self, cache_dir: Path, timeout: float = 30.0, min_interval: float = 0.5):
        self.cache_dir = Path(cache_dir) / "hkex"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_request = 0.0
        self.session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; FilingAnalysisAssistant/7.5)",
                "Referer": f"{HKEX_ROOT}/search/titlesearch.xhtml?lang=en",
                "Accept": "application/json,text/plain,*/*",
            }
        )

    def _get(self, url: str, **kwargs) -> requests.Response:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        self._last_request = time.monotonic()
        response.raise_for_status()
        return response

    def company_catalog(self, max_age_days: int = 7) -> list[dict]:
        cache_path = self.cache_dir / "active_companies.json"
        if cache_path.exists() and time.time() - cache_path.stat().st_mtime < max_age_days * 86400:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            payload = self._get(HKEX_COMPANY_LIST).json()
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        for key in ("stockInfo", "data", "result"):
            items = payload.get(key) if isinstance(payload, dict) else None
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
        return []

    def _prefix_security(self, lookup: str, code: str = "") -> dict | None:
        try:
            response = self._get(
                HKEX_PREFIX,
                params={"callback": "callback", "lang": "ZH", "type": "A", "name": lookup, "market": "SEHK"},
            ).text.strip()
            match = re.search(r"^[^(]*\((.*)\)\s*;?$", response, flags=re.S)
            payload = json.loads(match.group(1) if match else response)
            items = payload.get("stockInfo") or []
            if code:
                items = [
                    item for item in items
                    if str(item.get("code") or item.get("c") or "").zfill(5) == code
                ]
            if not items:
                return None
            # Prefix search can return duplicate language/share-class rows for the
            # same exact ticker.  The ticker supplied by the user is already an
            # unambiguous security identifier, so keep the first exact-code row.
            return dict(items[0])
        except Exception:
            return None

    def resolve_security(self, stock_code: str = "", company_name: str = "") -> dict:
        code = ""
        if stock_code:
            code = normalise_hk_code(stock_code).split(".")[0]
            direct = self._prefix_security(code, code)
            if direct is not None:
                item = direct
                item["canonical_code"] = f"{str(item.get('code') or item.get('c') or '').zfill(5)}.HK"
                item["canonical_name"] = str(item.get("name") or item.get("n") or "")
                item["stock_id"] = str(item.get("stockId") or item.get("i") or item.get("id") or "")
                return item
        compact_name = _company_name_key(company_name)
        exact_matches: list[dict] = []
        fuzzy_matches: list[dict] = []
        for item in self.company_catalog():
            item_code = str(item.get("c") or item.get("code") or item.get("stockCode") or "").zfill(5)
            item_name = str(item.get("n") or item.get("name") or item.get("stockName") or "")
            compact_item_name = _company_name_key(item_name)
            if code and item_code == code:
                exact_matches.append(item)
            elif not code and compact_name:
                if compact_name == compact_item_name:
                    exact_matches.append(item)
                elif compact_name in compact_item_name:
                    fuzzy_matches.append(item)
        matches = exact_matches if exact_matches else fuzzy_matches
        if not code and len(matches) > 1:
            # HKD primary counters are below 80000; 8xxxx records are RMB dual counters.
            primary = [
                item for item in matches
                if str(item.get("c") or item.get("code") or "").isdigit()
                and int(str(item.get("c") or item.get("code") or "")) < 80000
            ]
            if len(primary) == 1:
                matches = primary
        if len(matches) != 1:
            lookup = code or str(company_name or "").strip()
            if lookup:
                direct = self._prefix_security(lookup, code)
                if direct is not None:
                    matches = [direct]
        if len(matches) != 1:
            raise ValueError(f"披露易证券列表无法唯一识别 {stock_code} {company_name}。港股代码请写成 00700.HK。")
        item = dict(matches[0])
        item["canonical_code"] = f"{str(item.get('c') or item.get('code') or '').zfill(5)}.HK"
        item["canonical_name"] = str(item.get("n") or item.get("name") or "")
        item["stock_id"] = str(item.get("i") or item.get("stockId") or item.get("id") or "")
        return item

    def raw_financial_documents(self, stock_id: str, report_year: int, report_type: str) -> list[dict]:
        """Return the raw HKEX financial-document records used by the public title-search page."""
        start, end = _search_window(report_year, report_type)
        params = {
            "sortDir": "0",
            "sortByOptions": "DateTime",
            "category": "0",
            "market": "SEHK",
            "stockId": stock_id,
            "documentType": "-1",
            "fromDate": start,
            "toDate": end,
            "title": "",
            "searchType": "1",
            "t1code": "40000",
            "t2Gcode": "-2",
            "t2code": "-2",
            "rowRange": "2000",
            "lang": "zh",
        }
        outer = self._get(HKEX_TITLE_SEARCH, params=params).json()
        inner: object = outer
        if isinstance(outer, dict) and isinstance(outer.get("result"), str):
            inner = json.loads(outer["result"])
        return list(_iter_records(inner))

    def search_reports(
        self, stock_code: str, company_name: str, report_year: int, report_type: str
    ) -> list[CninfoAnnouncement]:
        security = self.resolve_security(stock_code, company_name)
        code = security["canonical_code"]
        name = security["canonical_name"] or company_name
        stock_id = security["stock_id"]
        if not stock_id:
            raise ValueError(f"披露易证券列表缺少 {code} 的 stockId。")
        results: list[CninfoAnnouncement] = []
        for raw in self.raw_financial_documents(stock_id, report_year, report_type):
            title = _plain(raw.get("TITLE") or raw.get("title"))
            category_text = _plain(
                raw.get("LONG_TEXT") or raw.get("SHORT_TEXT") or raw.get("longText") or raw.get("shortText")
            )
            link = str(raw.get("FILE_LINK") or raw.get("fileLink") or raw.get("file_link") or "")
            if not link.lower().split("?")[0].endswith(".pdf"):
                continue
            if not _is_wanted_report(title, report_year, report_type, category_text):
                continue
            date_text = str(raw.get("DATE_TIME") or raw.get("dateTime") or raw.get("date") or "")
            date_match = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", date_text)
            if date_match:
                announcement_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
            else:
                date_match = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2})", date_text)
                announcement_date = (
                    f"{int(date_match.group(3)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(1)):02d}"
                    if date_match else ""
                )
            identifier = str(raw.get("NEWS_ID") or raw.get("newsId") or "") or re.sub(r"\D", "", link)[-18:] or str(abs(hash(link)))
            results.append(
                CninfoAnnouncement(
                    sec_code=code,
                    sec_name=name,
                    org_id=stock_id,
                    announcement_id=identifier,
                    title=title,
                    announcement_date=announcement_date,
                    adjunct_url=link,
                    download_url=urljoin(HKEX_ROOT, link),
                    report_year=report_year,
                    report_type=report_type,
                )
            )
        unique = {item.download_url: item for item in results}
        return sorted(unique.values(), key=lambda item: (item.announcement_date, item.announcement_id), reverse=True)

    @staticmethod
    def _validate_formal_pdf(pdf_path: Path, report_type: str) -> None:
        import pymupdf

        if not pdf_path.exists() or pdf_path.stat().st_size < 50_000:
            raise ValueError("披露易文件过小，不像正式定期报告。")
        with pdf_path.open("rb") as handle:
            if handle.read(4) != b"%PDF":
                raise ValueError("披露易返回的文件不是有效 PDF。")
        with pymupdf.open(pdf_path) as document:
            if document.page_count < 8:
                raise ValueError(f"披露易 PDF 只有 {document.page_count} 页，不像正式定期报告。")

    def download_announcement(
        self,
        announcement: CninfoAnnouncement,
    ) -> tuple[Path, bool]:
        """Download the exact preflight-approved HKEX report; never search again here."""
        target_dir = self.cache_dir / "reports" / str(announcement.report_year) / announcement.report_type
        target_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = target_dir / _safe_filename(
            f"{announcement.sec_code}_{announcement.sec_name}_{announcement.report_year}年"
            f"{announcement.report_type}_{announcement.announcement_id}.pdf"
        )
        metadata_path = pdf_path.with_suffix(".cninfo.json")
        if pdf_path.exists():
            try:
                self._validate_formal_pdf(pdf_path, announcement.report_type)
                if not metadata_path.exists():
                    metadata_path.write_text(json.dumps(asdict(announcement), ensure_ascii=False, indent=2), encoding="utf-8")
                return pdf_path, True
            except (OSError, ValueError):
                pdf_path.unlink(missing_ok=True)
        content = self._get(announcement.download_url).content
        temporary = pdf_path.with_suffix(".part")
        temporary.write_bytes(content)
        try:
            self._validate_formal_pdf(temporary, announcement.report_type)
            temporary.replace(pdf_path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        metadata_path.write_text(json.dumps(asdict(announcement), ensure_ascii=False, indent=2), encoding="utf-8")
        return pdf_path, False

    def download_report(
        self, stock_code: str, company_name: str, report_year: int, report_type: str
    ) -> tuple[Path, CninfoAnnouncement, bool]:
        candidates = self.search_reports(stock_code, company_name, report_year, report_type)
        if not candidates:
            raise FileNotFoundError(
                f"披露易未找到 {normalise_hk_code(stock_code)} {report_year}年{report_type}全文；"
                "请核对报告所属年份，或改用 ZIP/本机文件夹提供原始 PDF。"
            )
        selected = candidates[0]
        pdf_path, cached = self.download_announcement(selected)
        return pdf_path, selected, cached

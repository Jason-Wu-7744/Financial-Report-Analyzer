from __future__ import annotations

import html
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import requests


CNINFO_ROOT = "https://www.cninfo.com.cn"
CNINFO_STATIC = "https://static.cninfo.com.cn"
STOCK_LIST_URL = f"{CNINFO_ROOT}/new/data/szse_stock.json"
QUERY_URL = f"{CNINFO_ROOT}/new/hisAnnouncement/query"
REPORT_CATEGORIES = {
    "年度报告": "category_ndbg_szsh;",
    "半年度报告": "category_bndbg_szsh;",
    "一季度报告": "category_yjdbg_szsh;",
    "三季度报告": "category_sjdbg_szsh;",
}
ALL_REPORT_CATEGORIES = "".join(REPORT_CATEGORIES.values())
REPORT_TYPE_ALIASES = {
    "年度报告": ("年度报告",),
    "半年度报告": ("半年度报告",),
    "一季度报告": ("一季度报告", "第一季度报告"),
    "三季度报告": ("三季度报告", "第三季度报告"),
}


@dataclass
class CninfoAnnouncement:
    sec_code: str
    sec_name: str
    org_id: str
    announcement_id: str
    title: str
    announcement_date: str
    adjunct_url: str
    download_url: str
    report_year: int = 0
    report_type: str = ""


@dataclass
class CninfoDownloadRecord:
    stock_code: str
    company_name: str
    status: str
    message: str
    pdf_path: str = ""
    announcement_title: str = ""
    announcement_date: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class ResolvedCompany:
    stock_code: str
    company_name: str


def _plain_title(value: object) -> str:
    text = re.sub(r"<[^>]+>", "", html.unescape(str(value or "")))
    return re.sub(r"\s+", "", text).strip()


def _safe_filename(value: str) -> str:
    return re.sub(r"[\\/:*?\"<>|\s]+", "_", value).strip("_.")


def _market_params(code: str) -> tuple[str, str]:
    if code.startswith(("4", "8", "9")):
        return "bj", "bj"
    if code.startswith(("5", "6")):
        return "sse", "sh"
    return "szse", "sz"


def _search_window(report_year: int, report_type: str) -> str:
    if report_type == "年度报告":
        start = date(report_year + 1, 1, 1)
        end = date(report_year + 2, 12, 31)
    elif report_type == "半年度报告":
        start = date(report_year, 7, 1)
        end = date(report_year + 1, 6, 30)
    elif report_type == "一季度报告":
        start = date(report_year, 4, 1)
        end = date(report_year, 12, 31)
    else:
        start = date(report_year, 10, 1)
        end = date(report_year + 1, 6, 30)
    end = min(end, date.today())
    if end < start:
        end = start
    return f"{start:%Y-%m-%d}~{end:%Y-%m-%d}"


def _announcement_date(milliseconds: object) -> str:
    try:
        return datetime.fromtimestamp(int(milliseconds) / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


TITLE_BLOCKED = (
    "摘要", "英文版", "英文", "取消", "业绩说明会", "业绩预告", "业绩快报",
    "问询函", "回复函", "审计报告", "关于", "提示性公告",
)
A_SHARE_CODE_RE = re.compile(
    r"^(?:00[0123]\d{3}|30[012]\d{3}|60[0135]\d{3}|68[89]\d{3}|43\d{4}|8[3-8]\d{4}|92\d{4})$"
)
MARKET_COLUMNS = (("szse", ""),)
PERIODIC_TITLE_PATTERNS = (
    ("半年度报告", re.compile(r"(20\d{2})年半年度报告")),
    ("一季度报告", re.compile(r"(20\d{2})年(?:第一|一)季度报告")),
    ("三季度报告", re.compile(r"(20\d{2})年(?:第三|三)季度报告")),
    ("年度报告", re.compile(r"(20\d{2})(?:年)?年度报告")),
)


def classify_periodic_report(title: str) -> tuple[str, int] | None:
    compact = _plain_title(title)
    if not compact or any(word in compact for word in TITLE_BLOCKED):
        return None
    for report_type, pattern in PERIODIC_TITLE_PATTERNS:
        match = pattern.search(compact)
        if match:
            return report_type, int(match.group(1))
    return None


def _is_full_report(title: str, report_year: int, report_type: str) -> bool:
    classified = classify_periodic_report(title)
    return classified == (report_type, report_year)


def _is_a_share_code(code: str) -> bool:
    return bool(A_SHARE_CODE_RE.fullmatch(str(code or "").strip()))


def _announcement_rank(item: CninfoAnnouncement) -> tuple[int, str, str]:
    revision_words = ("修订", "更正后", "更新后")
    revision_score = 1 if any(word in item.title for word in revision_words) else 0
    return revision_score, item.announcement_date, item.announcement_id


class CninfoClient:
    def __init__(self, cache_dir: Path, timeout: float = 30.0, min_interval: float = 0.35):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_request = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; FilingAnalysisAssistant/1.2)",
                "Referer": f"{CNINFO_ROOT}/",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json,text/plain,*/*",
            }
        )

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _get(self, url: str, **kwargs) -> requests.Response:
        self._throttle()
        response = self.session.get(url, timeout=self.timeout, **kwargs)
        self._last_request = time.monotonic()
        response.raise_for_status()
        return response

    def _post(self, url: str, **kwargs) -> requests.Response:
        self._throttle()
        response = self.session.post(url, timeout=self.timeout, **kwargs)
        self._last_request = time.monotonic()
        response.raise_for_status()
        return response

    def stock_catalog(self, max_age_days: int = 7) -> list[dict]:
        cache_path = self.cache_dir / "szse_stock.json"
        if cache_path.exists() and time.time() - cache_path.stat().st_mtime < max_age_days * 86400:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            payload = self._get(STOCK_LIST_URL).json()
            cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        stock_list = payload.get("stockList") or []
        if not isinstance(stock_list, list):
            raise ValueError("巨潮证券代码表格式异常。")
        return stock_list

    def resolve_security(self, stock_code: str, company_name: str = "") -> dict:
        code_match = re.search(r"(?<!\d)(\d{6})(?!\d)", str(stock_code or ""))
        canonical_code = code_match.group(1) if code_match else str(stock_code or "").strip()
        catalog = self.stock_catalog()
        matches = [item for item in catalog if str(item.get("code") or "") == canonical_code]
        if not matches and company_name:
            compact_name = re.sub(r"[\s*]", "", company_name)
            exact_matches = [
                item for item in catalog
                if compact_name == re.sub(r"[\s*]", "", str(item.get("zwjc") or ""))
            ]
            if len(exact_matches) == 1:
                return exact_matches[0]
            matches = [
                item for item in catalog
                if compact_name and compact_name in re.sub(r"[\s*]", "", str(item.get("zwjc") or ""))
            ]
        if len(matches) != 1:
            raise ValueError(f"巨潮证券代码表无法唯一识别 {stock_code} {company_name}。")
        return matches[0]

    def search_reports(
        self,
        stock_code: str,
        company_name: str,
        report_year: int,
        report_type: str,
    ) -> list[CninfoAnnouncement]:
        if report_type not in REPORT_CATEGORIES:
            raise ValueError(f"不支持的报告类型：{report_type}")
        security = self.resolve_security(stock_code, company_name)
        stock_code = str(security.get("code") or stock_code)
        company_name = str(security.get("zwjc") or company_name)
        org_id = str(security.get("orgId") or "")
        if not org_id:
            raise ValueError(f"巨潮证券代码表缺少 {stock_code} 的公司标识。")
        column, plate = _market_params(stock_code)
        payload = {
            "pageNum": 1,
            "pageSize": 50,
            "tabName": "fulltext",
            "column": column,
            "stock": f"{stock_code},{org_id}",
            "searchkey": "",
            "secid": "",
            "plate": plate,
            "category": REPORT_CATEGORIES[report_type],
            "trade": "",
            "seDate": _search_window(report_year, report_type),
            "sortName": "",
            "sortType": "",
            "isHLtitle": "true",
        }
        response = self._post(QUERY_URL, data=payload).json()
        raw_items = response.get("announcements") or []
        results: list[CninfoAnnouncement] = []
        for raw in raw_items:
            title = _plain_title(raw.get("announcementTitle"))
            if not _is_full_report(title, report_year, report_type):
                continue
            item = self._parse_announcement(
                raw,
                fallback_code=stock_code,
                fallback_name=company_name,
                fallback_org=org_id,
                report_year=report_year,
                report_type=report_type,
            )
            if item is not None:
                results.append(item)
        return sorted(results, key=_announcement_rank, reverse=True)

    def _parse_announcement(
        self,
        raw: dict,
        fallback_code: str = "",
        fallback_name: str = "",
        fallback_org: str = "",
        report_year: int = 0,
        report_type: str = "",
    ) -> CninfoAnnouncement | None:
        title = _plain_title(raw.get("announcementTitle"))
        adjunct_url = str(raw.get("adjunctUrl") or "").lstrip("/")
        if not adjunct_url or str(raw.get("adjunctType") or "").upper() != "PDF":
            return None
        download_url = adjunct_url if adjunct_url.startswith("http") else f"{CNINFO_STATIC}/{adjunct_url}"
        return CninfoAnnouncement(
            sec_code=str(raw.get("secCode") or fallback_code),
            sec_name=_plain_title(raw.get("secName") or fallback_name),
            org_id=str(raw.get("orgId") or fallback_org),
            announcement_id=str(raw.get("announcementId") or ""),
            title=title,
            announcement_date=_announcement_date(raw.get("announcementTime")),
            adjunct_url=adjunct_url,
            download_url=download_url,
            report_year=report_year,
            report_type=report_type,
        )

    def search_reports_by_disclosure_date(
        self,
        disclosure_date: date,
        report_types: Iterable[str] | None = None,
    ) -> list[CninfoAnnouncement]:
        wanted = {item for item in (report_types or REPORT_CATEGORIES) if item in REPORT_CATEGORIES}
        if not wanted:
            wanted = set(REPORT_CATEGORIES)
        se_date = f"{disclosure_date:%Y-%m-%d}~{disclosure_date:%Y-%m-%d}"
        best: dict[tuple[str, str, int], CninfoAnnouncement] = {}
        for column, plate in MARKET_COLUMNS:
            page_num = 1
            while page_num <= 200:
                payload = {
                    "pageNum": page_num,
                    "pageSize": 30,
                    "tabName": "fulltext",
                    "column": column,
                    "stock": "",
                    "searchkey": "",
                    "secid": "",
                    "plate": plate,
                    "category": ALL_REPORT_CATEGORIES,
                    "trade": "",
                    "seDate": se_date,
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                }
                response = self._post(QUERY_URL, data=payload).json()
                if not isinstance(response, dict) or "announcements" not in response:
                    raise ValueError("CNINFO returned an invalid filing response. Please retry.")
                raw_items = response.get("announcements") or []
                if not isinstance(raw_items, list):
                    raise ValueError("CNINFO returned an invalid filing list. Please retry.")
                for raw in raw_items:
                    classified = classify_periodic_report(raw.get("announcementTitle"))
                    if classified is None:
                        continue
                    report_type, report_year = classified
                    if report_type not in wanted:
                        continue
                    item = self._parse_announcement(
                        raw, report_year=report_year, report_type=report_type
                    )
                    if item is None or not _is_a_share_code(item.sec_code):
                        continue
                    key = (item.sec_code, item.report_type, item.report_year)
                    current = best.get(key)
                    if current is None or _announcement_rank(item) > _announcement_rank(current):
                        best[key] = item
                total_pages = int(response.get("totalpages") or 0)
                if not raw_items or (total_pages and page_num >= total_pages) or len(raw_items) < 30:
                    break
                page_num += 1
        return sorted(best.values(), key=lambda item: (item.sec_code, item.report_type, item.announcement_id))

    def search_semiannual_by_disclosure_date(self, disclosure_date: date) -> list[CninfoAnnouncement]:
        return self.search_reports_by_disclosure_date(disclosure_date, ["半年度报告"])

    def download_announcement(
        self,
        announcement: CninfoAnnouncement,
        report_year: int | None = None,
        report_type: str | None = None,
    ) -> tuple[Path, bool]:
        report_year = report_year or announcement.report_year
        report_type = report_type or announcement.report_type or "半年度报告"
        if not report_year:
            raise ValueError(f"{announcement.sec_code} 缺少报告期年份。")
        target_dir = self.cache_dir / "reports" / str(report_year) / report_type
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_filename(
            f"{announcement.sec_code}_{announcement.sec_name}_"
            f"{report_year}年{report_type}_{announcement.announcement_id}.pdf"
        )
        pdf_path = target_dir / filename
        metadata_path = pdf_path.with_suffix(".cninfo.json")
        has_pdf_header = False
        if pdf_path.exists() and pdf_path.stat().st_size > 10_000:
            with pdf_path.open("rb") as handle:
                has_pdf_header = handle.read(4) == b"%PDF"
        if has_pdf_header:
            if not metadata_path.exists():
                metadata_path.write_text(json.dumps(asdict(announcement), ensure_ascii=False, indent=2), encoding="utf-8")
            return pdf_path, True
        response = self._get(announcement.download_url, stream=True)
        content = response.content
        if len(content) < 10_000 or not content.startswith(b"%PDF"):
            raise ValueError("巨潮下载结果不是有效 PDF，可能触发了限流，请稍后重试。")
        pdf_path.write_bytes(content)
        metadata_path.write_text(json.dumps(asdict(announcement), ensure_ascii=False, indent=2), encoding="utf-8")
        return pdf_path, False

    def download_report(
        self,
        stock_code: str,
        company_name: str,
        report_year: int,
        report_type: str,
    ) -> tuple[Path, CninfoAnnouncement, bool]:
        candidates = self.search_reports(stock_code, company_name, report_year, report_type)
        if not candidates:
            timing_hint = "该报告可能尚未披露；半年报通常在8月底前集中披露。" if report_type == "半年度报告" else "该报告可能尚未披露。"
            raise FileNotFoundError(
                f"巨潮未找到 {report_year}年{report_type}全文。{timing_hint}请核对这里填写的是报告所属年份，不是公告年份。"
            )
        selected = candidates[0]
        target_dir = self.cache_dir / "reports" / str(report_year) / report_type
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = _safe_filename(
            f"{selected.sec_code or stock_code}_{selected.sec_name or company_name}_"
            f"{report_year}年{report_type}_{selected.announcement_id}.pdf"
        )
        pdf_path = target_dir / filename
        metadata_path = pdf_path.with_suffix(".cninfo.json")
        has_pdf_header = False
        if pdf_path.exists() and pdf_path.stat().st_size > 10_000:
            with pdf_path.open("rb") as handle:
                has_pdf_header = handle.read(4) == b"%PDF"
        if has_pdf_header:
            if not metadata_path.exists():
                metadata_path.write_text(json.dumps(asdict(selected), ensure_ascii=False, indent=2), encoding="utf-8")
            return pdf_path, selected, True
        response = self._get(selected.download_url, stream=True)
        content = response.content
        if len(content) < 10_000 or not content.startswith(b"%PDF"):
            raise ValueError("巨潮下载结果不是有效 PDF，可能触发了限流，请稍后重试。")
        pdf_path.write_bytes(content)
        metadata_path.write_text(json.dumps(asdict(selected), ensure_ascii=False, indent=2), encoding="utf-8")
        return pdf_path, selected, False


def parse_company_identifiers(
    value: str,
    cache_dir: Path,
    market: str | None = None,
) -> list[ResolvedCompany]:
    """Resolve identifiers, optionally enforcing one selected listing market."""
    from hkex import HkexClient, is_hk_stock_code

    tokens = [token.strip() for token in re.split(r"[/／,，;；\n\r\t]+", value or "") if token.strip()]
    if not tokens:
        raise ValueError("没有识别到股票名称或证券代码。")
    client = CninfoClient(cache_dir)
    hk_client = HkexClient(cache_dir)
    companies: list[ResolvedCompany] = []
    seen_codes: set[str] = set()
    for token in tokens:
        if market in {"港股", "H股"}:
            if re.fullmatch(r"\d{6}(?:\.0)?", token):
                raise ValueError(f"港股模式不接受 A 股代码“{token}”；请先切换到 A 股。")
            code_value = token if is_hk_stock_code(token) else ""
            name_value = "" if code_value else token
            try:
                security = hk_client.resolve_security(code_value, name_value)
            except ValueError as error:
                raise ValueError(f"港股模式无法识别“{token}”；请输入港股名称或 00700.HK 格式代码。") from error
            code = security["canonical_code"]
            name = security["canonical_name"]
        elif market == "A股":
            if is_hk_stock_code(token):
                raise ValueError(f"A股模式不接受港股代码“{token}”；请先切换到港股。")
            code_match = re.fullmatch(r"(?:[A-Za-z]{2})?(\d{6})(?:\.[A-Za-z]{2})?", token)
            try:
                security = client.resolve_security(code_match.group(1) if code_match else "", "" if code_match else token)
            except ValueError as error:
                raise ValueError(f"A股模式无法识别“{token}”；请输入 A 股名称或六位证券代码。") from error
            code = str(security.get("code") or "")
            name = str(security.get("zwjc") or "")
        elif is_hk_stock_code(token):
            security = hk_client.resolve_security(token, "")
            code = security["canonical_code"]
            name = security["canonical_name"]
        else:
            code_match = re.fullmatch(r"(?:[A-Za-z]{2})?(\d{6})(?:\.[A-Za-z]{2})?", token)
            try:
                security = client.resolve_security(code_match.group(1) if code_match else "", "" if code_match else token)
                code = str(security.get("code") or "")
                name = str(security.get("zwjc") or "")
            except ValueError as cninfo_error:
                if code_match:
                    raise cninfo_error
                try:
                    security = hk_client.resolve_security("", token)
                    code = security["canonical_code"]
                    name = security["canonical_name"]
                except ValueError:
                    raise cninfo_error
        if code and code not in seen_codes:
            seen_codes.add(code)
            companies.append(ResolvedCompany(code, name))
    return companies


def list_reports_by_date(
    cache_dir: Path,
    disclosure_date: date | None = None,
    report_types: Iterable[str] | None = None,
) -> list[CninfoAnnouncement]:
    target = disclosure_date or (date.today() - timedelta(days=1))
    return CninfoClient(cache_dir).search_reports_by_disclosure_date(target, report_types)


def list_semiannual_reports_by_date(cache_dir: Path, disclosure_date: date | None = None) -> list[CninfoAnnouncement]:
    return list_reports_by_date(cache_dir, disclosure_date, ["半年度报告"])


def download_announcements(
    announcements: Iterable[CninfoAnnouncement],
    cache_dir: Path,
    progress: Callable[[int, int, CninfoDownloadRecord], None] | None = None,
) -> tuple[list[Path], list[CninfoDownloadRecord]]:
    from hkex import HkexClient, is_hk_stock_code

    items = list(announcements)
    client = CninfoClient(cache_dir)
    hk_client = HkexClient(cache_dir)
    pdfs: list[Path] = []
    records: list[CninfoDownloadRecord] = []
    for index, announcement in enumerate(items, 1):
        try:
            if is_hk_stock_code(announcement.sec_code):
                pdf_path, cached = hk_client.download_announcement(announcement)
            else:
                pdf_path, cached = client.download_announcement(announcement)
            pdfs.append(pdf_path)
            record = CninfoDownloadRecord(
                stock_code=announcement.sec_code,
                company_name=announcement.sec_name,
                status="已缓存" if cached else "已下载",
                message=announcement.title,
                pdf_path=str(pdf_path),
                announcement_title=announcement.title,
                announcement_date=announcement.announcement_date,
                source_url=announcement.download_url,
            )
        except Exception as error:
            record = CninfoDownloadRecord(
                stock_code=announcement.sec_code,
                company_name=announcement.sec_name,
                status="未找到/下载失败",
                message=f"{type(error).__name__}: {error}",
            )
        records.append(record)
        if progress:
            progress(index, len(items), record)
    return pdfs, records


def normalise_company_rows(rows: Iterable, cache_dir: Path, market: str | None = None) -> list:
    """Fill identifiers and optionally reject rows from the other listing market."""
    from hkex import HkexClient, is_hk_stock_code

    client = CninfoClient(cache_dir)
    hk_client = HkexClient(cache_dir)
    normalised = list(rows)
    for row in normalised:
        if market in {"港股", "H股"}:
            if row.stock_code and not is_hk_stock_code(row.stock_code):
                raise ValueError(f"港股模式不接受证券代码“{row.stock_code}”；请使用 00700.HK 格式。")
            try:
                security = hk_client.resolve_security(row.stock_code, row.company_name)
            except ValueError as error:
                label = row.stock_code or row.company_name
                raise ValueError(f"港股模式无法识别“{label}”。") from error
            row.stock_code = security["canonical_code"]
            row.company_name = row.company_name or security["canonical_name"]
        elif market == "A股":
            if is_hk_stock_code(row.stock_code):
                raise ValueError(f"A股模式不接受港股代码“{row.stock_code}”；请先切换到港股。")
            try:
                security = client.resolve_security(row.stock_code, row.company_name)
            except ValueError as error:
                label = row.stock_code or row.company_name
                raise ValueError(f"A股模式无法识别“{label}”。") from error
            row.stock_code = str(security.get("code") or "")
            row.company_name = row.company_name or str(security.get("zwjc") or "")
        elif is_hk_stock_code(row.stock_code):
            security = hk_client.resolve_security(row.stock_code, row.company_name)
            row.stock_code = security["canonical_code"]
            row.company_name = row.company_name or security["canonical_name"]
        elif not row.stock_code:
            try:
                security = client.resolve_security("", row.company_name)
                row.stock_code = str(security.get("code") or "")
            except ValueError as cninfo_error:
                try:
                    security = hk_client.resolve_security("", row.company_name)
                    row.stock_code = security["canonical_code"]
                    row.company_name = row.company_name or security["canonical_name"]
                except ValueError:
                    raise cninfo_error
        elif not row.company_name:
            security = client.resolve_security(row.stock_code, "")
            row.company_name = str(security.get("zwjc") or "")
    return normalised


def download_report_for_company(
    stock_code: str,
    company_name: str,
    report_year: int,
    report_type: str,
    cache_dir: Path,
) -> tuple[Path, CninfoAnnouncement, bool]:
    """Dispatch automatic report download to CNINFO (A shares) or HKEXnews (HK)."""
    from hkex import HkexClient, is_hk_stock_code

    if is_hk_stock_code(stock_code):
        return HkexClient(cache_dir).download_report(stock_code, company_name, report_year, report_type)
    return CninfoClient(cache_dir).download_report(stock_code, company_name, report_year, report_type)


def search_reports_for_company(
    stock_code: str,
    company_name: str,
    report_year: int,
    report_type: str,
    cache_dir: Path,
) -> list[CninfoAnnouncement]:
    from hkex import HkexClient, is_hk_stock_code

    if is_hk_stock_code(stock_code):
        return HkexClient(cache_dir).search_reports(stock_code, company_name, report_year, report_type)
    return CninfoClient(cache_dir).search_reports(stock_code, company_name, report_year, report_type)


def load_cninfo_metadata(pdf_path: Path) -> dict[str, str]:
    metadata_path = pdf_path.with_suffix(".cninfo.json")
    if not metadata_path.exists():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return {
            "source_url": str(payload.get("download_url") or ""),
            "announcement_title": str(payload.get("title") or ""),
            "announcement_date": str(payload.get("announcement_date") or ""),
        }
    except (OSError, ValueError, TypeError):
        return {}


def download_reports_for_rows(
    rows: Iterable,
    report_year: int,
    report_type: str,
    cache_dir: Path,
    progress: Callable[[int, int, CninfoDownloadRecord], None] | None = None,
) -> tuple[list[Path], list[CninfoDownloadRecord]]:
    row_list = list(rows)
    pdfs: list[Path] = []
    records: list[CninfoDownloadRecord] = []
    for index, row in enumerate(row_list, 1):
        try:
            pdf_path, announcement, cached = download_report_for_company(
                row.stock_code, row.company_name, report_year, report_type, cache_dir
            )
            pdfs.append(pdf_path)
            record = CninfoDownloadRecord(
                stock_code=row.stock_code,
                company_name=row.company_name,
                status="已缓存" if cached else "已下载",
                message=announcement.title,
                pdf_path=str(pdf_path),
                announcement_title=announcement.title,
                announcement_date=announcement.announcement_date,
                source_url=announcement.download_url,
            )
        except Exception as error:
            record = CninfoDownloadRecord(
                stock_code=row.stock_code,
                company_name=row.company_name,
                status="未找到/下载失败",
                message=f"{type(error).__name__}: {error}",
            )
        records.append(record)
        if progress:
            progress(index, len(row_list), record)
    return pdfs, records

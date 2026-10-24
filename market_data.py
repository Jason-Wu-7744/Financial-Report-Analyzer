from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path

import requests


EASTMONEY_F10_URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"


@dataclass
class MarketFinancialMetrics:
    revenue_billion: float | None = None
    parent_profit_billion: float | None = None
    adjusted_profit_billion: float | None = None
    revenue_yoy_pct: float | None = None
    parent_profit_yoy_pct: float | None = None
    adjusted_profit_yoy_pct: float | None = None
    npm_pct: float | None = None
    asset_turnover: float | None = None
    equity_multiplier: float | None = None
    report_date: str = ""
    source_name: str = "东方财富F10主要指标"
    source_url: str = ""
    raw: dict | None = None
    error: str = ""

    def has_any(self) -> bool:
        return any(
            value is not None
            for value in (
                self.revenue_billion,
                self.parent_profit_billion,
                self.adjusted_profit_billion,
                self.revenue_yoy_pct,
                self.parent_profit_yoy_pct,
                self.adjusted_profit_yoy_pct,
                self.npm_pct,
                self.asset_turnover,
                self.equity_multiplier,
            )
        )

    def has_dupont(self) -> bool:
        return any(
            value is not None
            for value in (self.npm_pct, self.asset_turnover, self.equity_multiplier)
        )


def _secu_code(stock_code: str) -> str:
    text = str(stock_code or "").strip().upper().replace(" ", "")
    if text.endswith(".HK") or text.startswith("HK") or re.fullmatch(r"\d{3,5}(?:\.0)?", text):
        if text.startswith("HK"):
            text = text[2:]
        if text.endswith(".HK"):
            text = text[:-3]
        text = text[:-2] if text.endswith(".0") else text
        if re.fullmatch(r"\d{1,5}", text):
            return f"{int(text):05d}.HK"
    code = re.search(r"(?<!\d)(\d{6})(?!\d)", str(stock_code or ""))
    if not code:
        raise ValueError(f"无法识别证券代码：{stock_code}")
    digits = code.group(1)
    if digits.startswith(("5", "6")):
        return f"{digits}.SH"
    if digits.startswith(("4", "8", "9")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _report_date(report_year: int, report_type: str) -> str:
    if report_type == "年度报告":
        return f"{report_year}-12-31"
    if report_type == "半年度报告":
        return f"{report_year}-06-30"
    if report_type == "一季度报告":
        return f"{report_year}-03-31"
    if report_type == "三季度报告":
        return f"{report_year}-09-30"
    raise ValueError(f"不支持的报告类型：{report_type}")


def _to_billion(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value) / 100_000_000.0, 4)
    except (TypeError, ValueError):
        return None


def _to_pct(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _to_times(value: object, digits: int = 6) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
        if number != number:  # NaN
            return None
        return round(number, digits)
    except (TypeError, ValueError):
        return None


def _equity_multiplier_from_debt_ratio(debt_ratio_pct: object) -> float | None:
    ratio = _to_pct(debt_ratio_pct)
    if ratio is None or ratio >= 100:
        return None
    return round(1.0 / (1.0 - ratio / 100.0), 6)


def _metrics_from_cache(payload: dict) -> MarketFinancialMetrics:
    allowed = {item.name for item in fields(MarketFinancialMetrics)}
    return MarketFinancialMetrics(**{key: value for key, value in payload.items() if key in allowed})


def _request_json(url: str, params: dict, headers: dict, timeout: float, retries: int = 3) -> dict:
    last_error = ""
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            last_error = "返回不是 JSON 对象"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(0.35 * (attempt + 1))
    raise RuntimeError(last_error)


def _match_report_row(rows: list[dict], target_date: str, date_keys: tuple[str, ...]) -> dict | None:
    for row in rows:
        for key in date_keys:
            report_date = str(row.get(key) or "")
            if report_date.startswith(target_date):
                return row
    return None


def fetch_eastmoney_metrics(
    stock_code: str,
    report_year: int,
    report_type: str,
    cache_dir: Path | None = None,
    timeout: float = 20.0,
) -> MarketFinancialMetrics:
    """Fetch headline metrics from East Money F10, with income-statement fallback."""
    target_date = _report_date(report_year, report_type)
    try:
        secu = _secu_code(stock_code)
    except ValueError as exc:
        return MarketFinancialMetrics(error=str(exc))

    cache_path = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{secu}_{target_date}.json"
        if cache_path.exists():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = _metrics_from_cache(payload)
            if cached.has_any():
                return cached

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; FilingAnalysisAssistant/7.0)",
        "Referer": "https://emweb.securities.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    if secu.endswith(".HK"):
        hk_params = {
            "reportName": "RPT_HKF10_FN_MAININDICATOR",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{secu.split(".")[0]}")',
            "pageNumber": 1,
            "pageSize": 50,
            "sortTypes": -1,
            "sortColumns": "REPORT_DATE",
            "source": "F10",
            "client": "PC",
        }
        try:
            payload = _request_json(EASTMONEY_F10_URL, hk_params, headers, timeout)
        except Exception as exc:
            return MarketFinancialMetrics(error=f"东方财富港股接口请求失败：{exc}")
        rows = ((payload.get("result") or {}).get("data") or []) if isinstance(payload, dict) else []
        matched = _match_report_row(rows, target_date, ("REPORT_DATE", "REPORTDATE"))
        if matched is None:
            return MarketFinancialMetrics(
                error=f"东方财富未找到 {secu} {report_type}（报告期 {target_date}）的港股财务指标。"
            )
        revenue_yuan = matched.get("OPERATE_INCOME") or matched.get("TOTAL_OPERATE_INCOME")
        parent_yuan = matched.get("HOLDER_PROFIT") or matched.get("PARENT_NETPROFIT")
        assets_yuan = matched.get("TOTAL_ASSETS")
        equity_yuan = matched.get("TOTAL_PARENT_EQUITY") or matched.get("TOTAL_EQUITY")
        npm_pct = _to_pct(matched.get("NET_PROFIT_RATIO"))
        if npm_pct is None and revenue_yuan not in (None, "", 0) and parent_yuan not in (None, ""):
            try:
                npm_pct = round(float(parent_yuan) / float(revenue_yuan) * 100.0, 4)
            except (TypeError, ValueError, ZeroDivisionError):
                npm_pct = None
        asset_turnover = None
        equity_multiplier = None
        try:
            if revenue_yuan not in (None, "", 0) and assets_yuan not in (None, "", 0):
                asset_turnover = round(float(revenue_yuan) / float(assets_yuan), 6)
            if assets_yuan not in (None, "", 0) and equity_yuan not in (None, "", 0):
                equity_multiplier = round(float(assets_yuan) / float(equity_yuan), 6)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        metrics = MarketFinancialMetrics(
            revenue_billion=_to_billion(revenue_yuan),
            parent_profit_billion=_to_billion(parent_yuan),
            revenue_yoy_pct=_to_pct(matched.get("OPERATE_INCOME_YOY") or matched.get("TOTAL_OPERATE_INCOME_YOY")),
            parent_profit_yoy_pct=_to_pct(matched.get("HOLDER_PROFIT_YOY") or matched.get("PARENT_NETPROFIT_YOY")),
            npm_pct=npm_pct,
            asset_turnover=asset_turnover,
            equity_multiplier=equity_multiplier,
            report_date=target_date,
            source_name="东方财富港股F10主要指标",
            source_url=(
                f"{EASTMONEY_F10_URL}?reportName=RPT_HKF10_FN_MAININDICATOR"
                f"&filter=(SECURITY_CODE=\"{secu.split('.')[0]}\")"
            ),
            raw=matched,
        )
        if cache_path is not None and metrics.has_any():
            cache_path.write_text(json.dumps(asdict(metrics), ensure_ascii=False, indent=2), encoding="utf-8")
        return metrics

    f10_params = {
        "reportName": "RPT_F10_FINANCE_MAINFINADATA",
        "columns": "ALL",
        "filter": f'(SECUCODE="{secu}")',
        "pageNumber": 1,
        "pageSize": 16,
        "sortTypes": -1,
        "sortColumns": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    try:
        payload = _request_json(EASTMONEY_F10_URL, f10_params, headers, timeout)
    except Exception as exc:
        return MarketFinancialMetrics(error=f"东方财富接口请求失败：{exc}")

    rows = ((payload.get("result") or {}).get("data") or []) if isinstance(payload, dict) else []
    matched = _match_report_row(rows, target_date, ("REPORT_DATE", "REPORTDATE"))
    if matched is None:
        return MarketFinancialMetrics(
            error=f"东方财富未找到 {secu} {report_type}（报告期 {target_date}）的主要财务指标。"
        )

    revenue_yuan = matched.get("TOTALOPERATEREVE") or matched.get("OPERATE_INCOME_PK")
    parent_yuan = matched.get("PARENTNETPROFIT")
    npm_pct = _to_pct(matched.get("XSJLL"))
    if npm_pct is None and revenue_yuan not in (None, "", 0) and parent_yuan not in (None, ""):
        try:
            npm_pct = round(float(parent_yuan) / float(revenue_yuan) * 100.0, 4)
        except (TypeError, ValueError, ZeroDivisionError):
            npm_pct = None
    asset_turnover = _to_times(matched.get("TOAZZL"))
    if asset_turnover is None:
        assets_yuan = matched.get("TOTAL_ASSETS_PK")
        try:
            if revenue_yuan not in (None, "", 0) and assets_yuan not in (None, "", 0):
                asset_turnover = round(float(revenue_yuan) / float(assets_yuan), 6)
        except (TypeError, ValueError, ZeroDivisionError):
            asset_turnover = None
    equity_multiplier = _to_times(matched.get("QYCS"))
    if equity_multiplier is None:
        equity_multiplier = _equity_multiplier_from_debt_ratio(matched.get("ZCFZL"))
    metrics = MarketFinancialMetrics(
        revenue_billion=_to_billion(revenue_yuan),
        parent_profit_billion=_to_billion(parent_yuan),
        adjusted_profit_billion=_to_billion(matched.get("KCFJCXSYJLR")),
        revenue_yoy_pct=_to_pct(matched.get("TOTALOPERATEREVETZ") or matched.get("OI_YOYRATIO_PK")),
        parent_profit_yoy_pct=_to_pct(matched.get("PARENTNETPROFITTZ")),
        adjusted_profit_yoy_pct=_to_pct(matched.get("KCFJCXSYJLRTZ")),
        npm_pct=npm_pct,
        asset_turnover=asset_turnover,
        equity_multiplier=equity_multiplier,
        report_date=target_date,
        source_url=(
            f"{EASTMONEY_F10_URL}?reportName=RPT_F10_FINANCE_MAINFINADATA"
            f"&filter=(SECUCODE=\"{secu}\")"
        ),
        raw={
            "SECUCODE": matched.get("SECUCODE"),
            "REPORT_DATE": matched.get("REPORT_DATE"),
            "REPORT_DATE_NAME": matched.get("REPORT_DATE_NAME"),
            "TOTALOPERATEREVE": matched.get("TOTALOPERATEREVE"),
            "PARENTNETPROFIT": matched.get("PARENTNETPROFIT"),
            "KCFJCXSYJLR": matched.get("KCFJCXSYJLR"),
            "TOTALOPERATEREVETZ": matched.get("TOTALOPERATEREVETZ"),
            "PARENTNETPROFITTZ": matched.get("PARENTNETPROFITTZ"),
            "KCFJCXSYJLRTZ": matched.get("KCFJCXSYJLRTZ"),
            "XSJLL": matched.get("XSJLL"),
            "TOAZZL": matched.get("TOAZZL"),
            "QYCS": matched.get("QYCS"),
            "ZCFZL": matched.get("ZCFZL"),
            "ROEJQ": matched.get("ROEJQ"),
            "TOTAL_ASSETS_PK": matched.get("TOTAL_ASSETS_PK"),
            "TOTAL_EQUITY_PK": matched.get("TOTAL_EQUITY_PK"),
        },
    )
    if metrics.adjusted_profit_billion is None:
        income_params = {
            "reportName": "RPT_DMSK_FN_INCOME",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{secu.split(".")[0]}")(REPORT_DATE=\'{target_date}\')',
            "pageNumber": 1,
            "pageSize": 5,
            "sortTypes": -1,
            "sortColumns": "REPORT_DATE",
            "source": "WEB",
            "client": "WEB",
        }
        try:
            income_payload = _request_json(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                income_params,
                {**headers, "Referer": "https://data.eastmoney.com/"},
                timeout,
            )
            income_rows = ((income_payload.get("result") or {}).get("data") or [])
            income_row = _match_report_row(income_rows, target_date, ("REPORT_DATE", "REPORTDATE"))
            if income_row:
                metrics.adjusted_profit_billion = _to_billion(income_row.get("DEDUCT_PARENT_NETPROFIT"))
                if metrics.revenue_billion is None:
                    metrics.revenue_billion = _to_billion(income_row.get("TOTAL_OPERATE_INCOME"))
                if metrics.parent_profit_billion is None:
                    metrics.parent_profit_billion = _to_billion(income_row.get("PARENT_NETPROFIT"))
                metrics.raw = {**(metrics.raw or {}), "DEDUCT_PARENT_NETPROFIT": income_row.get("DEDUCT_PARENT_NETPROFIT")}
        except Exception:
            pass
    if cache_path is not None and metrics.has_any():
        cache_path.write_text(json.dumps(asdict(metrics), ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.05)
    return metrics

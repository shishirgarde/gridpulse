"""Browser-free Delhi energy-met ingestion from official NLDC PSP reports."""

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import requests
import xlrd

API_URL = "https://webapi.grid-india.in/api/v1/file"
CDN_URL = "https://webcdn.grid-india.in/"
LISTING_URL = "https://grid-india.in/en/reports/daily-psp-report"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Report:
    day: date
    url: str
    modified_at: str
    file_id: int


def _text(value: object) -> str:
    return " ".join(str(value).split()).casefold()


def parse_delhi_energy(content: bytes, expected_day: date) -> float:
    """Validate the report's date and extract only Delhi's Energy Met (MU)."""
    try:
        book = xlrd.open_workbook(file_contents=content, on_demand=True)
    except xlrd.XLRDError as exc:
        raise ValueError("Grid-India returned an invalid XLS report.") from exc
    try:
        if "MOP_E" not in book.sheet_names():
            raise ValueError("Grid-India report layout changed: MOP_E sheet is missing.")
        sheet = book.sheet_by_name("MOP_E")
        rows = [sheet.row_values(index) for index in range(sheet.nrows)]
        if not any(_text(value) == "report for previous day" for row in rows for value in row):
            raise ValueError("Grid-India report does not identify its observation-day convention.")
        reporting_dates = []
        for row_index, row in enumerate(rows):
            for col, value in enumerate(row):
                if _text(value).rstrip(":") != "date of reporting":
                    continue
                cells = [index for index in range(col + 1, sheet.ncols) if row[index] != ""]
                if len(cells) != 1:
                    raise ValueError("Grid-India reporting date is missing or ambiguous.")
                index = cells[0]
                if sheet.cell_type(row_index, index) == xlrd.XL_CELL_DATE:
                    reporting_dates.append(
                        xlrd.xldate_as_datetime(row[index], book.datemode).date()
                    )
                else:
                    reporting_dates.append(datetime.strptime(str(row[index]), "%d-%b-%Y").date())
        if reporting_dates != [expected_day + timedelta(days=1)]:
            raise ValueError("Grid-India reporting date does not match the listed observation day.")

        sections = [index for index, row in enumerate(rows)
                    if any(_text(value) == "c. power supply position in states" for value in row)]
        if len(sections) != 1:
            raise ValueError("Grid-India state power-supply table is missing or ambiguous.")
        start = sections[0] + 1
        end = next((index for index in range(start, len(rows))
                    if any(re.match(r"^[d-z]\.\s", _text(value)) for value in rows[index])),
                   len(rows))
        headers = [(index, col) for index in range(start, end)
                   for col, value in enumerate(rows[index]) if _text(value) == "states"]
        if len(headers) != 1:
            raise ValueError("Grid-India state-name column is missing or ambiguous.")
        header, state_col = headers[0]
        energy_cols = [col for col in range(sheet.ncols)
                       if _text(rows[header - 1][col]) == "energy met"
                       and _text(rows[header][col]) == "(mu)"]
        delhi_rows = [index for index in range(header + 1, end)
                      if _text(rows[index][state_col]) == "delhi"]
        if len(energy_cols) != 1 or len(delhi_rows) != 1:
            raise ValueError("Grid-India Delhi Energy Met (MU) cell is missing or ambiguous.")
        row, col = delhi_rows[0], energy_cols[0]
        if sheet.cell_type(row, col) != xlrd.XL_CELL_NUMBER:
            raise ValueError("Grid-India Delhi energy met is not numeric.")
        energy = float(rows[row][col])
        if not math.isfinite(energy) or energy <= 0:
            raise ValueError("Grid-India Delhi energy met must be finite and positive.")
        return energy
    finally:
        book.release_resources()


def _list_reports(session: requests.Session, today: date) -> dict[date, Report]:
    # A 60-day lookup spans the 56-day input window plus the accepted publication lag.
    years = {day.year if day.month >= 4 else day.year - 1
             for day in (today, today - timedelta(days=60))}
    reports: dict[date, Report] = {}
    for year in sorted(years):
        response = session.post(API_URL, json={
            "_source": "GRDW", "_type": "DAILY_PSP_REPORT",
            "_fileDate": f"{year}-{str(year + 1)[-2:]}", "_month": "00",
        }, timeout=60)
        response.raise_for_status()
        payload = response.json()
        if payload.get("flagType") != 0 or not isinstance(payload.get("retData"), list):
            raise ValueError("Grid-India report listing did not return a successful file list.")
        for item in payload["retData"]:
            path = item["FilePath"]
            if not isinstance(path, str):
                raise ValueError("Grid-India returned an invalid report path.")
            if not path.lower().endswith(".xls"):
                continue
            if not path.startswith("files/grdw/") or any(
                part in (".", "..") for part in unquote(path).split("/")
            ):
                raise ValueError("Grid-India returned an unexpected report path.")
            match = re.fullmatch(r"(\d{2}\.\d{2}\.\d{2})_NLDC_PSP[^/]*\.xls",
                                 unquote(path).rsplit("/", 1)[-1], re.IGNORECASE)
            if not match:
                raise ValueError("Grid-India XLS filename does not identify an observation day.")
            day = datetime.strptime(match[1], "%d.%m.%y").date()
            if day >= today:
                continue
            modified = datetime.strptime(item["ModifiedOn"], "%d-%m-%Y %H:%M").isoformat()
            report = Report(day, CDN_URL + path, modified, int(item["Id"]))
            prior = reports.get(day)
            if prior is None or (report.modified_at, report.file_id) > (
                prior.modified_at, prior.file_id
            ):
                reports[day] = report
    if not reports:
        raise ValueError("Grid-India has no completed-day XLS reports available.")
    return reports


def fetch_observations(data_root: Path, today: date | None = None) -> dict[date, float]:
    """Sync 56 demand days, retaining official raw reports and revised actuals."""
    today = today or datetime.now(ZoneInfo("Asia/Kolkata")).date()
    cache_path = data_root / "dashboard_actuals.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    # Migrate legacy CSV caches by rebuilding the active window from official reports.
    official = cache.get("source") == API_URL
    observations = {date.fromisoformat(day): float(value)
                    for day, value in cache.get("observations", {}).items()} if official else {}
    saved_reports = cache.get("reports", {}) if official else {}
    if any(not math.isfinite(value) or value <= 0 for value in observations.values()):
        raise ValueError("The saved Grid-India observations contain invalid energy values.")
    with requests.Session() as session:
        reports = _list_reports(session, today)
        origin = max(reports)
        days = [origin - timedelta(days=offset) for offset in range(55, -1, -1)]
        raw_folder = data_root / "grid_india_reports"
        raw_folder.mkdir(parents=True, exist_ok=True)
        for day in days:
            report = reports.get(day)
            if report is None:
                LOGGER.warning("No Grid-India XLS report is listed for %s; no value was filled.",
                               day)
                continue
            key = day.isoformat()
            saved = saved_reports.get(key, {})
            if (day in observations and saved.get("url") == report.url
                    and saved.get("modified_at") == report.modified_at
                    and saved.get("file_id") == report.file_id
                    and isinstance(saved.get("sha256"), str)
                    and re.fullmatch(r"[a-f0-9]{64}", saved["sha256"])
                    and (raw_folder / f"{key}_{saved['sha256']}.xls").is_file()):
                continue
            response = session.get(report.url, timeout=60)
            response.raise_for_status()
            energy = parse_delhi_energy(response.content, day)
            digest = hashlib.sha256(response.content).hexdigest()
            destination = raw_folder / f"{key}_{digest}.xls"
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(response.content)
            temporary.replace(destination)
            observations[day] = energy
            saved_reports[key] = {"url": report.url, "modified_at": report.modified_at,
                                  "file_id": report.file_id, "sha256": digest}
    updated = {"source": API_URL, "source_url": LISTING_URL,
               "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
               "observations": {day.isoformat(): value for day, value in observations.items()},
               "reports": saved_reports}
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(updated, allow_nan=False), encoding="utf-8")
    temporary.replace(cache_path)
    return observations

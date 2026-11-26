import json
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import xlrd

from gridpulse import grid_india

TODAY = date(2026, 11, 26)
ORIGIN = date(2026, 11, 24)


def report_item(day, *, file_id=1, modified="25-11-2026 10:24", suffix="597"):
    return {
        "Id": file_id,
        "ModifiedOn": modified,
        "FilePath": f"files/grdw/{day:%Y/%m}/{day:%d.%m.%y}_NLDC_PSP_{suffix}.xls",
    }


@pytest.fixture
def api(monkeypatch):
    session = Mock()
    items = [report_item(ORIGIN - timedelta(days=offset)) for offset in range(56)]
    response = Mock()
    response.json.return_value = {"flagType": 0, "retData": items}
    session.post.return_value = response
    session.get.side_effect = lambda url, **kwargs: Mock(content=url.encode())
    monkeypatch.setattr(grid_india.requests, "Session", lambda: nullcontext(session))
    parse = Mock(side_effect=lambda content, day: 70.0 + day.day / 100)
    monkeypatch.setattr(grid_india, "parse_delhi_energy", parse)
    return session, items, parse


def test_bootstrap_migrates_legacy_cache_and_reuses_official_reports(tmp_path, api):
    session, _, parse = api
    cache_path = tmp_path / "dashboard_actuals.json"
    cache_path.write_text(json.dumps({"observations": {"2026-11-24": 999.0}}))

    observations = grid_india.fetch_observations(tmp_path, TODAY)
    assert len(observations) == 56
    assert observations[ORIGIN] == 70.24
    assert session.get.call_count == 56
    assert len(list((tmp_path / "grid_india_reports").glob("*.xls"))) == 56
    cache = json.loads(cache_path.read_text())
    assert cache["source"] == grid_india.API_URL
    assert cache["reports"][ORIGIN.isoformat()]["url"].endswith("24.11.26_NLDC_PSP_597.xls")

    session.get.reset_mock()
    parse.reset_mock()
    assert grid_india.fetch_observations(tmp_path, TODAY) == observations
    session.get.assert_not_called()
    parse.assert_not_called()


def test_revised_report_updates_actual_and_preserves_old_raw_report(tmp_path, api):
    session, items, parse = api
    grid_india.fetch_observations(tmp_path, TODAY)
    items.append(report_item(ORIGIN, file_id=2, modified="26-11-2026 09:00",
                             suffix="H&E%20v3_913"))
    session.get.reset_mock()
    parse.side_effect = lambda content, day: 76.47

    observations = grid_india.fetch_observations(tmp_path, TODAY)
    assert observations[ORIGIN] == 76.47
    session.get.assert_called_once_with(grid_india.CDN_URL + items[-1]["FilePath"], timeout=60)
    assert len(list((tmp_path / "grid_india_reports").glob(f"{ORIGIN}_*.xls"))) == 2


@pytest.mark.parametrize("failure", ["network", "invalid_report"])
def test_failed_update_does_not_replace_valid_actuals_cache(tmp_path, api, failure):
    session, items, parse = api
    grid_india.fetch_observations(tmp_path, TODAY)
    before = (tmp_path / "dashboard_actuals.json").read_bytes()
    items[0]["ModifiedOn"] = "26-11-2026 09:00"
    if failure == "network":
        session.get.side_effect = requests.ConnectionError("download failed")
        error = requests.ConnectionError
    else:
        parse.side_effect = ValueError("report date changed")
        error = ValueError
    with pytest.raises(error):
        grid_india.fetch_observations(tmp_path, TODAY)
    assert (tmp_path / "dashboard_actuals.json").read_bytes() == before


def test_missing_reports_are_logged_and_never_filled(tmp_path, api, caplog):
    _, items, _ = api
    missing = ORIGIN - timedelta(days=10)
    items[:] = [item for item in items if f"{missing:%d.%m.%y}_" not in item["FilePath"]]
    observations = grid_india.fetch_observations(tmp_path, TODAY)
    assert missing not in observations
    assert len(observations) == 55
    assert f"No Grid-India XLS report is listed for {missing}" in caplog.text


def test_listing_handles_financial_year_boundary_and_excludes_unfinished_days():
    session = Mock()
    session.post.return_value.json.return_value = {
        "flagType": 0,
        "retData": [report_item(date(2026, 3, 31)), report_item(date(2026, 4, 1)),
                    report_item(date(2026, 4, 2))],
    }
    reports = grid_india._list_reports(session, date(2026, 4, 2))
    assert set(reports) == {date(2026, 3, 31), date(2026, 4, 1)}
    assert [call.kwargs["json"]["_fileDate"] for call in session.post.call_args_list] == [
        "2025-26", "2026-27",
    ]


def test_listing_rejects_api_errors_and_unexpected_paths(api):
    session, items, _ = api
    session.post.return_value.json.return_value = {"flagType": 1, "retData": []}
    with pytest.raises(ValueError, match="successful file list"):
        grid_india._list_reports(session, TODAY)
    session.post.return_value.json.return_value = {"flagType": 0, "retData": items}
    items[0]["FilePath"] = "../24.11.26_NLDC_PSP_597.xls"
    with pytest.raises(ValueError, match="unexpected report path"):
        grid_india._list_reports(session, TODAY)


@pytest.fixture
def workbook(monkeypatch):
    rows = [
        ["Report for previous day", "", "", "Date of Reporting:", "", "25-Nov-2026"],
        ["C. Power Supply Position in States", "", "", "", "", ""],
        ["", "", "Max.Demand", "Shortage", "Energy Met", "Energy"],
        ["Region", "States", "Met (MW)", "(MW)", "(MU)", "Shortage (MU)"],
        ["NR", "Delhi", 4111.0, 0.0, 76.47, 0.0],
        ["D. Other observations", "", "", "", "", ""],
    ]
    sheet = Mock(ncols=6)
    sheet.row_values.side_effect = lambda index: rows[index]
    sheet.cell_type.side_effect = lambda r, c: (
        xlrd.XL_CELL_NUMBER if isinstance(rows[r][c], (int, float)) else xlrd.XL_CELL_TEXT
    )
    book = Mock(datemode=0)
    book.sheet_names.return_value = ["MOP_E"]
    book.sheet_by_name.return_value = sheet
    monkeypatch.setattr(xlrd, "open_workbook", lambda **kwargs: book)
    return SimpleNamespace(rows=rows, sheet=sheet, book=book)


def test_parser_finds_labels_after_rows_and_columns_shift(workbook):
    workbook.rows.insert(0, ["", "", "", "", "", ""])
    for row in workbook.rows:
        row.insert(0, "")
    workbook.sheet.nrows = len(workbook.rows)
    workbook.sheet.ncols = 7
    assert grid_india.parse_delhi_energy(b"test", ORIGIN) == 76.47
    workbook.book.release_resources.assert_called_once()


def test_parser_accepts_excel_reporting_date(workbook):
    workbook.rows[0][5] = (datetime(2026, 11, 25) - datetime(1899, 12, 30)).days
    original_type = workbook.sheet.cell_type.side_effect
    workbook.sheet.cell_type.side_effect = lambda r, c: (
        xlrd.XL_CELL_DATE if (r, c) == (0, 5) else original_type(r, c)
    )
    workbook.sheet.nrows = len(workbook.rows)
    assert grid_india.parse_delhi_energy(b"test", ORIGIN) == 76.47


@pytest.mark.parametrize("breakage", ["wrong_date", "wrong_unit", "duplicate_delhi",
                                      "missing_delhi", "text_energy", "negative", "nan"])
def test_parser_rejects_ambiguous_or_invalid_observations(workbook, breakage):
    if breakage == "wrong_date":
        workbook.rows[0][5] = "24-Nov-2026"
    elif breakage == "wrong_unit":
        workbook.rows[3][4] = "(MW)"
    elif breakage == "duplicate_delhi":
        workbook.rows.insert(5, list(workbook.rows[4]))
    elif breakage == "missing_delhi":
        workbook.rows[4][1] = "Haryana"
    elif breakage == "text_energy":
        workbook.rows[4][4] = "-"
    elif breakage == "negative":
        workbook.rows[4][4] = -1.0
    elif breakage == "nan":
        workbook.rows[4][4] = float("nan")
    workbook.sheet.nrows = len(workbook.rows)
    with pytest.raises(ValueError):
        grid_india.parse_delhi_energy(b"test", ORIGIN)
    workbook.book.release_resources.assert_called_once()


def test_parser_rejects_html_instead_of_xls():
    with pytest.raises(ValueError, match="invalid XLS"):
        grid_india.parse_delhi_energy(b"<html>Temporarily unavailable</html>", ORIGIN)

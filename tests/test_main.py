import csv
import io
import os
import sys
from datetime import date, datetime, timedelta

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
SAMPLE_PDF = os.path.join(REPO_ROOT, "pdf_files", "2026", "10", "2026-10-03.pdf")
PDF_BYTES = b"%PDF-1.4\n%fake pdf body\n%%EOF"


@pytest.fixture(autouse=True)
def no_log_file():
    """Keep tests from appending to the real log.txt."""
    main.logger.removeHandler(main.file_handler)
    yield
    main.logger.addHandler(main.file_handler)


def make_response(url, status=200, body=b"", headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = body
    response.url = url
    response.headers.update(headers or {})
    return response


class FakeSession:
    """Returns canned responses per URL and records requested URLs."""

    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        result = self.responses[url]
        if isinstance(result, Exception):
            raise result
        return result


# Date parsing


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Date 03-10-2026", date(2026, 10, 3)),
        ("Date 11-09-2026", date(2026, 9, 11)),
        ("Date: 25-12-2025", date(2025, 12, 25)),
        ("Date 1/17/2020", date(2020, 1, 17)),
    ],
)
def test_parse_date(line, expected):
    assert main.parse_date(line) == expected


def test_parse_date_uses_creation_date_for_ambiguous_us_style():
    # 2020-era PDFs printed M/D/YYYY
    assert main.parse_date("Date 2/1/2020", datetime(2020, 2, 1, 9)) == date(2020, 2, 1)
    assert main.parse_date("Date 2/1/2020", datetime(2020, 1, 2, 9)) == date(2020, 1, 2)
    with pytest.raises(main.DateTimeExtractionError):
        main.parse_date("Date 2/1/2020")


def test_parse_date_does_not_fail_when_creation_date_differs(caplog):
    # A stale PDF (published on the 11th, still served on the 14th) must still parse
    parsed = main.parse_date("Date 11-09-2026", datetime(2026, 9, 14))
    assert parsed == date(2026, 9, 11)
    assert "creation date" not in caplog.text


def test_parse_date_warns_on_large_drift(caplog):
    parsed = main.parse_date("Date 25-10-2026", datetime(2026, 3, 10))
    assert parsed == date(2026, 10, 25)
    assert "creation date" in caplog.text


def test_parse_date_rejects_garbage():
    with pytest.raises(main.DateTimeExtractionError):
        main.parse_date("Date 45-45-2026")


def test_extract_date_time():
    text = "Date 03-10-2026\nTime 9:14 AM\nTT BUY ..."
    assert main.extract_date_time(text) == datetime(2026, 10, 3, 9, 14)


def test_validate_date_time_rejects_future():
    with pytest.raises(main.DateTimeExtractionError):
        main.validate_date_time(datetime.now() + timedelta(days=5))


# Rates parsing and validation


def sample_rows(n=main.MIN_EXPECTED_CURRENCIES):
    codes = ["USD"] + [f"C{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(n - 1)]
    return [{"currency_code": c, "rates": ["1.5"] * 8} for c in codes]


def test_extract_currency_rates_splits_merged_zero_cells():
    # Seen in the 2026-09-01 PDF: "0 22.15" was extracted as "022.15"
    text = "MALAYSIAN RINGGIT MYR/INR 0 0 23.24 23.54 0 022.15 24.75"
    rates = main.extract_currency_rates(text)
    assert rates[0]["rates"] == ["0", "0", "23.24", "23.54", "0", "0", "22.15", "24.75"]
    # Zero-led decimals such as 0.62 are left alone
    text = "BANGLADESHI TAKA BDT/INR 0 0 0 0 0 0 0.62 0.83"
    assert main.extract_currency_rates(text)[0]["rates"][-2:] == ["0.62", "0.83"]


def test_validate_rates_drops_malformed_rows():
    rows = sample_rows() + [
        {"currency_code": "BAD", "rates": ["1"] * 7},
        {"currency_code": "OLD", "rates": [str(i) for i in range(9)]},
        {"currency_code": "XYZ", "rates": ["1", "a", "1", "1", "1", "1", "1", "1"]},
    ]
    valid = main.validate_rates(rows)
    codes = {r["currency_code"] for r in valid}
    assert "BAD" not in codes and "XYZ" not in codes
    # The extra trailing column of older PDFs is dropped
    old = next(r for r in valid if r["currency_code"] == "OLD")
    assert old["rates"] == [str(i) for i in range(8)]


def test_validate_rates_normalises_numbers_to_strings():
    rows = sample_rows()
    rows[0]["rates"] = [95.75, 96.6, 95.68, 96.77, 95.68, 96.77, 94.55, 97.15]
    valid = main.validate_rates(rows)
    assert valid[0]["rates"][1] == "96.6"


def test_validate_rates_requires_enough_currencies():
    with pytest.raises(main.RatesExtractionError):
        main.validate_rates(sample_rows()[:3])
    with pytest.raises(main.RatesExtractionError):
        main.validate_rates([])


def test_process_real_pdf_as_text():
    with open(SAMPLE_PDF, "rb") as f:
        date_time, rates = main.process_as_text(io.BytesIO(f.read()))
    assert date_time == datetime(2026, 10, 3, 9, 14)
    usd = next(r for r in rates if r["currency_code"] == "USD")
    assert usd["rates"] == ["95.75", "96.6", "95.68", "96.77", "95.68", "96.77", "94.55", "97.15"]
    assert len(rates) >= main.MIN_EXPECTED_CURRENCIES


def test_process_content_writes_csv(tmp_path):
    with open(SAMPLE_PDF, "rb") as f:
        main.process_content(io.BytesIO(f.read()), save_file=True, output_dir=str(tmp_path))
    with open(tmp_path / "SBI_REFERENCE_RATES_USD.csv") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["DATE"] == "2026-10-03 09:14"
    assert rows[0]["TT BUY"] == "95.75"
    assert (tmp_path / "2026" / "10" / "2026-10-03.pdf").exists()


def test_parse_json_response_handles_code_fences():
    assert main.parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert main.parse_json_response('Here you go: {"a": 1} hope it helps') == {"a": 1}


# Downloading


def test_fetch_pdf_follows_redirects():
    session = FakeSession(
        {
            "https://bank.sbi/x.pdf": make_response(
                "https://bank.sbi/x.pdf", 301, headers={"Location": "https://sbi.bank.in/x.pdf"}
            ),
            "https://sbi.bank.in/x.pdf": make_response("https://sbi.bank.in/x.pdf", 200, PDF_BYTES),
        }
    )
    assert main.fetch_pdf("https://bank.sbi/x.pdf", session) == PDF_BYTES


def test_fetch_pdf_detects_maintenance_redirect():
    # Seen in log.txt: SBI redirects to http://sbi.bank.in/Under_Maintainance.html
    session = FakeSession(
        {
            "https://sbi.bank.in/x.pdf": make_response(
                "https://sbi.bank.in/x.pdf",
                302,
                headers={"Location": "http://sbi.bank.in/Under_Maintainance.html"},
            ),
        }
    )
    with pytest.raises(main.SiteUnderMaintenance):
        main.fetch_pdf("https://sbi.bank.in/x.pdf", session)
    assert session.requested == ["https://sbi.bank.in/x.pdf"]


def test_fetch_pdf_rejects_html_with_details():
    url = "https://sbi.bank.in/x.pdf"
    session = FakeSession(
        {url: make_response(url, 200, b"<html>Access Denied</html>", {"Content-Type": "text/html"})}
    )
    with pytest.raises(main.PdfDownloadError, match="Access Denied"):
        main.fetch_pdf(url, session)


def test_get_latest_pdf_retries_rounds(monkeypatch):
    calls = {"direct": 0}

    def fake_direct(session):
        calls["direct"] += 1
        return (PDF_BYTES if calls["direct"] == 3 else None), False

    monkeypatch.setattr(main, "try_direct_download", fake_direct)
    monkeypatch.setattr(main, "try_proxy_download", lambda: None)
    result = main.get_latest_pdf_from_sbi(rounds=3, delay_seconds=0)
    assert result.getvalue() == PDF_BYTES
    assert calls["direct"] == 3


def test_get_latest_pdf_skips_proxies_during_maintenance(monkeypatch):
    monkeypatch.setattr(main, "try_direct_download", lambda session: (None, True))

    def fail_proxy():
        raise AssertionError("proxies should not be tried during maintenance")

    monkeypatch.setattr(main, "try_proxy_download", fail_proxy)
    with pytest.raises(main.PdfDownloadError):
        main.get_latest_pdf_from_sbi(rounds=2, delay_seconds=0)


def test_proxy_download_survives_missing_proxy(monkeypatch):
    def raise_no_proxy(*args, **kwargs):
        raise main.FreeProxyException("There are no working proxies at this time.")

    monkeypatch.setattr(main.FreeProxy, "get", raise_no_proxy)
    assert main.try_proxy_download() is None


def test_main_returns_non_zero_on_failure(monkeypatch):
    def fail():
        raise main.PdfDownloadError("down")

    monkeypatch.setattr(main, "get_latest_pdf_from_sbi", fail)
    assert main.main() == 1

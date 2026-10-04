import base64
import csv
import glob
import io
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import anthropic
import PyPDF2
import requests
from dateutil import parser
from fp.errors import FreeProxyException
from fp.fp import FreeProxy
from pdf2image import convert_from_bytes
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Constants
SBI_DAILY_RATES_URL = (
    "https://sbi.bank.in/documents/16012/1400784/FOREX_CARD_RATES.pdf"
)
SBI_DAILY_RATES_URL_FALLBACK = (
    "https://bank.sbi/documents/16012/1400784/FOREX_CARD_RATES.pdf"
)
FILE_NAME_FORMAT = "%Y-%m-%d"
FILE_NAME_WITH_TIME_FORMAT = f"{FILE_NAME_FORMAT} %H:%M"
TABLE_COLUMNS = [
    "TT BUY",
    "TT SELL",
    "BILL BUY",
    "BILL SELL",
    "FOREX TRAVEL CARD BUY",
    "FOREX TRAVEL CARD SELL",
    "CN BUY",
    "CN SELL",
]
HEADERS = ["DATE", "PDF FILE"] + TABLE_COLUMNS

# Network tuning. SBI's servers are flaky: connection failures, read timeouts and
# redirects to a maintenance page are all common, but usually clear within minutes.
REQUEST_TIMEOUT = (10, 30)  # (connect, read) seconds
PROXY_REQUEST_TIMEOUT = (5, 20)
DOWNLOAD_ROUNDS = 3
DOWNLOAD_ROUND_DELAY_SECONDS = 120
PROXY_ATTEMPTS_PER_ROUND = 3
MAX_REDIRECTS = 5
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# The PDF has ~30 currencies. Anything far below that means the parse went wrong.
MIN_EXPECTED_CURRENCIES = 10
# The PDF creation date and the printed date should agree. Larger gaps are suspicious.
MAX_DATE_DRIFT_DAYS = 7

ANTHROPIC_MODEL = "claude-haiku-4-5"

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler = logging.FileHandler("log.txt", delay=True)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)
# Also log to the console so failures are visible in the GitHub Actions run output.
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)


class DateTimeExtractionError(Exception):
    pass


class RatesExtractionError(Exception):
    pass


class SiteUnderMaintenance(Exception):
    pass


class PdfDownloadError(Exception):
    pass


def setup_session(retries: int = 3) -> requests.Session:
    """Set up a requests Session with retries on transient errors."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if retries:
        retry = Retry(
            total=retries,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            # Redirects are followed manually in fetch_pdf
            redirect=False,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
    return session


def extract_date_time(
    text: str, file_creation_date: Optional[datetime] = None
) -> datetime:
    """
    Extract date and time from the given text.
    The file creation date, if provided, is used as a sanity check.
    """
    date_line = next(
        (line for line in text.split("\n") if line.strip().lower().startswith("date")),
        None,
    )
    time_line = next(
        (line for line in text.split("\n") if line.strip().lower().startswith("time")),
        None,
    )

    if not date_line or not time_line:
        raise DateTimeExtractionError("Date or time not found in the text")

    parsed_date = parse_date(date_line, file_creation_date)
    parsed_time = parse_time(time_line)

    return datetime.combine(parsed_date, parsed_time)


def parse_date(date_line: str, file_creation_date: Optional[datetime] = None) -> date:
    """
    Parse the date from a given line, handling different formats.

    Current PDFs print DD-MM-YYYY, but older ones (e.g. 2020) used M/D/YYYY.
    When both readings are valid dates, the one closest to the file creation date
    is used; without a creation date, dashed dates are read day-first.
    """
    match = re.search(r"(\d{1,2})([-/.])(\d{1,2})[-/.](\d{4})", date_line)
    if not match:
        try:
            return parser.parse(date_line, fuzzy=True, dayfirst=True).date()
        except (ValueError, OverflowError) as e:
            raise DateTimeExtractionError(
                f"Failed to parse date from '{date_line}': {e}"
            )

    first, separator, second, year = match.groups()
    candidates = []
    for day, month in ((first, second), (second, first)):
        try:
            candidate = date(int(year), int(month), int(day))
        except ValueError:
            continue
        if candidate not in candidates:
            candidates.append(candidate)

    if not candidates:
        raise DateTimeExtractionError(f"Failed to parse date from '{date_line}'")

    if len(candidates) == 1:
        parsed_date = candidates[0]
    elif file_creation_date:
        parsed_date = min(
            candidates, key=lambda d: abs((file_creation_date.date() - d).days)
        )
    elif separator == "-":
        parsed_date = candidates[0]
    else:
        raise DateTimeExtractionError(
            f"Ambiguous date '{date_line}' and no file creation date to resolve it"
        )

    if file_creation_date:
        drift = abs((file_creation_date.date() - parsed_date).days)
        if drift > MAX_DATE_DRIFT_DAYS:
            logger.warning(
                f"Date in PDF ({parsed_date}) is {drift} days away from the file "
                f"creation date ({file_creation_date.date()}). Using the date in the PDF."
            )

    return parsed_date


def parse_time(time_line: str) -> datetime.time:
    """
    Parse the time from a given line.
    """
    try:
        return parser.parse(time_line, fuzzy=True).time()
    except (ValueError, OverflowError) as e:
        raise DateTimeExtractionError(f"Failed to parse time from '{time_line}': {e}")


def extract_currency_rates(text: str) -> List[Dict[str, List[str]]]:
    """Extract currency rates from the given text."""
    # Sometimes the spacing in the parsed text is incorrect.
    # There may be no space between the currency code and the rates.
    # \s* takes care of such cases.
    currency_line_regex = re.compile(r"([A-Z]{3})\/INR\s*((?:\d+(?:\.\d+)?\s?)+)")

    rates = []

    for line in text.split("\n"):
        match = re.search(currency_line_regex, line)
        if match:
            currency, rates_string = match.groups()
            rates.append(
                {
                    "currency_code": currency,
                    "rates": split_merged_zeros(rates_string.strip().split()),
                }
            )

    return rates


def split_merged_zeros(tokens: List[str]) -> List[str]:
    """
    Text extraction sometimes glues a "0" cell to the next value, e.g. "022.15"
    for "0" and "22.15". No real rate starts with a 0 followed by another digit,
    so such tokens are split back into separate cells.
    """
    result = []
    for token in tokens:
        while re.fullmatch(r"0\d.*", token):
            result.append("0")
            token = token[1:]
        result.append(token)
    return result


def validate_rates(rates_data: List[Dict]) -> List[Dict[str, List[str]]]:
    """
    Check the parsed rates and normalise them to strings.
    Rows that don't have one numeric value per column are dropped with a warning.
    Raises RatesExtractionError if too few usable rows remain.
    """
    valid = []
    for row in rates_data or []:
        currency = str(row.get("currency_code", "")).strip().upper()
        rates = row.get("rates") or []
        if not re.fullmatch(r"[A-Z]{3}", currency):
            logger.warning(f"Skipping row with invalid currency code: {row}")
            continue
        if len(rates) < len(TABLE_COLUMNS):
            logger.warning(
                f"Skipping {currency}: expected {len(TABLE_COLUMNS)} rates, "
                f"got {len(rates)}: {rates}"
            )
            continue
        # Older PDFs (2020-2023) have an extra trailing column, which isn't kept
        rates = rates[: len(TABLE_COLUMNS)]
        try:
            numeric = [float(r) for r in rates]
        except (TypeError, ValueError):
            logger.warning(f"Skipping {currency}: non-numeric rates {rates}")
            continue
        if any(r < 0 for r in numeric):
            logger.warning(f"Skipping {currency}: negative rates {rates}")
            continue
        valid.append({"currency_code": currency, "rates": [str(r) for r in rates]})

    currencies = {row["currency_code"] for row in valid}
    if len(valid) < MIN_EXPECTED_CURRENCIES or "USD" not in currencies:
        raise RatesExtractionError(
            f"Only {len(valid)} valid currency rows parsed "
            f"(USD present: {'USD' in currencies})"
        )

    return valid


def validate_date_time(date_time: datetime) -> None:
    """Reject dates that can't be right, e.g. in the future."""
    if date_time.date() > date.today() + timedelta(days=1):
        raise DateTimeExtractionError(f"Extracted date {date_time} is in the future")


def save_to_csv(
    rates_data: List[Dict[str, List[str]]],
    date_time: datetime,
    output_dir: Optional[str] = None,
) -> None:
    """Save the rates data to the corresponding CSV files."""
    pdf_name = date_time.strftime(FILE_NAME_FORMAT) + ".pdf"
    pdf_file_link = f"https://github.com/sahilgupta/sbi-fx-ratekeeper/blob/main/pdf_files/{date_time.year}/{date_time.month}/{pdf_name}"
    formatted_date_time = date_time.strftime(FILE_NAME_WITH_TIME_FORMAT)

    output_dir = output_dir or "csv_files"
    os.makedirs(output_dir, exist_ok=True)

    for row in rates_data:
        currency = row["currency_code"]
        new_data = dict(
            zip(HEADERS, [formatted_date_time, pdf_file_link] + row["rates"])
        )

        csv_file_path = os.path.join(output_dir, f"SBI_REFERENCE_RATES_{currency}.csv")
        csv_rows = []

        if os.path.exists(csv_file_path):
            with open(csv_file_path, "r", encoding="UTF8") as f_in:
                reader = csv.DictReader(f_in)
                csv_rows = list(reader)

        csv_rows.append(new_data)
        rows_uniq = list({v["DATE"]: v for v in csv_rows}.values())
        rows_uniq.sort(
            key=lambda x: datetime.strptime(x["DATE"], FILE_NAME_WITH_TIME_FORMAT)
        )

        # Write to a temp file and rename, so a crash mid-write can't corrupt the CSV
        tmp_path = csv_file_path + ".tmp"
        with open(tmp_path, "w", encoding="UTF8", newline="") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows_uniq)
        os.replace(tmp_path, csv_file_path)


def save_pdf_file(
    file_content: io.BytesIO, date_time: datetime, output_dir: Optional[str] = None
) -> None:
    """Save the PDF file to the appropriate directory."""
    dir_path = os.path.join(
        output_dir or "pdf_files", str(date_time.year), str(date_time.month)
    )
    os.makedirs(dir_path, exist_ok=True)

    pdf_name = date_time.strftime(FILE_NAME_FORMAT) + ".pdf"
    file_path = os.path.join(dir_path, pdf_name)

    with open(file_path, "wb") as f:
        file_content.seek(0)
        f.write(file_content.getbuffer())


def is_pdf(content: bytes) -> bool:
    """The PDF spec allows the %PDF- header anywhere in the first 1024 bytes."""
    return b"%PDF-" in content[:1024]


def describe_response(response: requests.Response) -> str:
    """Summarise a response for logging, so non-PDF replies can be diagnosed."""
    snippet = response.content[:200].decode("utf-8", errors="replace")
    snippet = " ".join(snippet.split())
    return (
        f"status={response.status_code} url={response.url} "
        f"content-type={response.headers.get('Content-Type')} "
        f"length={len(response.content)} body={snippet!r}"
    )


def fetch_pdf(
    url: str,
    session: requests.Session,
    proxies: Optional[Dict[str, str]] = None,
    timeout: Tuple[int, int] = REQUEST_TIMEOUT,
) -> bytes:
    """
    Download the PDF at the given URL.
    Redirects are followed manually so that a redirect to SBI's maintenance page is
    detected immediately, instead of being retried until the retries run out.
    """
    current_url = url
    for _ in range(MAX_REDIRECTS + 1):
        response = session.get(
            current_url, timeout=timeout, proxies=proxies, allow_redirects=False
        )
        if not response.is_redirect:
            break
        location = response.headers.get("Location", "")
        if "maintain" in location.lower() or "maintenance" in location.lower():
            raise SiteUnderMaintenance(f"{current_url} redirected to {location}")
        current_url = urljoin(current_url, location)
    else:
        raise PdfDownloadError(f"Too many redirects starting from {url}")

    if "maintain" in response.url.lower():
        raise SiteUnderMaintenance(f"{url} served the maintenance page")
    if response.status_code != 200:
        raise PdfDownloadError(f"Unexpected response: {describe_response(response)}")
    if not is_pdf(response.content):
        raise PdfDownloadError(f"Response is not a PDF: {describe_response(response)}")

    return response.content


def get_free_proxy() -> Optional[str]:
    try:
        return FreeProxy(timeout=1, rand=True, elite=True, https=True).get()
    except FreeProxyException as e:
        logger.info(f"Could not find a free proxy: {e}")
    except Exception as e:
        logger.info(f"Unexpected error while looking for a free proxy: {e!r}")
    return None


def try_direct_download(session: requests.Session) -> Tuple[Optional[bytes], bool]:
    """
    Try each SBI URL directly.
    Returns the PDF content if successful, and whether the site is under maintenance.
    """
    under_maintenance = False
    for url in [SBI_DAILY_RATES_URL, SBI_DAILY_RATES_URL_FALLBACK]:
        try:
            return fetch_pdf(url, session), False
        except SiteUnderMaintenance as e:
            logger.warning(f"SBI site is under maintenance: {e}")
            under_maintenance = True
        except (requests.RequestException, PdfDownloadError) as e:
            logger.warning(f"Failed to download PDF from {url}: {e!r}")
    return None, under_maintenance


def try_proxy_download() -> Optional[bytes]:
    """Try downloading through a few free proxies."""
    # No retries: a bad proxy should be dropped quickly in favour of the next one
    session = setup_session(retries=0)
    for attempt in range(1, PROXY_ATTEMPTS_PER_ROUND + 1):
        proxy = get_free_proxy()
        if not proxy:
            return None
        try:
            content = fetch_pdf(
                SBI_DAILY_RATES_URL,
                session,
                proxies={"http": proxy, "https": proxy},
                timeout=PROXY_REQUEST_TIMEOUT,
            )
            logger.info(f"Downloaded PDF via proxy {proxy}")
            return content
        except SiteUnderMaintenance as e:
            logger.warning(f"SBI site is under maintenance (via proxy): {e}")
            return None
        except (requests.RequestException, PdfDownloadError) as e:
            logger.info(
                f"Proxy attempt {attempt}/{PROXY_ATTEMPTS_PER_ROUND} via {proxy} "
                f"failed: {e!r}"
            )
    return None


def get_latest_pdf_from_sbi(
    rounds: int = DOWNLOAD_ROUNDS, delay_seconds: int = DOWNLOAD_ROUND_DELAY_SECONDS
) -> io.BytesIO:
    """
    Attempt to download a valid PDF.
    Each round tries the SBI URLs directly, then via free proxies. Outages are
    usually short-lived, so failed rounds are retried after a delay.
    """
    session = setup_session()

    for round_number in range(1, rounds + 1):
        content, under_maintenance = try_direct_download(session)
        if content is None and not under_maintenance:
            logger.info("Failed to download PDF directly. Attempting with proxies...")
            content = try_proxy_download()

        if content is not None:
            return io.BytesIO(content)

        if round_number < rounds:
            logger.info(
                f"Download round {round_number}/{rounds} failed. "
                f"Retrying in {delay_seconds}s..."
            )
            time.sleep(delay_seconds)

    raise PdfDownloadError(f"Unable to retrieve a valid PDF after {rounds} rounds")


def parse_json_response(text: str) -> Dict:
    """Parse JSON from a model response, tolerating code fences or surrounding text."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


IMAGE_PROMPT = """Analyze this image of an SBI forex card rates page.
Check whether it contains the text "be used as reference rates".
For each currency row, parse out the 3-letter ISO currency code from the second column, for instance `USD` from `USD/INR`, and the 8 rates in this column order: TT BUY, TT SELL, BILL BUY, BILL SELL, FOREX TRAVEL CARD BUY, FOREX TRAVEL CARD SELL, CN BUY, CN SELL.
Respond with only a JSON object, with no other text, in this structure:
{"has_reference_rates": true or false, "date": "<date as DD-MM-YYYY>", "time": "<time of publishing in HH:MM AM/PM format>", "forex_rates": [{"currency_code": "USD", "rates": [83.57, 84.42, 83.50, 84.59, 83.50, 84.59, 82.55, 84.90]}]}"""


def process_as_image(
    file_content: io.BytesIO,
) -> Tuple[datetime, List[Dict[str, List[str]]]]:
    """Process the PDF as an image when text extraction fails."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY not set in environment variables.")
    client = anthropic.Anthropic(api_key=api_key, max_retries=4)

    pages_images = convert_from_bytes(file_content.getvalue(), dpi=500, size=2000)

    for page_number, page in enumerate(pages_images[:2], start=1):
        buffered = io.BytesIO()
        page.convert("RGB").save(buffered, format="JPEG")
        image_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": IMAGE_PROMPT},
                ],
            }
        ]

        response = client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=4096, messages=messages
        )

        try:
            response_json = parse_json_response(response.content[0].text)
        except (json.JSONDecodeError, IndexError, AttributeError) as e:
            logger.warning(f"Could not parse model response for page {page_number}: {e}")
            continue

        if not response_json.get("has_reference_rates"):
            continue

        date_time_str = f"Date: {response_json.get('date')}\nTime: {response_json.get('time')}"
        extracted_date_time = extract_date_time(date_time_str)
        rates_data = validate_rates(response_json.get("forex_rates"))
        return extracted_date_time, rates_data

    raise RatesExtractionError("Unable to extract reference rates from images")


def process_as_text(
    file_content: io.BytesIO,
) -> Tuple[datetime, List[Dict[str, List[str]]]]:
    """Extract the date and rates from the PDF's text layer."""
    reader = PyPDF2.PdfReader(file_content, strict=False)
    text = reader.pages[0].extract_text()
    try:
        file_creation_date = reader.metadata.creation_date if reader.metadata else None
    except Exception:
        file_creation_date = None
    extracted_date_time = extract_date_time(text, file_creation_date)

    reference_page = None
    for page in reader.pages[:2]:
        page_text = page.extract_text()
        if "to be used as reference rates" in page_text.lower():
            reference_page = page_text
            break

    if not reference_page:
        raise RatesExtractionError(
            "Text about reference rates not found on the first two pages."
        )

    rates_data = validate_rates(extract_currency_rates(reference_page))
    return extracted_date_time, rates_data


def process_content(
    file_content: io.BytesIO, save_file: bool = False, output_dir: Optional[str] = None
) -> datetime:
    """Process the content, extracting data and saving to CSV."""
    try:
        extracted_date_time, rates_data = process_as_text(file_content)
    except Exception as e:
        logger.warning(
            f"Failed to process PDF as text: {e!r}. Attempting to process as image."
        )
        try:
            extracted_date_time, rates_data = process_as_image(file_content)
        except Exception as image_error:
            raise RatesExtractionError(
                f"Text extraction failed ({e!r}) and image extraction failed "
                f"({image_error!r})"
            ) from image_error

    validate_date_time(extracted_date_time)

    if save_file:
        save_pdf_file(file_content, extracted_date_time, output_dir)

    save_to_csv(rates_data, extracted_date_time, output_dir)

    logger.info(
        f"Saved rates for {len(rates_data)} currencies, "
        f"published {extracted_date_time.strftime(FILE_NAME_WITH_TIME_FORMAT)}"
    )
    return extracted_date_time


def parse_historical_data(
    directory: str, save_file: bool = True, output_dir: Optional[str] = None
) -> None:
    """Parse historical PDF files in the given directory."""
    all_pdfs = sorted(glob.glob(os.path.join(directory, "**/*.pdf"), recursive=True))
    for file_path in all_pdfs:
        logger.info(f"Parsing {file_path}")
        with open(file_path, "rb") as f:
            file_content = io.BytesIO(f.read())
            try:
                process_content(file_content, save_file, output_dir)
            except Exception:
                logger.exception(f"Error processing {file_path}")


def main() -> int:
    try:
        file_content = get_latest_pdf_from_sbi()
        process_content(file_content, save_file=True)
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
        return 1
    return 0


if __name__ == "__main__":
    # Example usage: parse historical data
    # parse_historical_data("/Users/sahilgupta/code/sbi_forex_rates/pdf_files/2024", save_file=False)
    sys.exit(main())

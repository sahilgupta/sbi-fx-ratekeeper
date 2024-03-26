import csv
import glob
import io
import logging
import os
import os.path
import re
from datetime import datetime
from urllib3.util.retry import Retry

import magic
from fp.fp import FreeProxy
import PyPDF2
import requests
from requests_html import HTMLSession
from requests.exceptions import RequestException
from dateutil import parser

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
file_handler = logging.FileHandler("log.txt")
file_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


SBI_DAILY_RATES_URL = (
    "https://www.sbi.co.in/documents/16012/1400784/FOREX_CARD_RATES.pdf"
)
SBI_DAILY_RATES_URL_FALLBACK = (
    "https://bank.sbi/documents/16012/1400784/FOREX_CARD_RATES.pdf"
)

FILE_NAME_FORMAT = "%Y-%m-%d"
FILE_NAME_WITH_TIME_FORMAT = f"{FILE_NAME_FORMAT} %H:%M"


# Compile the regular expression
currency_line_regex = re.compile(r"([A-Z]{3})\/INR\s((?:\d+(?:\.\d+)?\s?)+)")
HEADERS = [
    "DATE",
    "PDF FILE",
    "TT BUY",
    "TT SELL",
    "BILL BUY",
    "BILL SELL",
    "FOREX TRAVEL CARD BUY",
    "FOREX TRAVEL CARD SELL",
    "CN BUY",
    "CN SELL",
]


def extract_date_time(reader_obj):
    text_page_1 = reader_obj.getPage(0).extractText()

    parsed_date = None
    parsed_time = None

    for line in text_page_1.split("\n"):
        if line.startswith("Date"):
            parsed_date = parser.parse(line, fuzzy=True, dayfirst=True).date()

            # sometimes the dates are formatted in the US style, double check if there's a confusion
            parsed_date_us_style = parser.parse(line, fuzzy=True).date()

            if parsed_date != parsed_date_us_style:
                # Double check the date from EXIF data, and use that one.
                creation_date = reader_obj.metadata.creation_date.date()

                if (
                    creation_date == parsed_date
                    or creation_date == parsed_date_us_style
                ):
                    parsed_date = creation_date
                else:
                    raise Exception(f"None of the date formats seem to match. {line}")

        elif line.startswith("Time"):
            parsed_time = parser.parse(line, fuzzy=True).time()

    if not parsed_date or not parsed_time:
        return None

    parsed_datetime = datetime.combine(parsed_date, parsed_time)

    return parsed_datetime


def dump_data(file_content, save_file=False):
    try:
        reader = PyPDF2.PdfReader(file_content, strict=False)
    except PyPDF2.errors.PdfReadError:
        logger.exception("")
        return
    except ValueError:
        logger.exception("")
        return

    extracted_date_time = extract_date_time(reader)
    if not extracted_date_time:
        logger.exception("Unable to extract date and time from the PDF. Aborting.")
        return

    formatted_date_time = extracted_date_time.strftime(FILE_NAME_WITH_TIME_FORMAT)

    logger.debug(f"Successfully parsed date and time {extracted_date_time}")

    if save_file:
        save_pdf_file(file_content, extracted_date_time)

    text_page_1 = reader.getPage(0).extractText()
    text_page_2 = reader.getPage(1).extractText()

    # SBI used to print the reference rates on Page #2 but now
    # does on Page #1. Figure out which page has the reference rates before further processing.
    if "to be used as reference rates" in text_page_1.lower():
        reference_page = text_page_1
    elif "to be used as reference rates" in text_page_2.lower():
        reference_page = text_page_2
    else:
        raise Exception(f"Text about reference rates not found on either page.")

    lines = reference_page.split("\n")

    new_data = None

    for line in lines:
        match = re.search(currency_line_regex, line)

        if match:
            (currency, rates_string) = match.groups()
            rates_list = rates_string.split(" ")

            csv_file_path = os.path.join(
                "csv_files", f"SBI_REFERENCE_RATES_{currency}.csv"
            )
            rows = []
            headers = (
                HEADERS  # Default to static column names if the file doesn't exist
            )

            if os.path.exists(csv_file_path):
                # Use the existing column names
                with open(csv_file_path, "r", encoding="UTF8") as f_in:
                    reader = csv.DictReader(f_in)
                    headers = reader.fieldnames
                    rows = list(reader)

            # Prepare new data entry
            pdf_name = extracted_date_time.strftime(FILE_NAME_FORMAT) + ".pdf"
            pdf_file_link = f"https://github.com/sahilgupta/sbi_forex_rates/blob/main/pdf_files/{str(extracted_date_time.year)}/{str(extracted_date_time.month)}/{pdf_name}"
            new_data = dict(
                zip(headers, [formatted_date_time, pdf_file_link] + rates_list)
            )
            logger.debug(f"New rates found: {new_data}")

            rows.append(new_data)
            rows_uniq = list({v["DATE"]: v for v in rows}.values())

            rows_uniq.sort(
                key=lambda x: datetime.strptime(x["DATE"], FILE_NAME_WITH_TIME_FORMAT)
            )

            with open(csv_file_path, "w", encoding="UTF8") as f_out:
                writer = csv.DictWriter(f_out, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows_uniq)

                logger.debug(f"Updated CSV file with {new_data}")

    if not new_data:
        logger.exception(f"No data matching the currency regex found")
        raise Exception(f"No data parsed from the PDF")


def save_pdf_file(file_content, date_time):
    # Construct the directory path
    dir_path = os.path.join("pdf_files", str(date_time.year), str(date_time.month))

    # Create the directory if it doesn't exist
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    pdf_name = date_time.strftime(FILE_NAME_FORMAT) + ".pdf"

    # Write to a file in the new directory
    with open(os.path.join(dir_path, pdf_name), "wb") as f:
        file_content.seek(0)
        f.write(file_content.getbuffer())


def download_latest_file():
    s = HTMLSession()

    retries = Retry(total=5, backoff_factor=3, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", requests.adapters.HTTPAdapter(max_retries=retries))

    try:
        response = s.get(SBI_DAILY_RATES_URL, timeout=10)
        response.raise_for_status()
    except RequestException as e:
        try:
            response = s.get(
                SBI_DAILY_RATES_URL_FALLBACK,
                timeout=10,
            )
            response.raise_for_status()
        except RequestException as e:
            raise Exception(
                "Unable to retrieve PDF from both the URLs. Error: " + str(e)
            )

    # Check the MIME type since the response may be HTML, even with status code 200
    mime_type = magic.from_buffer(response.content[:128])

    if not mime_type.startswith("PDF document"):
        logger.info(f"Invalid PDF. Response MIME type seems to be {mime_type}")

        # Use proxies to try downloading the file again
        for x in range(5):
            logger.info(f"Using a proxy to retry getting the PDF")
            proxy = FreeProxy(timeout=1, rand=True, elite=True, https=True).get()
            proxies = {"http": proxy}

            response = s.get(SBI_DAILY_RATES_URL, timeout=10, proxies=proxies)
            response.raise_for_status()

            mime_type = magic.from_buffer(response.content[:128])
            if mime_type.startswith("PDF document"):
                logger.info(f"Found a valid PDF in {x+1} try. Breaking away")
                break
        else:
            raise Exception("Was not able to get a valid PDF. Aborting...")

    bytestream = io.BytesIO(response.content)
    save_pdf_file(bytestream, date_time=datetime.now())

    # Need to convert to a byte stream for PDF parser to be able to seek to different address
    return io.BytesIO(response.content)


def parse_historical_data(save_file=True):
    all_pdfs = sorted(
        glob.glob("/Users/sahilgupta/code/sbi_forex_rates/**/*.pdf", recursive=True)
    )

    # file_path = "/Users/sahilgupta/code/sbi_forex_rates/pdf_files/2024/2/2024-02-09.pdf"
    for file_path in all_pdfs:
        logger.info(f"Parsing {file_path}")
        with open(file_path, "rb") as f:
            # Need to convert to a byte stream for PDF parser to be able to seek to different address
            bytestream = io.BytesIO(f.read())

            try:
                dump_data(bytestream, save_file)
            except:
                logger.exception(f"Ran into error for {file_path}")


if __name__ == "__main__":
    # parse_historical_data(save_file=False)
    file_content = download_latest_file()
    dump_data(file_content)

import csv
import glob
import io
import logging
import os
import os.path
import re
from datetime import datetime
from urllib3.util.retry import Retry

import PyPDF2
import requests
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
currency_line_regex = re.compile(
    r"([A-Za-z ]+)\s+(\S{3})(?:/INR){0,1}\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))\s+((?:\d{1,3}\.\d{1,2})|(?:\d{1,3}\.\d)|(?:\d{1,3}))"
)
header_row_regex = re.compile("(([A-Z]{2,4}) (BUY|SELL))")


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

    logger.debug(f"Successfully parsed date and time {extracted_date_time}")

    if save_file:
        save_pdf_file(file_content, extracted_date_time)

    text_page_2 = reader.getPage(1).extractText()
    lines = text_page_2.split("\n")

    header_row = lines[0]
    headers = ["DATE"] + [x[0] for x in re.findall(header_row_regex, header_row)]

    new_data = None

    for line in lines[1:]:
        match = re.search(currency_line_regex, line)
        if match:
            formatted_date_time = extracted_date_time.strftime(
                FILE_NAME_WITH_TIME_FORMAT
            )

            currency = match.groups()[1].split("/")[0]
            csv_file_path = os.path.join(
                "csv_files", f"SBI_REFERENCE_RATES_{currency}.csv"
            )
            rows = []

            if os.path.exists(csv_file_path):
                with open(csv_file_path, "r", encoding="UTF8") as f_in:
                    reader = csv.DictReader(f_in)
                    headers = reader.fieldnames
                    rows = [x for x in reader]

            rates = match.groups()[2:]
            new_data = dict(zip(headers, (formatted_date_time,) + rates))
            logger.debug(f"New rates found: {new_data}")

            rows.append(new_data)
            rows_uniq = list({v["DATE"]: v for v in rows}.values())

            rows_uniq.sort(
                key=lambda x: datetime.strptime(x["DATE"], FILE_NAME_WITH_TIME_FORMAT)
            )

            with open(csv_file_path, "w", encoding="UTF8") as f_out:
                writer = csv.DictWriter(f_out, fieldnames=headers)

                writer.writeheader()
                for row in rows_uniq:
                    writer.writerow(row)

                logger.debug(f"Updated CSV file with {new_data}")
    if not new_data:
        logger.exception(f"No data matching the currency regex found")


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
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.67 Safari/537.36"
    }

    s = requests.Session()

    retries = Retry(total=5, backoff_factor=3, status_forcelist=[500, 502, 503, 504])
    s.mount("https://", requests.adapters.HTTPAdapter(max_retries=retries))

    try:
        response = s.get(SBI_DAILY_RATES_URL, headers=headers, timeout=10)
        response.raise_for_status()
    except RequestException as e:
        try:
            response = s.get(SBI_DAILY_RATES_URL_FALLBACK, headers=headers, timeout=10)
            response.raise_for_status()
        except RequestException as e:
            raise Exception("Unable to retrieve PDF from both the URLs. Error: " + str(e))

    bytestream = io.BytesIO(response.content)
    save_pdf_file(bytestream, date_time=datetime.now())

    # Need to convert to a byte stream for PDF parser to be able to seek to different address
    return io.BytesIO(response.content)


def parse_historical_data(save_file=True):
    all_pdfs = sorted(
        glob.glob("/Users/sahilgupta/code/sbi_forex_rates/**/*.pdf", recursive=True)
    )

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

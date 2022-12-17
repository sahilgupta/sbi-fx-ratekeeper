import io
import PyPDF2
import re
import os
import os.path
import csv
import glob
from dateutil import parser
from datetime import datetime
import requests

# Compile the regular expression
currency_line_regex = re.compile(
    r"([A-Za-z ]+)\s+(\S+/INR)\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})"
)
header_row_regex = re.compile("(([A-Z]{2,4}) (BUY|SELL))")

SBI_DAILY_RATES_URL = (
    "https://www.sbi.co.in/documents/16012/1400784/FOREX_CARD_RATES.pdf"
)

FILE_NAME_FORMAT = "%Y-%m-%d"
FILE_NAME_WITH_TIME_FORMAT = f"{FILE_NAME_FORMAT} %H:%M"


def extract_text(file_content):
    reader = PyPDF2.PdfReader(file_content, strict=False)

    # Extract the text from the pages
    text_page_1 = reader.getPage(0).extractText()
    text_page_2 = reader.getPage(1).extractText()

    return text_page_1, text_page_2


def extract_date_time(text):
    for line in text.split("\n"):
        if line.startswith("Date"):
            date = parser.parse(line, fuzzy=True, dayfirst=True).date()
        elif line.startswith("Time"):
            time = parser.parse(line, fuzzy=True).time()

    if not date or not time:
        return None
    else:
        parsed_datetime = datetime.combine(date, time)

        return parsed_datetime


def dump_data(file_content, save_file=False):
    try:
        page_1_text, page_2_text = extract_text(file_content)
    except PyPDF2.errors.PdfReadError:
        return
    except ValueError:
        return

    extracted_date_time = extract_date_time(page_1_text)

    if save_file:
        save_pdf_file(file_content, extracted_date_time)

    lines = page_2_text.split("\n")

    header_row = lines[0]
    headers = ["DATE"] + [x[0] for x in re.findall(header_row_regex, header_row)]

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

    response = requests.get(SBI_DAILY_RATES_URL, headers=headers, timeout=5)
    response.raise_for_status()

    bytestream = io.BytesIO(response.content)
    save_pdf_file(bytestream, date_time=datetime.now())

    # Need to convert to a byte stream for PDF parser to be able to seek to different address
    return io.BytesIO(response.content)


def parse_historical_data():
    all_pdfs = sorted(glob.glob("/Users/sahilgupta/code/sbi-tt-rates-historical/*.pdf"))

    for file_path in all_pdfs:
        with open(file_path, "rb") as f:
            # Need to convert to a byte stream for PDF parser to be able to seek to different address
            bytestream = io.BytesIO(f.read())

            dump_data(bytestream, save_file=True)


# parse_historical_data()
file_content = download_latest_file()
dump_data(file_content)
import PyPDF2
import re
import os
import csv
import glob
from dateutil import parser
from datetime import datetime

# Compile the regular expression
currency_line_regex = re.compile(
    r"([A-Za-z ]+)\s+(\S+/INR)\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})"
)
header_row_regex = re.compile("(([A-Z]{2,4}) (BUY|SELL))")

all_pdfs = glob.glob("/Users/sahilgupta/code/sbi-tt-rates-historical/*.pdf")

file_path = "/Users/sahilgupta/FOREX_CARD_RATES.pdf"
for file_path in all_pdfs:
    with open(file_path, "rb") as pdf_file:
        # Create a PDF reader object
        try:
            reader = PyPDF2.PdfFileReader(pdf_file, strict=False)
        except OSError:
            continue

        # 1st page
        page = reader.getPage(0)
        # Extract the text from the page
        text = page.extractText()

        for line in text.split("\n"):
            if line.startswith("Date"):
                date = parser.parse(line, fuzzy=True, dayfirst=True)
            elif line.startswith("Time"):
                time = parser.parse(line, fuzzy=True)

        if not date or not time:
            raise Exception("meh")

        # 2nd page
        page = reader.getPage(1)
        # Extract the text from the page
        text = page.extractText()
        lines = text.split("\n")

        header_row = lines[0]
        headers = ["DATE"] + [x[0] for x in re.findall(header_row_regex, header_row)]

        for line in lines[1:]:
            match = re.search(currency_line_regex, line)
            if match:
                currency = match.groups()[1].split("/")[0]
                rates = match.groups()[2:]

                date_time = f"{date.strftime('%Y-%m-%d')} {time.strftime('%H:%M')}"
                new_data = dict(zip(headers, (date_time,) + rates))

                csv_file_path = f"{currency}.csv"
                rows = []

                if os.path.exists(csv_file_path):
                    with open(csv_file_path, "r", encoding="UTF8") as f_in:
                        reader = csv.DictReader(f_in)
                        headers = reader.fieldnames
                        rows = [x for x in reader]

                rows.append(new_data)
                rows_uniq = list({v['DATE']:v for v in rows}.values())

                rows_uniq.sort(key=lambda x: datetime.strptime(x['DATE'], "%Y-%m-%d %H:%M"))

                with open(csv_file_path, "w", encoding="UTF8") as f_out:
                    writer = csv.DictWriter(f_out, fieldnames=headers)

                    # write the header
                    writer.writeheader()

                    for row in rows_uniq:
                        writer.writerow(row)

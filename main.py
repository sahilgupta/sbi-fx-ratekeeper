import PyPDF2
import re
import csv

# Compile the regular expression
date_regex = re.compile(r'Date (\d{2}-\d{2}-\d{4})')
time_regex = r"(\d{1,2}):(\d{2})\s+(AM|PM)"
currency_line_regex = re.compile(r"([A-Za-z ]+)\s+(\S+/INR)\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})\s+(\d{1,3}\.\d{2})")
header_row_regex = re.compile("(([A-Z]{2,4}) (BUY|SELL))")

file_path = '/Users/sahilgupta/FOREX_CARD_RATES.pdf'

with open(file_path, 'rb') as pdf_file:
    # Create a PDF reader object
    reader = PyPDF2.PdfFileReader(pdf_file)

    # 1st page
    page = reader.getPage(0)
    # Extract the text from the page
    text = page.extractText()

    match = date_regex.search(text)
    date = match.groups()[0]

    time = re.search(time_regex, text).group()

    # 2nd page
    page = reader.getPage(1)
    # Extract the text from the page
    text = page.extractText()
    lines = text.split('\n')

    header_row = lines[0]
    headers = ["DATE"] + [x[0] for x in re.findall(header_row_regex, header_row)]

    for line in lines[1:]:
        match = re.search(currency_line_regex, line)
        if match:
            currency = match.groups()[1].split('/')[0]
            rates = match.groups()[2:]

            date_time = f"{date} {time}"
            new_data = dict(zip(headers, (date_time, ) + rates))

            csv_file_path = f'{currency}.csv'

            with open(csv_file_path, 'r', encoding='UTF8') as f_in:
                reader = csv.DictReader(f_in)
                headers = reader.fieldnames
                rows = [x for x in reader]

            with open(csv_file_path, 'w', encoding='UTF8') as f_out:
                print(headers)
                writer = csv.DictWriter(f_out, fieldnames=headers)

                # write the header
                writer.writeheader()
                writer.writerow(new_data)

                for row in rows:
                    writer.writerow(row)
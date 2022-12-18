import os
import io
from datetime import date, timedelta
import requests
from main import save_pdf_file, dump_data

start_date = date(2022, 1, 1)
end_date = date(2022, 11, 30)
delta = timedelta(days=1)

while start_date <= end_date:
    day = start_date.strftime("%d")
    month = start_date.strftime("%m")
    year = start_date.strftime("%Y")

    URL = f"https://mksco.in/wp-content/uploads/{year}/{month}/{day}-{month}-{year}-stamp.pdf"
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.67 Safari/537.36"
    }

    file_path = os.path.join("pdf_files", year, str(start_date.month), f"{year}-{month}-{day}.pdf")

    if not os.path.exists(file_path):
        print(f"PDF not found for {file_path}")
        print(URL)
        try:
            response = requests.get(URL, headers=headers, timeout=5)
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            if error.response.status_code == 404:
                print("ran into 404")
        else:
            bytestream = io.BytesIO(response.content)
            dump_data(bytestream, save_file=True)
    else:
        print(f"PDF found for {file_path}. Moving on...")

    start_date += delta
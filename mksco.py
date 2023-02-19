import io
import os
from datetime import date, timedelta
from urllib3.util.retry import Retry

import requests

from main import dump_data, save_pdf_file

start_date = date(2021, 5, 27)
end_date = date(2021, 12, 31)
delta = timedelta(days=1)

while start_date <= end_date:
    day = start_date.strftime("%d")
    month = start_date.strftime("%m")
    year = start_date.strftime("%Y")

    URL = f"https://mksco.in/wp-content/uploads/{year}/{month}/{day}-{month}-{year}-stamp.pdf"
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.67 Safari/537.36"
    }

    file_path = os.path.join(
        "pdf_files", year, str(start_date.month), f"{year}-{month}-{day}.pdf"
    )

    if not os.path.exists(file_path):
        print(f"PDF not found for {file_path}")
        print(URL)

        s = requests.Session()

        retries = Retry(
            total=5, backoff_factor=3, status_forcelist=[500, 502, 503, 504]
        )
        s.mount("https://", requests.adapters.HTTPAdapter(max_retries=retries))

        try:
            response = s.get(URL, headers=headers, timeout=5)
            response.raise_for_status()
        except requests.exceptions.HTTPError as error:
            # catch the 500 server error

            if error.response.status_code == 404:
                print("ran into 404")
        else:
            bytestream = io.BytesIO(response.content)
            dump_data(bytestream, save_file=True)
    else:
        print(f"PDF found for {file_path}. Moving on...")

    start_date += delta

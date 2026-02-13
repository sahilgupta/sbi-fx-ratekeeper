import pandas as pd
import os
import re
import glob

if __name__ == "__main__":
    # Automatically discover all CSV files and extract currency codes
    csv_files = glob.glob("csv_files/SBI_REFERENCE_RATES_*.csv")
    currency_info = []
    
    for csv_file in csv_files:
        # Extract currency code using regex
        match = re.search(r'SBI_REFERENCE_RATES_([A-Z]{3})\.csv$', csv_file)
        if match:
            currency_code = match.group(1)
            currency_info.append((currency_code, csv_file))
    
    # Sort by currency code for consistent output
    currency_info.sort(key=lambda x: x[0])
    sbi_currency_col = "TT BUY"
    month_end_dates = pd.date_range(start="2020-01-01", end=pd.Timestamp.today(), freq="ME").date

    # Read all FX CSVs once
    fx_data = {}
    for currency_code, csv_file_path in currency_info:
        sbi_df = pd.read_csv(csv_file_path)
        sbi_df['Date'] = pd.to_datetime(sbi_df['DATE'], errors='coerce')
        sbi_df = sbi_df.dropna(subset=['Date'])
        # Set index for fast lookup
        sbi_df.set_index(sbi_df['Date'].dt.date, inplace=True)
        fx_data[currency_code] = sbi_df

    # Prepare data for writing to CSV
    rows = []
    for d in month_end_dates:
        rates = []
        used_dates = []
        for currency_code, _ in currency_info:
            sbi_df = fx_data[currency_code]
            rate = None
            search_date = d
            used_date = d
            # Fallback to previous dates if rate not found or rate is 0
            while rate is None:
                if search_date in sbi_df.index:
                    rate_val = sbi_df.loc[search_date, sbi_currency_col]
                    # If multiple rates for the same date, take the last one
                    if isinstance(rate_val, pd.Series):
                        rate_val = rate_val.iloc[-1]
                    if pd.notna(rate_val) and rate_val > 0:
                        rate = rate_val
                        used_date = search_date
                    else:
                        search_date = search_date - pd.Timedelta(days=1)
                        if search_date < month_end_dates[0]:
                            rate = None
                            used_date = None
                            break
                else:
                    search_date = search_date - pd.Timedelta(days=1)
                    if search_date < month_end_dates[0]:
                        rate = None
                        used_date = None
                        break
            rates.append(rate if rate is not None else "")
            used_dates.append(used_date)
        # Only write the rates row (ignore used_dates/fallback info for CSV)
        rows.append([str(d)] + [r if r != "" else "" for r in rates])

    # Create column names dynamically
    currency_columns = [currency_code for currency_code, _ in currency_info]
    columns = ["Date"] + currency_columns
    
    # Write to forex_inr_rates.csv
    df_out = pd.DataFrame(rows, columns=columns)
    df_out.to_csv("forex_inr_rates.csv", index=False)
    print(f"forex_inr_rates.csv written with month-end TT BUY rates for {', '.join(currency_columns)}.")
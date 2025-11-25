# SBI FX RateKeeper

[Explanation to Rule 26 of the Income Tax Rules, 1962](https://incometaxindia.gov.in/_layouts/15/dit/pages/viewer.aspx?grp=rule&cname=cmsid&cval=103120000000007372&searchfilter=) advises using telegraphic transfer rates of SBI as reference for calculating foreign income or capital gains. SBI publishes the rates daily on its website, barring Sundays and bank holidays. Unfortunately, they do not provide any way to access historical data.

Well, worry no more. SBI FX RateKeeper saves the daily SBI forex rates in a CSV file, enabling easy access to historical rates. Rates for each currency are in a separate file; for example, SBI_REFERENCE_RATES_USD.csv has only the USD data.

- New rates are added daily, automatically
- Fully compatible with Microsoft Excel or Google Sheets
- **Enhanced script now supports all 31 available currencies automatically**

## Consolidated Month-End Rates CSV

The `update_forex_rate.py` script generates a consolidated `forex_inr_rates.csv` file containing month-end TT BUY rates for all available currencies. This script has been enhanced to:

- **Automatically discover all currencies**: No need to manually specify currency codes
- **Use local CSV files**: Reads directly from the `csv_files/` folder instead of downloading from GitHub
- **Support all 31 currencies**: AED, AUD, BDT, BHD, CAD, CHF, CNY, DKK, EUR, GBP, HKD, IDR, JPY, KES, KRW, KWD, LKR, MYR, NOK, NZD, OMR, PKR, QAR, RUB, SAR, SEK, SGD, THB, TRY, USD, ZAR
- **Dynamic processing**: Automatically adapts to new currencies when CSV files are added

### Usage

To generate the consolidated month-end rates CSV:

```bash
python update_forex_rate.py
```

This will create a `forex_inr_rates.csv` file with:
- Date column (month-end dates from January 2020 to present)
- One column for each available currency with TT BUY rates
- Automatic fallback to previous dates when rates are not available for specific month-ends

You can easily [browse and search the rates on GitHub](https://github.com/sahilgupta/sbi_forex_rates/tree/main/csv_files):

![Browse historical SBI TTBR on GitHub](https://raw.githubusercontent.com/sahilgupta/sbi_forex_rates/main/images/Browse%20historical%20SBI%20TTBR%20on%20GitHub.gif)
<br/>

OR download the CSV files and use with Excel or Google Sheets
![Download historical SBI TTBR CSV](https://raw.githubusercontent.com/sahilgupta/sbi_forex_rates/main/images/Download%20historical%20SBI%20TTBR%20CSV.gif)
<br/>

The PDFs (saved from the SBI servers) are available in the *pdf_files/* folder. For verification, direct link to each day's PDF is also published along with the data. 

**Note:**
The SBI explicitly mentions that only the rates published for ₹10-20 lakh transaction range are to be considered as reference rates.
The reference rates do NOT change based on your transaction value, which could be ₹100 or ₹1 Cr.

## Known Limitations
- Data is only available from Jan 2020 onwards.
- For some reason, SBI doesn't publish the rates file on all working days; no data is available for such days. You can either get the rates from [RBI Reference Rate Archive](https://www.rbi.org.in/scripts/ReferenceRateArchive.aspx), or from some third-party FX rates vendor such as [OANDA](https://www.oanda.com/fx-for-business/historical-rates).

Typically, the RBI Reference rates have a 20-30 paise difference with the SBI TT Buying rates. This delta is reasonably stable over time. You can find the average difference for a few dates post 2020, take the published RBI rates and adjust them by the standard delta before using.

### Credits
Credit for data prior to Dec 2022 goes to:

- [Shivam Khandelwal](https://github.com/skbly7) for saving the PDF files of SBI's daily forex rates on GitHub since 2020 at [https://github.com/skbly7/sbi-tt-rates-historical]

- Forex Rate Card archives of Maneesh K. Singh & Co. [2021](https://mksco.in/forex-card-rates-2021/) and [2022](https://mksco.in/forex-card-rates-2022/)

- Internet Archive Wayback Machine

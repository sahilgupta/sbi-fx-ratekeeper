# SBI Historical Forex Rates

[Explanation to Rule 26 of the Income Tax Rules, 1962](https://incometaxindia.gov.in/_layouts/15/dit/pages/viewer.aspx?grp=rule&cname=cmsid&cval=103120000000007372&searchfilter=%5B%7B%22crawledpropertykey%22:0,%22value%22:%22income-tax+rules%22,%22searchoperand%22:2%7D,%7B%22crawledpropertykey%22:1,%22value%22:%22rule%22,%22searchoperand%22:2%7D%5D&k=income+tax,income+tax&isdlg=0) advises using telegraphic transfer rates of SBI as reference for calculating foreign income or capital gains. SBI publishes the rates daily on its website, barring Sundays and bank holidays. Unfortunately, there is no official way to access historical data.

Well, worry no more. This project saves the daily SBI forex rates in a CSV file, enabling easy access to historical rates. Rates for each currency are in a separate file; for example, SBI_REFERENCE_RATES_USD.csv has only the USD data.

- The new rates are added daily, automatically
- Fully compatible with Microsoft Excel or Google Sheets

You can easily [browse and search the rates on GitHub](https://github.com/sahilgupta/sbi_forex_rates/tree/main/csv_files) itself:

![Browse historical SBI TTBR on GitHub](https://raw.githubusercontent.com/sahilgupta/sbi_forex_rates/main/images/Browse%20historical%20SBI%20TTBR%20on%20GitHub.gif)
<br/>

OR download the CSV files and use with Excel or Google Sheets
![Download historical SBI TTBR CSV](https://raw.githubusercontent.com/sahilgupta/sbi_forex_rates/main/images/Download%20historical%20SBI%20TTBR%20CSV.gif)
<br/>

The link to the PDF file (saved from the SBI servers) is also published with each day's data to make it easy to verify. They are also available in the *pdf_files/* folder.

**Note:**
The reference rates are on the 2nd page of each PDF.

## Known Limitations

- Data is only available from Jan 2020 onwards.
- For some reason, SBI doesn't publish the rates file on all working days; no data is available for such days. You can either get the rates from [RBI Reference Rate Archive](https://www.rbi.org.in/scripts/ReferenceRateArchive.aspx), or from some third-party FX rates vendor such as [OANDA](https://www.oanda.com/fx-for-business/historical-rates).

Typically, the RBI Reference rates have a 20-30 paise difference with the SBI TT Buying rates. This delta is reasonably stable over time. You can find the average difference for a few dates post 2020, take the published RBI rates and adjust them by the standard delta before using.

### Credits

Credit for data prior to Dec 2022 goes to:

- [Shivam Khandelwal](https://github.com/skbly7) for saving the PDF files of SBI's daily forex rates on GitHub since 2020 at [https://github.com/skbly7/sbi-tt-rates-historical]

- Forex Rate Card archives of Maneesh K. Singh & Co. [2021](https://mksco.in/forex-card-rates-2021/) and [2022](https://mksco.in/forex-card-rates-2022/)

- Internet Archive Wayback Machine

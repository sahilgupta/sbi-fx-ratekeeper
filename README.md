# SBI Historical Forex Rates

Section 26 of the ITR advises using SBI TTBR as reference foreign exchange rates for calculating capital gains. SBI publishes these forex rates daily but does not provide a way to access  historical data. Well, no more.

This project downloads and stores daily SBI forex rates in a CSV file, with separate files for each currency. For example, SBI_REFERENCE_RATES_USD.csv has only the USD data.

- The new rates are added daily, automatically
- Fully compatible with Microsoft Excel or Google Sheets

**Note:**

The PDF files from SBI servers are also available in the *pdf_files* folder. The reference rates are on the 2nd page of each PDF.

## Known Limitations

Note that data prior to Dec 2022 is NOT complete and I do not know of reliable ways to backfill it completely. Please reach out to me if you know of workarounds.

### Credits

Credit for data prior to Dec 2022 goes to:

- [Shivam Khandelwal](https://github.com/skbly7) for saving the PDF files of SBI's daily forex rates on GitHub since 2020 at [https://github.com/skbly7/sbi-tt-rates-historical]

- Forex Rate Card archives of Maneesh K. Singh & Co. [2021](https://mksco.in/forex-card-rates-2021/) and [2022](https://mksco.in/forex-card-rates-2022/))

- Internet Archive Wayback Machine
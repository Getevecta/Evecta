---
title: Importing leads from Excel
audience: customer
version: 1
last_reviewed: 2026-08-12
---

# Importing leads from Excel

## How do I import leads from Excel?

Open Lead Database and click Upload Excel. Select an .xlsx or .xls workbook.

## Can I upload CSV through Upload Excel?

No. Upload Excel accepts .xlsx or .xls only. CSV is not accepted by that importer.

## Which columns are required for an Excel lead import?

Every workbook must have a header row with Company Name and Email columns, and every non-blank data row must contain both values. Accepted header aliases include company and business name variations, and email and e-mail variations.

## Which Excel columns are optional?

Optional columns are Industry, Contact Number, Address, and Website. Common alternatives such as Sector, Category, Phone, Mobile, Location, Web, URL, and Website URL are recognized.

## What is the Excel upload limit?

Evecta processes up to 1,000 non-blank data rows per upload. Blank rows are ignored, and rows beyond the 1,000-row limit are reported and not imported.

## How are duplicates and Excel import errors handled?

A lead whose email already exists in the user's Lead Database is skipped. Repeated email addresses within the same workbook are also skipped. Rows missing Company Name or Email fail validation, blank rows are ignored, and the result summary reports imported, duplicate, failed, blank, and over-limit rows. An empty file, missing required headers, or an unreadable workbook produces an error.

## What should I do if Excel upload reports zero imported rows?

Confirm that the workbook has a header and non-blank data rows, includes Company Name and Email, and that both required values exist on every intended row. Review whether every row was a duplicate, invalid, blank, or beyond the 1,000-row limit. Use the product sample workbook as a formatting reference.

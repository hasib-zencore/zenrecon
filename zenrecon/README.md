# ZenRecon — Odoo 19

Technical addon: `zenrecon`

ZenRecon is the standalone module that combines the complete functionality of
`bank_system_reconciliation` and `bank_reconciliation_accounting_setup`. It
provides one Bank Reconciliation application for VISA, Mastercard, NPSB,
transaction reconciliation, accounting configuration, and voucher management.
It has no dependency on either legacy custom addon.

For a new database, install only `zenrecon`. Converting a database where either
legacy addon is already installed requires a controlled data/XML-ID migration;
take a database and filestore backup before that transition.

## VISA VSS

One source TXT file uploaded from the user's computer creates one VSS import/report set.
The module scans that file and produces exactly five consolidated business tables:

- VSS-110 — Settlement Summary Report
- VSS-120 — Interchange Value Report
- VSS-130 — Reimbursement Fees Report
- VSS-140 — Visa Charges Report
- VSS-210 — Currency Conversion Fees Report

The module does **not** mix rows from different imported files.

For each target report ID, the parser searches the complete source file. Every
logical block that explicitly contains `*** NO DATA FOR THIS REPORT ***` is
skipped. Every data-bearing block is parsed and its rows are appended to the
single consolidated table for that VSS report type. Header/context values such
as Production Date, Report Date, Reporting For, Rollup To, Funds Xfer Entity and
Settlement Currency are repeated on each stored row.

The VSS-110 consolidated list corresponds to the single wide table in the user's
reference spreadsheet/PDF (the PDF visually splits the wide table across pages,
but it is one logical table).

## Workflow

1. Open **Bank Reconciliation → Data Intake**.
2. Administrators map every logical source folder to its own exact physical directory.
   Each directory must be visible to the Odoo server (a local server folder or mounted share);
   no common physical root is required.
3. Put the daily files in their configured VISA, Mastercard, NPSB, CMS, or CBS folders.
4. Click **Export Files**, choose **All configured folders** or one or more selected streams,
   select the business date, and process.
5. Missing and invalid files remain visible with their status; successful files open their
   existing import records. Exact file content is protected from duplicate processing by SHA-256.
6. Open the created VSS Import and use the five smart buttons: **VSS-110**, **VSS-120**,
   **VSS-130**, **VSS-140**, **VSS-210**. Each button opens one consolidated read-only table containing only rows from
   that import's source TXT file.

`NO DATA` source blocks do not create rows. Technical parse problems are shown
under **Parsing Exceptions**.

## Upgrade from the earlier prototype

Replace the addon folder with this build and upgrade the module. Then open the
existing import and click **Process / Rebuild 5 Reports**. The rebuild deletes
only derived prototype report/line data for that import and recreates the five
consolidated tables. The original source file is retained as an attachment and
is never modified.

Example upgrade command:

```bash
    cd /opt/odoo19
    ./odoo-bin -c /opt/odoo19/odoo.conf \
        -d YOUR_DATABASE \
        -u zenrecon \
        --stop-after-init
```

Then start Odoo normally.

## Mastercard IPM

Mastercard processing is isolated under **Bank System Reconciliation → Mastercard**.
Users upload a binary IPM file directly from their computer. The source file is
retained as an attachment for audit, while its RDW records and data
elements are stored in dedicated Mastercard tables.

The implementation follows the supplied CMS/IPM reference rules:

- 1014-byte physical blocks with 1012 usable bytes
- four-byte big-endian RDW logical records
- ASCII/EBCDIC auto-detection and the supplied ISO 8583:1993 field map
- MTI/DE24 record classification
- duplicate detection by SHA-256
- per-record parsing errors without mixing data into VISA tables
- masked PAN values only; full PAN and raw record payloads are not persisted

Use **Download Complete XLSX** from a Mastercard import or its records list for
the audit workbook. It includes file metadata, one wide record sheet with every
DE present in that file, the normalized data-element table, and parsing errors.

## Mastercard Clearing

Place the clearing file in its configured **Data Intake** folder and export the
Mastercard Clearing stream. Clearing imports and rows remain isolated from VISA
and Mastercard IPM tables. The parser stores notification (`1IP727020-AA`),
acknowledgement (`1IP727010-AA`), and clearing-day-total (`1IP728010-AA`) rows.

The former standalone `mastercard_clearing` addon is absorbed during upgrade.
Its tables, records, sequence, views, and external identifiers are retained by
`zenrecon`; after a successful upgrade, the old addon folder
can be removed without uninstalling it separately.

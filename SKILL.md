---
name: batch-oa-downloader
description: Parse BibTeX, RIS, or RTS citation exports, check each record for lawful open-access full text, batch-download verified PDFs, mark records with no free copy, and package results. Use when a user provides a bibliography export and wants OA checking or bulk PDF retrieval.
metadata:
  compatibility: Requires Python 3 and internet access. Uses only lawful open-access URLs; optional Unpaywall lookup benefits from a contact email.
---

# Batch OA Downloader

Turn a user-provided `.bib`, `.ris`, or `.rts` bibliography into a verified PDF bundle and an access-status report.

## Required behavior

1. Confirm the input file and output folder. Treat `.rts` as RIS when its contents use RIS tags such as `TY  -`, `TI  -`, and `ER  -`.
2. Run `scripts/batch_oa_download.py`. This workflow is正文-only; it does not retrieve Supporting Information.
3. Use only lawful open-access locations returned by OpenAlex, Unpaywall, Crossref, PubMed Central, repositories, or an explicitly supplied legitimate PDF URL. Never bypass a paywall, CAPTCHA, DRM, login, or access control.
4. Validate every successful response as an actual PDF. Do not rename HTML, login pages, or error bodies as PDF files.
5. Return the generated ZIP plus `access_report.csv` to the user. Summarize counts by status and call out unresolved metadata.

## Command

```powershell
python scripts/batch_oa_download.py --input "<references.bib|references.ris|references.rts>" --out "<output-folder>" --zip
```

If the user provides a contact email, or `UNPAYWALL_EMAIL` is configured, add `--email`. Do not invent an email address and do not require one: OpenAlex remains available without it.

Useful options:

```text
--email ADDRESS       Enable Unpaywall and identify polite API traffic
--delay SECONDS       Delay between records (default: 0.5)
--timeout SECONDS     Per-request timeout (default: 30)
--max-records N       Batch limit (default: 500; hard maximum: 2000)
--max-pdf-mib N       Per-PDF size limit (default: 100; hard maximum: 500)
--dry-run             Parse and report records without network access
--zip                 Create <output-folder>.zip containing PDFs and reports
```

## Status interpretation

- `open_access_downloaded`: a lawful OA PDF was downloaded and validated.
- `open_access_found_download_failed`: an OA URL existed, but no candidate produced a valid PDF.
- `closed_or_no_oa_found`: metadata was resolved, but no lawful free PDF was found. Present this to the user as “可能收费/未发现合法免费全文”, not as proof that every access route is paid.
- `metadata_unresolved`: the record could not be matched confidently; manual DOI/title checking is needed.
- `invalid_record`: the exported record lacks a usable DOI and title.

The CSV and JSON manifest are the audit trail. Preserve them in the ZIP. Never place credentials, cookies, or session data in reports.

## Defensive defaults

- Accept only `.bib`, `.ris`, and `.rts` inputs up to 10 MiB.
- Require a new or empty output folder so a rerun cannot mix stale files into the bundle.
- Permit downloads only from public HTTPS destinations; reject credentials in URLs, local/private addresses, and unsafe redirects.
- Stream PDFs with a size ceiling, write to a temporary `.part` file, validate the `%PDF-` signature, then atomically rename.
- For title-only records, reject low-confidence OpenAlex matches instead of downloading a potentially unrelated paper.
- Bound timeouts, batch size, PDF size, error-message length, and API response size.

#!/usr/bin/env python3
"""Parse BibTeX/RIS, resolve lawful OA PDFs, validate downloads, and report results."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import os
import re
import socket
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

UA = "BatchOADownloader/1.0 (+https://openalex.org)"
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_PDF_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_RECORDS = 500
ALLOWED_INPUT_SUFFIXES = {".bib", ".ris", ".rts"}


def clean_doi(value: str) -> str:
    match = DOI_RE.search(value or "")
    return match.group(0).rstrip(".,;)}]").lower() if match else ""


def bib_value(block: str, key: str) -> str:
    pattern = rf"(?ims)^\s*{re.escape(key)}\s*=\s*(?:\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}|\"([^\"]*)\")\s*,?"
    match = re.search(pattern, block)
    return " ".join((match.group(1) or match.group(2) or "").split()) if match else ""


def parse_bibtex(text: str) -> list[dict]:
    starts = list(re.finditer(r"(?m)^\s*@\w+\s*\{", text))
    records = []
    for i, match in enumerate(starts):
        block = text[match.start() : starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        cite = re.match(r"(?s)\s*@\w+\s*\{\s*([^,]+)", block)
        records.append({
            "id": cite.group(1).strip() if cite else f"record-{i+1}",
            "title": bib_value(block, "title"),
            "doi": clean_doi(bib_value(block, "doi") or bib_value(block, "url")),
            "year": bib_value(block, "year"),
        })
    return records


def parse_ris(text: str) -> list[dict]:
    records, current = [], {}
    for raw in text.splitlines():
        match = re.match(r"^([A-Z0-9]{2})\s{0,2}-\s?(.*)$", raw.strip())
        if not match:
            continue
        tag, value = match.groups()
        if tag == "TY":
            current = {"id": f"record-{len(records)+1}"}
        elif tag in {"TI", "T1", "CT"} and not current.get("title"):
            current["title"] = value.strip()
        elif tag == "DO":
            current["doi"] = clean_doi(value)
        elif tag in {"PY", "Y1"} and not current.get("year"):
            current["year"] = value[:4]
        elif tag in {"ID", "AN"} and value:
            current["id"] = value.strip()
        elif tag == "UR" and not current.get("doi"):
            current["doi"] = clean_doi(value)
        elif tag == "ER":
            if current:
                records.append(current)
            current = {}
    if current:
        records.append(current)
    return records


def load_records(path: Path, max_records: int) -> list[dict]:
    if path.suffix.lower() not in ALLOWED_INPUT_SUFFIXES:
        raise ValueError("input must use .bib, .ris, or .rts")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError(f"input exceeds {MAX_INPUT_BYTES // (1024 * 1024)} MiB")
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    if path.suffix.lower() == ".bib" or re.search(r"(?m)^\s*@\w+\s*\{", text):
        records = parse_bibtex(text)
    else:
        records = parse_ris(text)
    if len(records) > max_records:
        raise ValueError(f"input has {len(records)} records; limit is {max_records}")
    for i, record in enumerate(records, 1):
        record.setdefault("id", f"record-{i}")
        record.setdefault("title", "")
        record.setdefault("doi", "")
        record.setdefault("year", "")
    return records


def public_https_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        port = parsed.port or 443
        for info in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM):
            address = ipaddress.ip_address(info[4][0])
            if not address.is_global:
                return False
        return True
    except (ValueError, OSError, socket.gaierror):
        return False


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_https_url(newurl):
            raise urllib.error.URLError("unsafe redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_open(url: str, headers: dict, timeout: int):
    if not public_https_url(url):
        raise urllib.error.URLError("unsafe or non-public HTTPS URL blocked")
    return urllib.request.build_opener(SafeRedirect()).open(
        urllib.request.Request(url, headers=headers), timeout=timeout
    )


def get_json(url: str, timeout: int, email: str = "") -> dict:
    headers = {"User-Agent": f"{UA}{' mailto:' + email if email else ''}", "Accept": "application/json"}
    with safe_open(url, headers, timeout) as response:
        declared = int(response.headers.get("Content-Length") or 0)
        if declared > MAX_JSON_BYTES:
            raise ValueError("metadata response too large")
        data = response.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise ValueError("metadata response too large")
        return json.loads(data)


def openalex_lookup(record: dict, timeout: int, email: str) -> dict | None:
    base = "https://api.openalex.org/works/"
    if record["doi"]:
        url = base + "https://doi.org/" + urllib.parse.quote(record["doi"], safe="/")
    elif record["title"]:
        params = {"search": record["title"], "per-page": "1"}
        if email:
            params["mailto"] = email
        data = get_json(base + "?" + urllib.parse.urlencode(params), timeout, email)
        results = data.get("results", [])
        return results[0] if results else None
    else:
        return None
    try:
        return get_json(url + (("&" if "?" in url else "?") + "mailto=" + urllib.parse.quote(email) if email else ""), timeout, email)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def oa_candidates(work: dict, doi: str, timeout: int, email: str) -> list[tuple[str, str]]:
    found = []
    locations = [work.get("best_oa_location") or {}] + (work.get("locations") or [])
    for loc in locations:
        if loc.get("is_oa") and loc.get("pdf_url") and public_https_url(loc["pdf_url"]):
            found.append((loc["pdf_url"], "openalex"))
    if email and doi:
        try:
            upw = get_json(f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi, safe='/')}?email={urllib.parse.quote(email)}", timeout, email)
            loc = upw.get("best_oa_location") or {}
            if loc.get("url_for_pdf") and public_https_url(loc["url_for_pdf"]):
                found.append((loc["url_for_pdf"], "unpaywall"))
        except (urllib.error.URLError, json.JSONDecodeError):
            pass
    unique, seen = [], set()
    for url, source in found:
        if url not in seen:
            seen.add(url)
            unique.append((url, source))
    return unique


def safe_name(text: str, fallback: str) -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", text).strip(" ._")
    return (value[:150] or fallback) + ".pdf"


def download_pdf(url: str, destination: Path, timeout: int, email: str, max_bytes: int) -> tuple[bool, str]:
    headers = {"User-Agent": f"{UA}{' mailto:' + email if email else ''}", "Accept": "application/pdf"}
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        digest, size, prefix = hashlib.sha256(), 0, b""
        with safe_open(url, headers, timeout) as response:
            declared = int(response.headers.get("Content-Length") or 0)
            if declared > max_bytes:
                return False, "PDF exceeds configured size limit"
            with partial.open("xb") as handle:
                while True:
                    chunk = response.read(min(1024 * 1024, max_bytes - size + 1))
                    if not chunk:
                        break
                    if not prefix:
                        prefix = chunk[:5]
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("PDF exceeds configured size limit")
                    digest.update(chunk)
                    handle.write(chunk)
        if prefix != b"%PDF-":
            return False, "response was not a PDF"
        os.replace(partial, destination)
        return True, digest.hexdigest()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        message = re.sub(r"https?://[^\s]+", "[URL redacted]", str(exc))[:300]
        return False, message
    finally:
        partial.unlink(missing_ok=True)


def title_similarity(left: str, right: str) -> float:
    tokenize = lambda value: set(re.findall(r"[a-z0-9]+", value.casefold()))
    a, b = tokenize(left), tokenize(right)
    return len(a & b) / len(a | b) if a and b else 0.0


def write_reports(results: list[dict], out: Path) -> None:
    (out / "manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    fields = ["id", "title", "doi", "year", "status", "oa_url", "source", "file", "note"]
    with (out / "access_report.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--email", default=os.environ.get("UNPAYWALL_EMAIL", ""))
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-pdf-mib", type=int, default=DEFAULT_MAX_PDF_BYTES // (1024 * 1024))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--zip", action="store_true", dest="make_zip")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input file not found: {args.input}")
    if args.timeout < 1 or args.timeout > 300:
        parser.error("--timeout must be between 1 and 300 seconds")
    if args.max_records < 1 or args.max_records > 2000:
        parser.error("--max-records must be between 1 and 2000")
    if args.max_pdf_mib < 1 or args.max_pdf_mib > 500:
        parser.error("--max-pdf-mib must be between 1 and 500")
    if args.email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", args.email):
        parser.error("--email is not a valid email address")
    try:
        records = load_records(args.input, args.max_records)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if not records:
        parser.error("no BibTeX or RIS records found")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("output folder must be new or empty to prevent stale or overwritten results")
    args.out.mkdir(parents=True, exist_ok=True)
    pdf_dir = args.out / "PDFs"
    pdf_dir.mkdir(exist_ok=True)
    results = []
    for index, record in enumerate(records, 1):
        row = {**record, "status": "", "oa_url": "", "source": "", "file": "", "note": ""}
        if not record["doi"] and not record["title"]:
            row["status"] = "invalid_record"
        elif args.dry_run:
            row["status"] = "not_checked_dry_run"
        else:
            try:
                work = openalex_lookup(record, args.timeout, args.email)
                if not work:
                    row["status"] = "metadata_unresolved"
                else:
                    if not record["doi"] and title_similarity(record["title"], work.get("display_name", "")) < 0.6:
                        row.update(status="metadata_unresolved", note="title match confidence too low")
                        results.append(row)
                        print(f"[{index}/{len(records)}] {row['status']}: {row['title'] or row['id']}")
                        continue
                    row["doi"] = record["doi"] or clean_doi(work.get("doi", ""))
                    row["title"] = record["title"] or work.get("display_name", "")
                    candidates = oa_candidates(work, row["doi"], args.timeout, args.email)
                    for url, source in candidates:
                        filename = f"{index:04d}_" + safe_name(row["title"], row["doi"] or row["id"])
                        ok, detail = download_pdf(url, pdf_dir / filename, args.timeout, args.email, args.max_pdf_mib * 1024 * 1024)
                        if ok:
                            row.update(status="open_access_downloaded", oa_url=url, source=source, file=f"PDFs/{filename}", note=f"sha256:{detail}")
                            break
                        row.update(oa_url=url, source=source, note=detail)
                    if not row["status"]:
                        row["status"] = "open_access_found_download_failed" if candidates else "closed_or_no_oa_found"
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError, ValueError) as exc:
                note = re.sub(r"https?://[^\s]+", "[URL redacted]", str(exc))[:300]
                row.update(status="metadata_unresolved", note=note)
        results.append(row)
        print(f"[{index}/{len(records)}] {row['status']}: {row['title'] or row['id']}")
        if not args.dry_run and index < len(records):
            time.sleep(max(0, args.delay))
    write_reports(results, args.out)
    if args.make_zip:
        archive = shutil.make_archive(str(args.out.resolve()), "zip", root_dir=args.out)
        print(f"ZIP: {archive}")
    counts = {}
    for row in results:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(json.dumps({"records": len(results), "summary": counts, "output": str(args.out.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

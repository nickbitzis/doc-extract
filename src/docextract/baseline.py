"""A rule-based extractor, written the way these usually start: regular expressions.

It is the baseline the model has to beat, and it runs offline. It handles
the common cases and shows exactly where hand-written rules run out: new
layouts, written-out dates, and numbers in another country's format.
"""

from __future__ import annotations

import re
from datetime import date

from .schema import CURRENCIES, Invoice, LineItem

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
NUM = r"\d{1,3}(?:[.,]\d{3})*[.,]\d{2}"
DATE = r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}\.\d{2}\.\d{4}|[A-Z][a-z]+ \d{1,2}, \d{4}|\d{1,2} [A-Z][a-z]{2} \d{4}"


def parse_number(s: str) -> float:
    s = s.strip().lstrip("$€£CA")
    if re.search(r",\d{2}$", s):  # 1.234,50
        s = s.replace(".", "").replace(",", ".")
    return float(s.replace(",", ""))


def parse_date(s: str) -> str | None:
    s = s.strip()
    if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):
        return s
    if m := re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", s):
        return date(int(m[3]), int(m[1]), int(m[2])).isoformat()
    if m := re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s):
        return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
    if m := re.fullmatch(r"([A-Z][a-z]+) (\d{1,2}), (\d{4})", s):
        return date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])).isoformat()
    if m := re.fullmatch(r"(\d{1,2}) ([A-Z][a-z]{2}) (\d{4})", s):
        return date(int(m[3]), MONTHS[m[2].lower()], int(m[1])).isoformat()
    return None


def _find(pattern: str, text: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def extract(text: str) -> Invoice:
    first = text.strip().splitlines()[0]
    vendor = _find(r"^(?:Thanks,|Regards,)\s*\n(.+)$", text, re.MULTILINE) or first.strip("| ").split(" | ")[0]
    number = _find(r"(?:Invoice No:|inv#|Invoice)\s+([A-Z#]*-?\d+)", text)
    dates = re.findall(DATE, text)
    issued = parse_date(dates[0]) if dates else None
    due_raw = _find(rf"(?:due:?|pay by|Due \|)\s*({DATE})", text)
    currency = next((c for c in CURRENCIES if re.search(rf"\b{c}\b", text)), "USD")
    bill_to = _find(r"Bill to:\s*\n\s*(.+)", text) or _find(r"billed (.+)", text) or _find(r"\| Customer \| (.+?) \|", text) or _find(r"Hello (.+?) team", text) or ""
    po = _find(r"\b(PO-\d+)", text, 0)

    items = []
    for m in re.finditer(rf"^(.+?)\s+(\d+)\s+({NUM})\s+({NUM})\s*$", text, re.MULTILINE):  # block layout
        items.append(LineItem(m[1].strip(), float(m[2]), parse_number(m[3]), parse_number(m[4])))
    for m in re.finditer(rf"^- (.+?): (\d+) x \S?({NUM}) = \S?({NUM})", text, re.MULTILINE):  # email
        items.append(LineItem(m[1], float(m[2]), parse_number(m[3]), parse_number(m[4])))
    for m in re.finditer(rf"^\| ([^|]+?) \| (\d+) \| ({NUM}) \| ({NUM}) \|", text, re.MULTILINE):  # table
        items.append(LineItem(m[1], float(m[2]), parse_number(m[3]), parse_number(m[4])))
    for m in re.finditer(rf"^(\d+) @ ({NUM})\s+(.+?)\s+({NUM})$", text, re.MULTILINE):  # receipt
        items.append(LineItem(m[3], float(m[1]), parse_number(m[2]), parse_number(m[4])))

    def money_after(label: str) -> float:
        v = _find(rf"{label}\D{{0,40}}?({NUM})", text)
        return parse_number(v) if v else 0.0

    return Invoice(
        vendor_name=vendor or "",
        invoice_number=number or "",
        invoice_date=issued or "",
        due_date=parse_date(due_raw) if due_raw else None,
        currency=currency,
        bill_to=bill_to,
        po_number=po,
        line_items=items,
        subtotal=money_after(r"sub(?:total)?"),
        tax=money_after(r"\btax"),
        total=money_after(r"(?:(?<!sub)total|amount due)"),
    )

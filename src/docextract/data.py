"""Generate synthetic invoices as plain text, with the true values saved alongside.

Real invoices vary in layout, date format, and number format, and that
variety is what breaks hand-written parsers. Four layouts are generated here,
from a tidy header block to a pasted email, with US, European, and written
dates, and both 1,234.50 and 1.234,50 style amounts. A few invoices contain a
deliberate arithmetic error so validation has something to catch.
"""

from __future__ import annotations

import json
import random
from datetime import date, timedelta
from pathlib import Path

from .schema import Invoice, LineItem

VENDORS = ["Northwind Supply Co.", "Bluefin Logistics LLC", "Acorn Office Goods", "Harbor & Pine Consulting", "Quarry Street Print Shop", "Kestrel Cloud Services", "Marlowe Industrial Parts", "Saffron Catering Group"]
CUSTOMERS = ["Trailhead Outfitters Inc.", "Larkspur Software Ltd.", "Cobalt Dental Partners", "Riverbend City Library", "Meridian Freight Corp."]
ITEMS = [("Printer paper, case of 10 reams", 42.5), ("Toner cartridge, black", 89.0), ("On-site support, per hour", 135.0), ("Pallet delivery", 220.0), ("Standing desk frame", 349.0), ("Monthly hosting plan", 480.0), ("Brochure printing, 500 units", 315.0), ("Catered lunch, per person", 18.75), ("Hydraulic hose fitting", 12.4), ("Strategy workshop, half day", 1850.0), ("Shipping labels, roll", 9.99), ("Ergonomic chair", 289.0)]
TAX_RATES = {"USD": 0.0825, "EUR": 0.2, "GBP": 0.2, "CAD": 0.13}
SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "CAD": "CA$"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def money(x: float, style: str) -> str:
    s = f"{x:,.2f}"
    if style == "eu":
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return s


def fmt_date(d: date, style: str) -> str:
    if style == "iso":
        return d.isoformat()
    if style == "us":
        return f"{d.month:02d}/{d.day:02d}/{d.year}"
    if style == "eu":
        return f"{d.day:02d}.{d.month:02d}.{d.year}"
    if style == "long":
        return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"
    return f"{d.day} {MONTHS[d.month - 1][:3]} {d.year}"  # "short"


KNOWN = ("block", "email", "table", "receipt")
HOLDOUT = ("letter", "columns", "keyvalue")


def make_invoice(rng: random.Random, n: int, layouts=KNOWN) -> tuple[Invoice, dict]:
    currency = rng.choice(["USD", "USD", "USD", "EUR", "GBP", "CAD"])
    issued = date(2026, 1, 5) + timedelta(days=rng.randrange(280))
    due = issued + timedelta(days=rng.choice([15, 30, 45])) if rng.random() < 0.85 else None
    items = []
    for desc, price in rng.sample(ITEMS, rng.randint(1, 4)):
        qty = rng.choice([1, 1, 2, 3, 5, 10, 12, 25])
        items.append(LineItem(desc, float(qty), price, round(qty * price, 2)))
    subtotal = round(sum(i.amount for i in items), 2)
    tax = round(subtotal * TAX_RATES[currency], 2)
    inv = Invoice(
        vendor_name=rng.choice(VENDORS),
        invoice_number=rng.choice(["INV-", "", "#", "A"]) + str(10000 + n * 37 + rng.randrange(30)),
        invoice_date=issued.isoformat(),
        due_date=due.isoformat() if due else None,
        currency=currency,
        bill_to=rng.choice(CUSTOMERS),
        po_number=f"PO-{rng.randrange(1000, 9999)}" if rng.random() < 0.6 else None,
        line_items=items,
        subtotal=subtotal,
        tax=tax,
        total=round(subtotal + tax, 2),
    )
    style = {
        "layout": rng.choice(layouts),
        "date": "eu" if currency in ("EUR",) and rng.random() < 0.7 else rng.choice(["iso", "us", "long", "short"]),
        "money": "eu" if currency == "EUR" and rng.random() < 0.7 else "us",
        "error": rng.random() < 0.12,
    }
    return inv, style


def render(inv: Invoice, style: dict) -> str:
    d = lambda iso: fmt_date(date.fromisoformat(iso), style["date"])
    m = lambda x: money(x, style["money"])
    sym = SYMBOL[inv.currency]
    shown_total = inv.total + (10.0 if style["error"] else 0.0)  # a typo on the printed total
    lines = []
    if style["layout"] == "block":
        lines += [inv.vendor_name.upper(), "", "INVOICE", f"Invoice No: {inv.invoice_number}", f"Date: {d(inv.invoice_date)}"]
        if inv.due_date:
            lines.append(f"Payment due: {d(inv.due_date)}")
        if inv.po_number:
            lines.append(f"Your PO: {inv.po_number}")
        lines += ["", "Bill to:", f"  {inv.bill_to}", "", f"{'Description':<36}{'Qty':>6}{'Unit':>12}{'Amount':>12}"]
        for it in inv.line_items:
            lines.append(f"{it.description:<36}{it.quantity:>6g}{m(it.unit_price):>12}{m(it.amount):>12}")
        lines += ["", f"{'Subtotal':>54}{m(inv.subtotal):>12}", f"{'Tax':>54}{m(inv.tax):>12}", f"{'TOTAL ' + inv.currency:>54}{m(shown_total):>12}"]
    elif style["layout"] == "email":
        lines += [f"From: billing@{inv.vendor_name.split()[0].lower()}.example", f"Subject: Invoice {inv.invoice_number} for {inv.bill_to}", "",
                  f"Hello {inv.bill_to} team,", "", f"Please find our invoice {inv.invoice_number}, dated {d(inv.invoice_date)}, for the following:", ""]
        for it in inv.line_items:
            lines.append(f"- {it.description}: {it.quantity:g} x {sym}{m(it.unit_price)} = {sym}{m(it.amount)}")
        lines += ["", f"Subtotal {sym}{m(inv.subtotal)}, tax {sym}{m(inv.tax)}, for a total of {sym}{m(shown_total)} ({inv.currency})."]
        if inv.due_date:
            lines.append(f"Kindly pay by {d(inv.due_date)}.")
        if inv.po_number:
            lines.append(f"Reference your purchase order {inv.po_number} on the remittance.")
        lines += ["", "Thanks,", inv.vendor_name]
    elif style["layout"] == "table":
        lines += [f"| {inv.vendor_name} | Invoice {inv.invoice_number} |", "|---|---|", f"| Issued | {d(inv.invoice_date)} |",
                  f"| Due | {d(inv.due_date) if inv.due_date else 'On receipt'} |", f"| Customer | {inv.bill_to} |", f"| PO | {inv.po_number or 'n/a'} |", "",
                  "| Item | Qty | Price | Line total |", "|---|---:|---:|---:|"]
        for it in inv.line_items:
            lines.append(f"| {it.description} | {it.quantity:g} | {m(it.unit_price)} | {m(it.amount)} |")
        lines += [f"| Subtotal | | | {m(inv.subtotal)} |", f"| Tax | | | {m(inv.tax)} |", f"| Total ({inv.currency}) | | | {m(shown_total)} |"]
    elif style["layout"] == "letter":
        parts = ", ".join(f"{it.quantity:g} of {it.description.lower()} at {m(it.unit_price)} each ({m(it.amount)})" for it in inv.line_items)
        lines += [f"{inv.vendor_name}", "", f"To the accounts team at {inv.bill_to}:", "",
                  f"This letter is our invoice number {inv.invoice_number}, issued on {d(inv.invoice_date)}. It covers {parts}."
                  + (f" It relates to your order {inv.po_number}." if inv.po_number else ""),
                  "", f"Before tax the charges come to {m(inv.subtotal)}. Tax adds {m(inv.tax)}, so the amount payable is {inv.currency} {m(shown_total)}."
                  + (f" Please settle it no later than {d(inv.due_date)}." if inv.due_date else " Payment is due on receipt."),
                  "", "Yours sincerely,", "Accounts Receivable"]
    elif style["layout"] == "columns":
        lines += [f"BILLING STATEMENT  //  {inv.vendor_name}", f"customer ......... {inv.bill_to}", f"document ......... {inv.invoice_number}",
                  f"issued ........... {d(inv.invoice_date)}", f"pay before ....... {d(inv.due_date) if inv.due_date else '-'}", f"order ref ........ {inv.po_number or '-'}", "",
                  f"{'AMOUNT':>12}  DETAIL"]
        for it in inv.line_items:
            lines.append(f"{m(it.amount):>12}  {it.description} ({it.quantity:g} units, {m(it.unit_price)} per unit)")
        lines += [f"{m(inv.subtotal):>12}  net", f"{m(inv.tax):>12}  vat/sales tax", f"{m(shown_total):>12}  GRAND TOTAL, {inv.currency}"]
    elif style["layout"] == "keyvalue":
        kv = [("doc_type", "invoice"), ("seller", inv.vendor_name), ("buyer", inv.bill_to), ("ref", inv.invoice_number), ("issue_dt", d(inv.invoice_date)),
              ("due_dt", d(inv.due_date) if inv.due_date else ""), ("buyer_po", inv.po_number or ""), ("ccy", inv.currency)]
        lines += [f"{k}={v}" for k, v in kv]
        for n, it in enumerate(inv.line_items, start=1):
            lines.append(f"line.{n}=desc:{it.description};qty:{it.quantity:g};price:{m(it.unit_price)};ext:{m(it.amount)}")
        lines += [f"net={m(inv.subtotal)}", f"tax={m(inv.tax)}", f"gross={m(shown_total)}"]
    else:  # receipt: compact, like text pasted from a PDF
        lines += [f"{inv.vendor_name}", f"inv# {inv.invoice_number}  {d(inv.invoice_date)}", f"billed {inv.bill_to}"]
        if inv.po_number:
            lines.append(f"p.o. {inv.po_number}")
        for it in inv.line_items:
            lines.append(f"{it.quantity:g} @ {m(it.unit_price)}  {it.description}  {m(it.amount)}")
        lines += [f"sub {m(inv.subtotal)}  tax {m(inv.tax)}", f"amount due {sym}{m(shown_total)} {inv.currency}"]
        if inv.due_date:
            lines.append(f"net terms, due {d(inv.due_date)}")
    return "\n".join(lines) + "\n"


def generate(folder: str | Path, count: int = 40, seed: int = 11, layouts=KNOWN) -> Path:
    """Write invoice text files and a truth.jsonl with the correct values for each."""
    folder = Path(folder)
    docs = folder / "invoices"
    docs.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    with open(folder / "truth.jsonl", "w") as truth:
        for n in range(1, count + 1):
            inv, style = make_invoice(rng, n, layouts)
            name = f"invoice-{n:03d}.txt"
            (docs / name).write_text(render(inv, style))
            # The truth records what the document says. An invoice with a typo'd
            # total keeps the printed total, and is marked so validation can be checked.
            record = inv.to_dict()
            if style["error"]:
                record["total"] = round(inv.total + 10.0, 2)
            truth.write(json.dumps({"file": name, "layout": style["layout"], "has_error": style["error"], "invoice": record}) + "\n")
    return folder

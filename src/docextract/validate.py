"""Business-rule checks on an extracted invoice.

A schema guarantees the shape of the output, not that it is right. These
checks catch both extraction mistakes and mistakes in the document itself,
and anything that fails goes to a person instead of straight into the ledger.
"""

from __future__ import annotations

from datetime import date

from .schema import CURRENCIES, Invoice

TOLERANCE = 0.011  # a cent, plus float noise


def check(inv: Invoice) -> list[str]:
    problems = []
    for n, it in enumerate(inv.line_items, start=1):
        if abs(it.quantity * it.unit_price - it.amount) > TOLERANCE:
            problems.append(f"line {n}: {it.quantity:g} x {it.unit_price:.2f} is {it.quantity * it.unit_price:.2f}, not {it.amount:.2f}")
    if not inv.line_items:
        problems.append("no line items")
    elif abs(sum(it.amount for it in inv.line_items) - inv.subtotal) > TOLERANCE:
        problems.append(f"line items add up to {sum(it.amount for it in inv.line_items):.2f}, but the subtotal is {inv.subtotal:.2f}")
    if abs(inv.subtotal + inv.tax - inv.total) > TOLERANCE:
        problems.append(f"subtotal plus tax is {inv.subtotal + inv.tax:.2f}, but the total is {inv.total:.2f}")
    if inv.currency not in CURRENCIES:
        problems.append(f"unknown currency {inv.currency!r}")
    try:
        issued = date.fromisoformat(inv.invoice_date)
        if inv.due_date and date.fromisoformat(inv.due_date) < issued:
            problems.append("due date is before the invoice date")
    except ValueError:
        problems.append("a date is not in YYYY-MM-DD form")
    if inv.subtotal > 0 and not 0 <= inv.tax / inv.subtotal <= 0.3:
        problems.append(f"tax is {inv.tax / inv.subtotal:.0%} of the subtotal, outside the expected range")
    return problems

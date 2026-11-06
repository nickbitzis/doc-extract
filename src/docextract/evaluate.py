"""Field-level scoring against the true values.

Document-level "all fields right" is the number that matters for automation,
but per-field accuracy says where to spend effort. Both are reported, along
with how well validation routed the invoices that have real errors.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .schema import FIELDS, Invoice
from .validate import check


def _norm_text(s) -> str:
    return " ".join(str(s or "").lower().replace(".", "").replace(",", "").split())


def field_correct(name: str, got: Invoice, want: Invoice) -> bool:
    a, b = getattr(got, name), getattr(want, name)
    if name in ("subtotal", "tax", "total"):
        return abs(float(a) - float(b)) < 0.005
    if name == "line_items":
        if len(a) != len(b):
            return False
        return all(
            abs(x.quantity - y.quantity) < 1e-9 and abs(x.unit_price - y.unit_price) < 0.005 and abs(x.amount - y.amount) < 0.005
            for x, y in zip(a, b)
        )
    if name in ("vendor_name", "bill_to", "invoice_number"):
        return _norm_text(a).lstrip("#") == _norm_text(b).lstrip("#")
    return a == b


@dataclass
class Case:
    file: str
    layout: str
    has_error: bool
    truth: Invoice


def load_truth(folder: str | Path) -> list[Case]:
    rows = [json.loads(line) for line in (Path(folder) / "truth.jsonl").read_text().splitlines() if line.strip()]
    return [Case(r["file"], r["layout"], r["has_error"], Invoice.from_dict(r["invoice"])) for r in rows]


@dataclass
class Report:
    n: int = 0
    per_field: dict = field(default_factory=lambda: {f: 0 for f in FIELDS})
    exact: int = 0
    by_layout: dict = field(default_factory=dict)  # layout -> [exact, total]
    flagged_errors: int = 0
    real_errors: int = 0
    false_flags: int = 0
    failures: list = field(default_factory=list)

    def add(self, case: Case, got: Invoice | None):
        self.n += 1
        layout = self.by_layout.setdefault(case.layout, [0, 0])
        layout[1] += 1
        self.real_errors += case.has_error
        if got is None:
            self.failures.append(case.file)
            return
        right = [f for f in FIELDS if field_correct(f, got, case.truth)]
        for f in right:
            self.per_field[f] += 1
        if len(right) == len(FIELDS):
            self.exact += 1
            layout[0] += 1
        flagged = bool(check(got))
        if case.has_error and flagged:
            self.flagged_errors += 1
        if flagged and not case.has_error:
            self.false_flags += 1

    def as_text(self) -> str:
        out = [f"{self.n} invoices. All fields right: {self.exact}/{self.n} ({self.exact / max(1, self.n):.0%})", "", "Field accuracy"]
        for f in FIELDS:
            out.append(f"  {f:<15} {self.per_field[f] / max(1, self.n):6.0%}")
        out += ["", "All fields right, by layout"]
        for name, (ok, total) in sorted(self.by_layout.items()):
            out.append(f"  {name:<15} {ok}/{total}")
        out += ["", f"Validation caught {self.flagged_errors} of {self.real_errors} invoices with a real arithmetic error, and flagged {self.false_flags} clean ones."]
        if self.failures:
            out.append(f"Extraction failed on: {', '.join(self.failures)}")
        return "\n".join(out)

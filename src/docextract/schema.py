"""The invoice schema, as a dataclass for Python and as JSON Schema for the model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

CURRENCIES = ("USD", "EUR", "GBP", "CAD")


@dataclass
class LineItem:
    description: str
    quantity: float
    unit_price: float
    amount: float


@dataclass
class Invoice:
    vendor_name: str
    invoice_number: str
    invoice_date: str  # YYYY-MM-DD
    due_date: str | None
    currency: str
    bill_to: str
    po_number: str | None
    line_items: list[LineItem] = field(default_factory=list)
    subtotal: float = 0.0
    tax: float = 0.0
    total: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Invoice":
        items = [LineItem(**{k: it[k] for k in ("description", "quantity", "unit_price", "amount")}) for it in d.get("line_items", [])]
        return cls(
            vendor_name=d["vendor_name"],
            invoice_number=d["invoice_number"],
            invoice_date=d["invoice_date"],
            due_date=d.get("due_date"),
            currency=d["currency"],
            bill_to=d["bill_to"],
            po_number=d.get("po_number"),
            line_items=items,
            subtotal=float(d["subtotal"]),
            tax=float(d["tax"]),
            total=float(d["total"]),
        )


FIELDS = ("vendor_name", "invoice_number", "invoice_date", "due_date", "currency", "bill_to", "po_number", "subtotal", "tax", "total", "line_items")

_str = {"type": "string"}
_num = {"type": "number"}
_date = {"type": "string", "description": "ISO date, YYYY-MM-DD"}

JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor_name": {**_str, "description": "The company that issued the invoice."},
        "invoice_number": _str,
        "invoice_date": _date,
        "due_date": {"type": ["string", "null"], "description": "ISO date, YYYY-MM-DD, or null if not stated."},
        "currency": {"type": "string", "enum": list(CURRENCIES)},
        "bill_to": {**_str, "description": "The customer company being billed."},
        "po_number": {"type": ["string", "null"], "description": "Purchase order number, or null if not stated."},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"description": _str, "quantity": _num, "unit_price": _num, "amount": _num},
                "required": ["description", "quantity", "unit_price", "amount"],
                "additionalProperties": False,
            },
        },
        "subtotal": _num,
        "tax": _num,
        "total": _num,
    },
    "required": list(FIELDS),
    "additionalProperties": False,
}

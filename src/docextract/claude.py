"""Extraction with Claude, using structured outputs so the reply always matches the schema."""

from __future__ import annotations

import json

from .schema import JSON_SCHEMA, Invoice

SYSTEM = """You extract data from invoices into JSON.

Rules:
- Copy values as they appear in the document. Do not fix or recompute anything, even if the arithmetic looks wrong. Downstream checks handle that.
- Dates become YYYY-MM-DD. Slashes mean month/day/year. Dots mean day.month.year.
- Amounts become plain numbers. In "1.234,50" the comma is the decimal point.
- vendor_name is the company that issued the invoice. bill_to is the customer.
- Use null for a due date or purchase order number that the document does not state. "On receipt" means no due date."""


class ExtractionError(RuntimeError):
    pass


def extract(text: str, model: str = "claude-opus-5-5", effort: str = "low", client=None) -> tuple[Invoice, dict]:
    """Return the invoice and token usage. Raises ExtractionError if the model declines or stops early."""
    if client is None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise RuntimeError("Install the Claude extra first: uv sync --extra claude") from exc
        client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM,
        messages=[{"role": "user", "content": f"<document>\n{text}\n</document>"}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": JSON_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise ExtractionError("The model declined this document.")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("The reply was cut off before the JSON was complete.")
    body = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ExtractionError(f"The reply was not valid JSON: {exc}") from exc
    usage = {"input_tokens": getattr(response.usage, "input_tokens", 0), "output_tokens": getattr(response.usage, "output_tokens", 0)}
    return Invoice.from_dict(data), usage

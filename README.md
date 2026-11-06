# docextract

Turn invoices into validated JSON. Claude reads each document and returns data that is guaranteed to match a schema, business rules check the result, and an evaluation scores every field against the true values. A regex extractor is included as the baseline, and the sample data is built to show exactly where that baseline breaks.

## Why

Document extraction is one of the most common first projects for AI in operations: invoices, purchase orders, claims, onboarding forms. The model call is the easy part. A production pipeline needs three more things:

1. **Output that always parses.** Structured outputs constrain the reply to a JSON Schema, so there is no "the model returned prose this time" failure mode.
2. **Checks on the content.** A schema says the total is a number, not that it is the right number. Validation checks that line items add up, that subtotal plus tax equals the total, that dates are in order, and that tax is in a sane range. Anything that fails goes to a person.
3. **A score.** Per-field accuracy shows where extraction is weak. "All fields right" is the number that decides how much can be automated.

## The sample data and what it shows

`data.py` generates synthetic invoices from fixed seeds, with the true values saved in `truth.jsonl`. Amounts come as `1,234.50` or `1.234,50`, dates as `2026-03-04`, `03/04/2026`, `04.03.2026`, `March 4, 2026`, or `4 Mar 2026`, in four currencies. About one in ten invoices has a printed total that doesn't match its own arithmetic, the kind of mistake validation should catch.

There are two sets:

- `examples/known`: 40 invoices in four layouts: a header block, an email, a Markdown table, and a compact receipt. The regex baseline was written for these.
- `examples/holdout`: 24 invoices in three layouts the baseline has never seen: a letter, a dotted-leader statement, and key=value lines.

The regex baseline on each, measured offline:

```
$ uv run docextract eval examples/known --offline
40 invoices. All fields right: 40/40 (100%)
Validation caught 7 of 7 invoices with a real arithmetic error, and flagged 0 clean ones.

$ uv run docextract eval examples/holdout --offline
24 invoices. All fields right: 0/24 (0%)
```

That gap is the real argument for a model. Rules are perfect on the templates they were written for and fall apart on the next vendor's format. Validation still does its job on the holdout set: nearly every bad extraction fails the arithmetic checks and is routed to review instead of being booked.

## Extract with Claude

```bash
uv sync --extra claude
export ANTHROPIC_API_KEY=...   # or use a saved `ant auth login` profile
uv run docextract extract examples/holdout/invoices/invoice-001.txt
uv run docextract eval examples/holdout
```

`extract` prints the JSON, then either "All checks passed" or the list of problems, and exits 1 when the invoice needs review. `eval` runs four documents at a time and prints per-field accuracy, results by layout, and how well validation routed the invoices with real errors.

The request uses `output_config.format` with the JSON Schema in `schema.py`, so the reply always parses. The prompt tells the model to copy values exactly as printed and not to fix arithmetic, because silently "correcting" a wrong total would hide the error that validation is there to catch. Requests run at low effort by default, which suits a short, well-specified task. Refusals and cut-off replies raise a clear error instead of returning partial data.

## Layout

```
src/docextract/schema.py    dataclasses and the JSON Schema sent to the model
src/docextract/claude.py    the Claude call with structured outputs
src/docextract/baseline.py  regex extractor, the offline baseline
src/docextract/validate.py  business-rule checks
src/docextract/evaluate.py  per-field scoring and the report
src/docextract/data.py      synthetic invoice generator
```

## Tests

```bash
uv run --group dev pytest
```

26 tests, none of which call the API. They check that generation is reproducible and matches the bundled examples, each validation rule, number and date parsing, the baseline's 100% and 0% results, the scoring rules, the request shape and error handling with a fake client, and the CLI.

## License

MIT. See [LICENSE](LICENSE).

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docextract import baseline, cli
from docextract.claude import SYSTEM, ExtractionError, extract
from docextract.data import HOLDOUT, KNOWN, generate, money, fmt_date
from docextract.evaluate import Report, field_correct, load_truth
from docextract.schema import FIELDS, JSON_SCHEMA, Invoice, LineItem
from docextract.validate import check

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def good_invoice(**changes):
    inv = Invoice("Acme", "INV-1", "2026-03-01", "2026-03-31", "USD", "Buyer Co", None,
                  [LineItem("Widget", 2, 10.0, 20.0), LineItem("Gadget", 1, 5.5, 5.5)], 25.5, 2.1, 27.6)
    for k, v in changes.items():
        setattr(inv, k, v)
    return inv


# Data ------------------------------------------------------------------------

def test_generation_is_deterministic(tmp_path):
    a, b = generate(tmp_path / "a"), generate(tmp_path / "b")
    assert (a / "truth.jsonl").read_text() == (b / "truth.jsonl").read_text()
    assert (a / "invoices" / "invoice-007.txt").read_text() == (b / "invoices" / "invoice-007.txt").read_text()


def test_bundled_examples_match_the_generator(tmp_path):
    generate(tmp_path / "known")
    assert (tmp_path / "known" / "truth.jsonl").read_text() == (EXAMPLES / "known" / "truth.jsonl").read_text()


def test_holdout_uses_only_unseen_layouts():
    layouts = {c.layout for c in load_truth(EXAMPLES / "holdout")}
    assert layouts == set(HOLDOUT) and not layouts & set(KNOWN)


def test_formats():
    assert money(1234.5, "us") == "1,234.50"
    assert money(1234.5, "eu") == "1.234,50"
    from datetime import date

    d = date(2026, 3, 4)
    assert [fmt_date(d, s) for s in ("iso", "us", "eu", "long", "short")] == ["2026-03-04", "03/04/2026", "04.03.2026", "March 4, 2026", "4 Mar 2026"]


# Validation --------------------------------------------------------------------

def test_clean_invoice_passes():
    assert check(good_invoice()) == []


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"total": 37.6}, "subtotal plus tax is 27.60, but the total is 37.60"),
        ({"subtotal": 30.0, "total": 32.1}, "line items add up to 25.50"),
        ({"line_items": [LineItem("Widget", 2, 10.0, 21.0)], "subtotal": 21.0, "total": 23.1}, "line 1: 2 x 10.00 is 20.00, not 21.00"),
        ({"due_date": "2026-02-01"}, "due date is before"),
        ({"invoice_date": "03/01/2026"}, "YYYY-MM-DD"),
        ({"tax": 20.0, "total": 45.5}, "outside the expected range"),
        ({"line_items": [], "subtotal": 0.0, "tax": 0.0, "total": 0.0}, "no line items"),
    ],
)
def test_validation_catches_problems(changes, expected):
    problems = check(good_invoice(**changes))
    assert any(expected in p for p in problems), problems


# Baseline --------------------------------------------------------------------

def test_baseline_number_and_date_parsing():
    assert baseline.parse_number("1.234,50") == 1234.5
    assert baseline.parse_number("$1,234.50") == 1234.5
    assert baseline.parse_number("€9,99") == 9.99
    assert baseline.parse_date("31.05.2026") == "2026-05-31"
    assert baseline.parse_date("May 3, 2026") == "2026-05-03"
    assert baseline.parse_date("3 May 2026") == "2026-05-03"
    assert baseline.parse_date("soon") is None


def score(folder):
    r = Report()
    for c in load_truth(folder):
        r.add(c, baseline.extract((Path(folder) / "invoices" / c.file).read_text()))
    return r


def test_baseline_is_perfect_on_the_layouts_it_was_written_for():
    r = score(EXAMPLES / "known")
    assert r.exact == r.n == 40
    assert r.flagged_errors == r.real_errors and r.false_flags == 0


def test_baseline_fails_on_new_layouts_and_validation_notices():
    r = score(EXAMPLES / "holdout")
    assert r.exact == 0
    # Bad extractions fail the arithmetic checks, so they go to review instead of the ledger.
    assert r.flagged_errors + r.false_flags >= r.n - 2


# Scoring -----------------------------------------------------------------------

def test_field_comparison_is_forgiving_where_it_should_be():
    want = good_invoice()
    assert field_correct("vendor_name", good_invoice(vendor_name="ACME."), want)
    assert field_correct("invoice_number", good_invoice(invoice_number="#inv-1"), want)
    assert field_correct("total", good_invoice(total=27.601), want)
    assert not field_correct("total", good_invoice(total=27.62), want)
    assert not field_correct("line_items", good_invoice(line_items=want.line_items[:1]), want)
    assert not field_correct("due_date", good_invoice(due_date=None), want)


def test_report_counts_failures_and_text():
    case = load_truth(EXAMPLES / "known")[0]
    r = Report()
    r.add(case, case.truth)
    r.add(case, None)
    assert (r.n, r.exact, r.failures) == (2, 1, [case.file])
    assert "All fields right: 1/2 (50%)" in r.as_text()


# Claude path, with a fake client ------------------------------------------------

def fake_client(payload=None, stop="end_turn", text=None):
    calls = []

    def create(**kw):
        calls.append(kw)
        body = text if text is not None else json.dumps(payload)
        return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=body)], usage=SimpleNamespace(input_tokens=900, output_tokens=200))

    return SimpleNamespace(messages=SimpleNamespace(create=create)), calls


def test_claude_request_uses_structured_outputs():
    truth = load_truth(EXAMPLES / "holdout")[0].truth
    client, calls = fake_client(truth.to_dict())
    inv, usage = extract("some invoice text", client=client)
    assert inv == truth and usage == {"input_tokens": 900, "output_tokens": 200}
    req = calls[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": JSON_SCHEMA}}
    assert req["system"] == SYSTEM
    assert req["messages"][0]["content"].startswith("<document>")


def test_schema_requires_every_field_and_allows_null_where_optional():
    assert set(JSON_SCHEMA["required"]) == set(FIELDS)
    assert JSON_SCHEMA["additionalProperties"] is False
    assert "null" in JSON_SCHEMA["properties"]["due_date"]["type"]
    assert "null" not in str(JSON_SCHEMA["properties"]["total"])


@pytest.mark.parametrize("stop, text, match", [("refusal", "", "declined"), ("max_tokens", "{", "cut off"), ("end_turn", "not json", "valid JSON")])
def test_claude_failures_raise_clear_errors(stop, text, match):
    client, _ = fake_client(stop=stop, text=text)
    with pytest.raises(ExtractionError, match=match):
        extract("x", client=client)


# CLI -----------------------------------------------------------------------------

def test_cli_extract_offline_validates(capsys):
    clean = next(c for c in load_truth(EXAMPLES / "known") if not c.has_error)
    assert cli.main(["extract", str(EXAMPLES / "known" / "invoices" / clean.file), "--offline"]) == 0
    out, err = capsys.readouterr()
    assert json.loads(out.split("\n\n")[0])["invoice_number"] == clean.truth.invoice_number
    assert "All checks passed" in err
    broken = next(c for c in load_truth(EXAMPLES / "known") if c.has_error)
    assert cli.main(["extract", str(EXAMPLES / "known" / "invoices" / broken.file), "--offline"]) == 1
    assert "Needs review" in capsys.readouterr().err


def test_cli_eval_offline(capsys):
    assert cli.main(["eval", str(EXAMPLES / "known"), "--offline"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Regex baseline on") and "All fields right: 40/40 (100%)" in out


def test_cli_eval_with_a_fake_model(capsys, monkeypatch):
    truth = {c.file: c.truth for c in load_truth(EXAMPLES / "holdout")}
    texts = {(EXAMPLES / "holdout" / "invoices" / f).read_text(): inv for f, inv in truth.items()}
    monkeypatch.setattr(cli, "extractor", lambda args: lambda text: texts[text])
    assert cli.main(["eval", str(EXAMPLES / "holdout")]) == 0
    assert "All fields right: 24/24 (100%)" in capsys.readouterr().out


def test_cli_generate(tmp_path, capsys):
    assert cli.main(["generate", "--out", str(tmp_path)]) == 0
    assert len(list((tmp_path / "holdout" / "invoices").iterdir())) == 24

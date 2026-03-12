from pathlib import Path
from types import SimpleNamespace
import sys

import pymupdf as fitz

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pdf_redactor as pr


def make_args(**overrides):
    defaults = {
        "color": "black",
        "color_hex": None,
        "text": None,
        "text_color": "white",
        "text_color_hex": None,
        "preview": False,
        "geographic_code": None,
        "mask": None,
        "phonenumber": False,
        "link": False,
        "email": False,
        "iban": False,
        "bic": False,
        "timestamp": False,
        "date": False,
        "barcode": False,
        "qrcode": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)

def test_find_timestamp_returns_full_matches():
    hits = pr.find_timestamp(["Start 12:34 and end 9:05."])
    assert hits == {0: ["12:34", "9:05"]}


def test_find_bics_matches_eight_and_eleven_character_codes():
    hits = pr.find_bics(["Codes: DEUTDEFF and DEUTDEFF500"])
    assert hits == {0: ["DEUTDEFF", "DEUTDEFF500"]}


def test_find_custom_mask_escapes_regex_characters():
    hits = pr.find_custom_mask(["C++ is allowed. C+ is not."], ["C++"])
    assert hits == {0: ["C++"]}

def test_default_output_path_stays_next_to_input():
    assert pr.default_output_path("/tmp/example/input.pdf") == "/tmp/example/input_redacted.pdf"


def test_resolve_single_file_output_path_accepts_directory():
    output = pr.resolve_single_file_output_path("/tmp/example/input.pdf", "/tmp/redacted")
    assert output == "/tmp/redacted/input_redacted.pdf"


def test_validate_output_flag_accepts_directory_for_single_file(tmp_path):
    args = make_args(output=str(tmp_path / "redacted"))
    pr.validate_output_flag(args, input_is_dir=False)
    assert (tmp_path / "redacted").is_dir()


def test_apply_redaction_batch_deduplicates_rects_and_applies_once():
    args = make_args()
    rect = fitz.Rect(10, 10, 50, 30)

    class FakePage:
        def __init__(self):
            self.annot_calls = 0
            self.apply_calls = 0

        def add_redact_annot(self, **kwargs):
            self.annot_calls += 1
            return object()

        def apply_redactions(self, **kwargs):
            self.apply_calls += 1

    page = FakePage()
    pr.apply_redaction_batch(
        page,
        [rect, fitz.Rect(rect)],
        args,
    )

    assert page.annot_calls == 1
    assert page.apply_calls == 1


def test_find_codes_returns_empty_when_pyzbar_is_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(pr, "decode", None)
    monkeypatch.setattr(pr, "PYZBAR_IMPORT_ERROR", ImportError("Unable to find zbar shared library"))

    document = fitz.open()
    document.new_page(width=120, height=120)

    rects = pr.find_qrcode(document)
    output = capsys.readouterr().out

    assert rects == {}
    assert "Unable to find zbar shared library" in output
    assert "disabled" in output

from pathlib import Path
from types import SimpleNamespace
import sys

import pymupdf as fitz
import pytest

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
        "sanitize": False,
        "document_metadata": False,
        "embedded_files": False,
        "annotations": False,
        "form_fields": False,
        "quiet": False,
        "show_matches": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_validate_redaction_targets_rejects_empty_selection():
    with pytest.raises(ValueError, match="Select at least one redaction target"):
        pr.validate_redaction_targets(make_args())


def test_validate_redaction_targets_accepts_selected_detector():
    pr.validate_redaction_targets(make_args(email=True))


def test_validate_redaction_targets_accepts_internal_cleanup_target():
    pr.validate_redaction_targets(make_args(document_metadata=True))


def test_scrub_additional_pdf_internals_uses_expected_sanitize_options():
    class FakeDocument:
        def __init__(self):
            self.scrub_options = None

        def scrub(self, **kwargs):
            self.scrub_options = kwargs

    document = FakeDocument()

    assert pr.scrub_additional_pdf_internals(document, make_args(sanitize=True, quiet=True)) is True
    assert document.scrub_options == pr.SANITIZE_SCRUB_OPTIONS


def test_scrub_additional_pdf_internals_only_runs_for_sanitize():
    class FakeDocument:
        def scrub(self, **kwargs):
            raise AssertionError("scrub should only run for --sanitize")

    assert pr.scrub_additional_pdf_internals(FakeDocument(), make_args(document_metadata=True)) is False


def test_default_detector_output_hides_sensitive_values(capsys):
    pr.find_email_addresses(["Contact jane.doe@example.com."], make_args())
    output = capsys.readouterr().out

    assert "Found 1 Email Address on Page 1" in output
    assert "jane.doe@example.com" not in output


def test_show_matches_reveals_detected_values(capsys):
    pr.find_email_addresses(["Contact jane.doe@example.com."], make_args(show_matches=True))
    output = capsys.readouterr().out

    assert "jane.doe@example.com" in output


def test_quiet_suppresses_detector_output(capsys):
    pr.find_timestamp(["Start 12:34."], make_args(quiet=True))
    output = capsys.readouterr().out

    assert output == ""


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


def test_save_redactions_removes_cleared_document_metadata(tmp_path):
    output = tmp_path / "metadata_redacted.pdf"
    doc = fitz.open()
    doc.new_page(width=120, height=120)
    doc.set_metadata(
        {
            "title": "Secret title",
            "author": "Secret author",
            "subject": "Secret subject",
            "keywords": "secret,pii",
            "creator": "Secret app",
            "producer": "Secret producer",
        }
    )
    doc.set_xml_metadata(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>'
        "</x:xmpmeta>"
    )

    removed = pr.redact_document_metadata(doc, make_args(quiet=True))
    pr.save_redactions(doc, output, make_args(quiet=True))
    doc.close()

    redacted = fitz.open(output)
    assert removed == 7
    assert redacted.get_xml_metadata() == ""
    assert redacted.metadata["title"] == ""
    assert redacted.metadata["author"] == ""
    assert redacted.metadata["subject"] == ""
    assert redacted.metadata["keywords"] == ""
    assert redacted.metadata["creator"] == ""
    assert redacted.metadata["producer"] == ""


def test_remove_embedded_files_removes_all_files_after_save(tmp_path):
    output = tmp_path / "embedded_files_redacted.pdf"
    doc = fitz.open()
    doc.new_page(width=120, height=120)
    doc.embfile_add("secret.txt", b"hidden payload", filename="secret.txt")

    removed = pr.remove_embedded_files(doc, make_args(quiet=True))
    pr.save_redactions(doc, output, make_args(quiet=True))
    doc.close()

    redacted = fitz.open(output)
    assert removed == 1
    assert redacted.embfile_count() == 0


def test_remove_annotations_and_comments_removes_page_annotations_after_save(tmp_path):
    input_path = tmp_path / "annotations.pdf"
    output = tmp_path / "annotations_redacted.pdf"
    doc = fitz.open()
    page = doc.new_page(width=120, height=120)
    page.add_text_annot((40, 40), "private comment")
    doc.save(input_path)
    doc.close()

    doc = fitz.open(input_path)
    removed = pr.remove_annotations_and_comments(doc, make_args(quiet=True))
    pr.save_redactions(doc, output, make_args(quiet=True))
    doc.close()

    redacted = fitz.open(output)
    assert removed == 1
    assert redacted[0].first_annot is None


def test_remove_form_fields_removes_widgets_after_save(tmp_path):
    output = tmp_path / "form_fields_redacted.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=120)
    widget = fitz.Widget()
    widget.field_name = "secret_name"
    widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    widget.field_value = "Alice"
    widget.rect = fitz.Rect(40, 40, 180, 70)
    page.add_widget(widget)

    removed = pr.remove_form_fields(doc, make_args(quiet=True))
    pr.save_redactions(doc, output, make_args(quiet=True))
    doc.close()

    redacted = fitz.open(output)
    assert removed == 1
    assert redacted.is_form_pdf == 0
    assert list(redacted[0].widgets()) == []


def test_sanitize_applies_existing_redaction_annotations(tmp_path):
    input_path = tmp_path / "pending_redaction.pdf"
    output = tmp_path / "pending_redaction_sanitized.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=120)
    page.insert_text((40, 40), "Secret visible text")
    for rect in page.search_for("Secret"):
        page.add_redact_annot(rect, fill=fitz.pdfcolor["black"])
    doc.save(input_path)
    doc.close()

    doc = fitz.open(input_path)
    pr.redact_pdf_internals(doc, make_args(sanitize=True, quiet=True))
    pr.save_redactions(doc, output, make_args(quiet=True))
    doc.close()

    redacted = fitz.open(output)
    assert "Secret" not in redacted[0].get_text("text")
    assert redacted[0].first_annot is None


def test_sanitize_preserves_links_without_link_redaction_flag(tmp_path):
    input_path = tmp_path / "linked.pdf"
    output = tmp_path / "linked_sanitized.pdf"
    doc = fitz.open()
    page = doc.new_page(width=240, height=120)
    page.insert_text((40, 40), "Visible link")
    page.insert_link(
        {
            "kind": fitz.LINK_URI,
            "from": fitz.Rect(40, 25, 120, 50),
            "uri": "https://example.com",
        }
    )
    doc.save(input_path)
    doc.close()

    doc = fitz.open(input_path)
    pr.redact_pdf_internals(doc, make_args(sanitize=True, quiet=True))
    pr.save_redactions(doc, output, make_args(quiet=True))
    doc.close()

    redacted = fitz.open(output)
    assert redacted[0].get_links()[0]["uri"] == "https://example.com"
    assert "Visible link" in redacted[0].get_text("text")


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


def test_run_redaction_applies_combined_page_rects_once(monkeypatch):
    args = make_args(email=True, qrcode=True, quiet=True)
    text_rect = fitz.Rect(10, 10, 50, 30)
    code_rect = fitz.Rect(60, 60, 90, 90)

    class FakePage:
        def __init__(self):
            self.annot_calls = 0
            self.apply_calls = 0

        def add_redact_annot(self, **kwargs):
            self.annot_calls += 1
            return object()

        def apply_redactions(self, **kwargs):
            self.apply_calls += 1

    class FakeDocument:
        def __init__(self):
            self.page = FakePage()

        def __len__(self):
            return 1

        def load_page(self, page_num):
            return self.page

    document = FakeDocument()
    monkeypatch.setattr(pr, "find_email_addresses", lambda text_pages, args=None: {0: ["a@example.com"]})
    monkeypatch.setattr(pr, "locate_matches", lambda pdf_document, matches_by_page: {0: [text_rect]})
    monkeypatch.setattr(pr, "find_qrcode", lambda pdf_document, args=None: {0: [code_rect]})

    pr.run_redaction("input.pdf", document, ["a@example.com"], args)

    assert document.page.annot_calls == 2
    assert document.page.apply_calls == 1


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

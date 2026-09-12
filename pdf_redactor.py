#!/usr/bin/env python3

import argparse
import os
import re
import sys
from collections import defaultdict

import cv2
import numpy as np
import phonenumbers
import pymupdf as fitz
from PIL import Image
from tqdm import tqdm

try:
    from pyzbar.pyzbar import decode
    PYZBAR_IMPORT_ERROR = None
except ImportError as exc:
    decode = None
    PYZBAR_IMPORT_ERROR = exc


# define colors
WHITE = fitz.pdfcolor["white"]
BLACK = fitz.pdfcolor["black"]
RED = fitz.pdfcolor["red"]
GREEN = fitz.pdfcolor["green"]
BLUE = fitz.pdfcolor["blue"]

# Dictionary to map input strings to predefined color variables
COLOR_MAP = {
    "white": WHITE,
    "black": BLACK,
    "red": RED,
    "green": GREEN,
    "blue": BLUE,
}

CONTENT_REDACTION_TARGET_FLAGS = (
    "phonenumber",
    "link",
    "email",
    "mask",
    "iban",
    "bic",
    "timestamp",
    "date",
    "barcode",
    "qrcode",
)

INTERNAL_REDACTION_TARGET_FLAGS = (
    "sanitize",
    "document_metadata",
    "embedded_files",
    "annotations",
    "form_fields",
)

REDACTION_TARGET_FLAGS = CONTENT_REDACTION_TARGET_FLAGS + INTERNAL_REDACTION_TARGET_FLAGS


### HELPER FUNCTIONS


def print_logo():
    print(
        r"""
_____  _____  ______ _____          _            _
|  __ \|  __ \|  ____|  __ \        | |          | |
| |__) | |  | | |__  | |__) |___  __| | __ _  ___| |_ ___  _ __
|  ___/| |  | |  __| |  _  // _ \/ _` |/ _` |/ __| __/ _ \| '__|
| |    | |__| | |    | | \ \  __/ (_| | (_| | (__| || (_) | |
|_|    |_____/|_|    |_|  \_\___|\__,_|\__,_|\___|\__\___/|_|
                                    PDFRedactor
                                                @ltillmann
        """
    )


def save_redactions(pdf_document, output_path, args=None):
    log(args, f"\n[i] Saving changes to '{output_path}'")
    pdf_document.save(
        output_path,
        garbage=4,
        clean=True,
        deflate=True,
        deflate_images=True,
        deflate_fonts=True,
        no_new_id=False,
        preserve_metadata=False,
    )


def is_quiet(args):
    return bool(getattr(args, "quiet", False))


def show_matches(args):
    return bool(getattr(args, "show_matches", False)) and not is_quiet(args)


def log(args, message=""):
    if not is_quiet(args):
        print(message)


def format_match_values(matches, args):
    if not show_matches(args) or not matches:
        return ""
    return f": {', '.join(str(match) for match in matches)}"


def print_page_match_summary(args, count, singular, plural, page_num, matches=None):
    if is_quiet(args):
        return
    print(
        f" |  Found {count} {singular if count == 1 else plural} "
        f"on Page {page_num + 1}{format_match_values(matches, args)}"
    )


def selected_redaction_targets(args):
    return [flag for flag in REDACTION_TARGET_FLAGS if getattr(args, flag, None)]


def selected_content_redaction_targets(args):
    return [flag for flag in CONTENT_REDACTION_TARGET_FLAGS if getattr(args, flag, None)]


def validate_redaction_targets(args, parser=None):
    if selected_redaction_targets(args):
        return

    message = (
        "Select at least one redaction target "
        "(-e, -l, -p, -m, -d, -f, -s, -b, -r, -q, --sanitize, "
        "--document-metadata, --embedded-files, --annotations, or --form-fields)."
    )
    if parser:
        parser.error(message)
    raise ValueError(message)


def validate_input_path(file_path):
    if not os.path.exists(file_path):
        print(f"[Error] No such Path/File: {file_path}\nPlease specify path or make sure file exists.")
        sys.exit(1)

    if os.path.isdir(file_path):
        return True

    if os.path.isfile(file_path) and file_path.lower().endswith(".pdf"):
        return False

    print(f"[Error] File '{file_path}' is not a PDF file.")
    sys.exit(1)


def load_pdf(file_path):
    return fitz.open(file_path)


def extract_text_pages(pdf_document):
    text_pages = []
    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        text_pages.append(page.get_text("text"))
    return text_pages


def validate_output_flag(args, input_is_dir):
    if not args.output:
        return

    if input_is_dir:
        if args.output.lower().endswith(".pdf"):
            raise ValueError(
                f"Output must be a directory when processing multiple PDFs. Given: {args.output}"
            )
        os.makedirs(args.output, exist_ok=True)
        return

    if args.output.lower().endswith(".pdf"):
        output_dir = os.path.dirname(os.path.abspath(args.output))
        os.makedirs(output_dir, exist_ok=True)
        return

    if os.path.exists(args.output) and not os.path.isdir(args.output):
        raise ValueError(
            f"Output must be a '.pdf' file or a directory when processing a single PDF. Given: {args.output}"
        )

    os.makedirs(args.output, exist_ok=True)


def default_output_path(input_path):
    stem, ext = os.path.splitext(input_path)
    return f"{stem}_redacted{ext}"


def resolve_single_file_output_path(input_path, output_path):
    if not output_path:
        return default_output_path(input_path)
    if output_path.lower().endswith(".pdf"):
        return output_path
    return os.path.join(output_path, os.path.basename(default_output_path(input_path)))


def hex_to_rgb(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(char + char for char in value)
    if len(value) != 6:
        raise ValueError("Invalid hex color.")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))


def get_redaction_colors(args):
    fill_color = hex_to_rgb(args.color_hex) if args.color_hex else COLOR_MAP[args.color]
    text_fill_color = (
        hex_to_rgb(args.text_color_hex) if args.text_color_hex else COLOR_MAP[args.text_color]
    )
    return fill_color, text_fill_color


def dedupe_rects(rects):
    unique_rects = []
    seen = set()
    for rect in rects:
        key = tuple(round(value, 3) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
        if key not in seen:
            seen.add(key)
            unique_rects.append(rect)
    return unique_rects


def merge_rect_maps(target, source):
    for page_num, rects in source.items():
        target[page_num].extend(rects)


def locate_matches(pdf_document, matches_by_page):
    rects_by_page = defaultdict(list)
    for page_num, matches in matches_by_page.items():
        if not matches:
            continue
        page = pdf_document.load_page(page_num)
        for match in dict.fromkeys(matches):
            rects_by_page[page_num].extend(page.search_for(match))
    return rects_by_page


def preview_redactions(page, annots):
    zoom = 3
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, annots=True, colorspace=fitz.csRGB)
    img = np.frombuffer(buffer=pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, -1).copy()

    window = "Redaction Preview"
    cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
    cv2.imshow(window, img)
    cv2.waitKey(1)

    while True:
        user_input = input("[?] Continue with redaction? (Y/n): ").strip().lower()
        if user_input in ("", "y"):
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            cv2.destroyWindow(window)
            return
        if user_input == "n":
            print(" |  Redaction aborted.")
            for annot in annots:
                page.delete_annot(annot)
            cv2.destroyWindow(window)
            return
        print("[Error] Invalid input. Please enter 'Y' to continue or 'n' to abort.")


def apply_redaction_batch(page, rects, args):
    unique_rects = dedupe_rects(rects)
    if not unique_rects:
        return

    fill_color, text_fill_color = get_redaction_colors(args)
    annots = []
    for rect in unique_rects:
        annots.append(
            page.add_redact_annot(
                quad=rect,
                text=args.text,
                text_color=text_fill_color,
                fill=fill_color,
                cross_out=True,
            )
        )

    if args.preview:
        preview_redactions(page, annots)
    else:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)


def get_zbar_install_hint():
    if sys.platform == "darwin":
        return "Install the zbar shared library, for example with: brew install zbar"
    if sys.platform.startswith("linux"):
        return "Install the zbar shared library from your system package manager."
    return "Install the zbar shared library required by pyzbar."


### PDF INTERNALS
DOCUMENT_METADATA_KEYS = (
    "title",
    "author",
    "subject",
    "keywords",
    "creator",
    "producer",
    "creationDate",
    "modDate",
    "trapped",
)

SANITIZE_SCRUB_OPTIONS = {
    "metadata": False,
    "xml_metadata": False,
    "embedded_files": False,
    "attached_files": True,
    "javascript": True,
    "thumbnails": True,
    "hidden_text": True,
    "redactions": True,
    "clean_pages": True,
    "remove_links": False,
    "reset_fields": False,
    "reset_responses": True,
}


def should_redact_internal(args, flag):
    return bool(getattr(args, "sanitize", False) or getattr(args, flag, False))


def scrub_additional_pdf_internals(pdf_document, args=None):
    if not getattr(args, "sanitize", False):
        return False

    log(args, "\n[i] Running extended PDF sanitization...")
    pdf_document.scrub(**SANITIZE_SCRUB_OPTIONS)
    log(args, " |  Removed hidden text, JavaScript, thumbnails, attached files, and pending redactions where present")
    return True


def redact_document_metadata(pdf_document, args=None):
    log(args, "\n[i] Removing document metadata...")
    metadata = pdf_document.metadata or {}
    removed_count = sum(1 for key in DOCUMENT_METADATA_KEYS if metadata.get(key))
    if pdf_document.get_xml_metadata():
        removed_count += 1

    pdf_document.set_metadata({})
    pdf_document.del_xml_metadata()

    log(
        args,
        f" |  Removed {removed_count} document metadata "
        f"{'entry' if removed_count == 1 else 'entries'}",
    )
    return removed_count


def remove_embedded_files(pdf_document, args=None):
    log(args, "\n[i] Removing embedded files...")
    names = list(pdf_document.embfile_names())
    for name in names:
        pdf_document.embfile_del(name)

    log(
        args,
        f" |  Removed {len(names)} embedded "
        f"{'file' if len(names) == 1 else 'files'}{format_match_values(names, args)}",
    )
    return len(names)


def remove_annotations_and_comments(pdf_document, args=None):
    log(args, "\n[i] Removing annotations and comments...")
    total_removed = 0

    for page_num in tqdm(
        range(len(pdf_document)),
        desc="[i] Scanning Pages",
        unit="page",
        disable=is_quiet(args),
    ):
        page = pdf_document.load_page(page_num)
        page_removed = 0
        annotation_types = []
        for annot in list(page.annots() or []):
            annotation_types.append(annot.type[1])
            page_removed += 1
            total_removed += 1
            page.delete_annot(annot)

        print_page_match_summary(
            args,
            page_removed,
            "Annotation/Comment",
            "Annotations/Comments",
            page_num,
            annotation_types,
        )

    return total_removed


def remove_form_fields(pdf_document, args=None):
    log(args, "\n[i] Removing form fields...")
    total_removed = 0

    for page_num in tqdm(
        range(len(pdf_document)),
        desc="[i] Scanning Pages",
        unit="page",
        disable=is_quiet(args),
    ):
        page = pdf_document.load_page(page_num)
        page_removed = 0
        field_names = []
        widget = page.first_widget
        while widget:
            field_names.append(widget.field_name or "unnamed field")
            page_removed += 1
            total_removed += 1
            widget = page.delete_widget(widget)

        print_page_match_summary(args, page_removed, "Form Field", "Form Fields", page_num, field_names)

    return total_removed


def redact_pdf_internals(pdf_document, args):
    scrub_additional_pdf_internals(pdf_document, args)

    if should_redact_internal(args, "document_metadata"):
        redact_document_metadata(pdf_document, args)

    if should_redact_internal(args, "embedded_files"):
        remove_embedded_files(pdf_document, args)

    if should_redact_internal(args, "annotations"):
        remove_annotations_and_comments(pdf_document, args)

    if should_redact_internal(args, "form_fields"):
        remove_form_fields(pdf_document, args)


### PHONE NUMBERS
def find_phone_numbers(text_pages, args=None):
    log(args, "\n[i] Searching for Phone Numbers...")
    all_phone_numbers = {}
    region_code = args.geographic_code if args and args.geographic_code else None
    for i, text_page in enumerate(text_pages):
        page_phone_numbers = [match.raw_string for match in phonenumbers.PhoneNumberMatcher(text_page, region_code)]
        all_phone_numbers[i] = page_phone_numbers
        print_page_match_summary(
            args,
            len(page_phone_numbers),
            "Phone Number",
            "Phone Numbers",
            i,
            page_phone_numbers,
        )
    return all_phone_numbers


### LINKS
def describe_link(link):
    if link.get("uri"):
        return link["uri"]
    if link.get("file"):
        return link["file"]
    if "page" in link:
        return f"page {link['page'] + 1}"
    return "internal link"


def find_link_rects(pdf_document, args=None):
    log(args, "\n[i] Searching for Links...")
    rects_by_page = defaultdict(list)

    for page_num in tqdm(
        range(len(pdf_document)),
        desc="[i] Scanning Pages",
        unit="page",
        disable=is_quiet(args),
    ):
        page = pdf_document.load_page(page_num)
        link_list = page.get_links()
        descriptions = ", ".join(describe_link(link) for link in link_list)
        print_page_match_summary(
            args,
            len(link_list),
            "Link",
            "Links",
            page_num,
            [descriptions] if descriptions else [],
        )
        rects_by_page[page_num].extend(link["from"] for link in link_list if "from" in link)

    return rects_by_page


### EMAIL ADDRESSES
def find_email_addresses(text_pages, args=None):
    log(args, "\n[i] Searching for Email Addresses...")
    all_email_addresses = {}
    extract_email_pattern = r"\S+@\S+\.\S+"
    for i, page in enumerate(text_pages):
        match = re.findall(extract_email_pattern, page)
        all_email_addresses[i] = match
        print_page_match_summary(args, len(match), "Email Address", "Email Addresses", i, match)
    return all_email_addresses


### CUSTOM SEARCH MASK
def build_custom_mask_pattern(mask):
    prefix = r"\b" if mask and re.match(r"\w", mask[0]) else ""
    suffix = r"\b" if mask and re.match(r"\w", mask[-1]) else ""
    return re.compile(f"{prefix}{re.escape(mask)}{suffix}", flags=re.IGNORECASE)


def find_custom_mask(text_pages, custom_masks, args=None):
    log(args, "\n[i] Searching for Custom Mask matches...")
    all_hits = {page_num: [] for page_num in range(len(text_pages))}

    for mask_index, mask in enumerate(custom_masks, start=1):
        if show_matches(args):
            log(args, f"\n[i] Searching for mask: '{mask}'")
        else:
            log(args, f"\n[i] Searching for custom mask {mask_index}/{len(custom_masks)}")
        pattern = build_custom_mask_pattern(mask)
        for page_num, page_text in enumerate(text_pages):
            matches = pattern.findall(page_text)
            all_hits[page_num].extend(matches)
            if matches:
                print_page_match_summary(args, len(matches), "match", "matches", page_num, matches)

    total_matches = sum(len(matches) for matches in all_hits.values())
    log(args, f"\n[i] Total mask matches found: {total_matches}")
    return all_hits


### IBAN
def find_ibans(text_pages, args=None):
    log(args, "\n[i] Searching for IBANs...")
    hits = {}
    match_pattern = r"\b[A-Z]{2}[0-9]{2}(?:[ ]?[0-9]{4}){4}(?!(?:[ ]?[0-9]){3})(?:[ ]?[0-9]{1,2})?\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page, flags=re.IGNORECASE)
        hits[i] = match
        print_page_match_summary(args, len(match), "IBAN", "IBANs", i, match)
    return hits


### BIC
def find_bics(text_pages, args=None):
    log(args, "\n[i] Searching for BICs...")
    hits = {}
    match_pattern = r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page, flags=re.IGNORECASE)
        hits[i] = match
        print_page_match_summary(args, len(match), "BIC", "BICs", i, match)
    return hits


### TIME
def find_timestamp(text_pages, args=None):
    log(args, "\n[i] Searching for Timestamps...")
    hits = {}
    match_pattern = r"\b(?:[0-1]?[0-9]|2[0-3]):[0-5][0-9]\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page)
        hits[i] = match
        print_page_match_summary(args, len(match), "Timestamp", "Timestamps", i, match)
    return hits


### DATE
def find_date(text_pages, args=None):
    log(args, "\n[i] Searching for Dates...")
    hits = {}
    match_pattern = (
        r"((?:[0]?[1-9]|[12][0-9]|3[01])(?:.?)(?:[./-]|[' '])"
        r"(?:0?[1-9]|1[0-2]|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|"
        r"Jan(?:uar)?|Feb(?:uar)?|Mär(?:z)?|Apr(?:il)?|Mai|Jun(?:i)?|Jul(?:i)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Okt(?:ober)?|Nov(?:ember)?|Dez(?:ember)?)(?:[./-]|[' '])(?:[0-9]{4}|[0-9]{2}))"
    )

    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page)
        hits[i] = match
        print_page_match_summary(args, len(match), "Date", "Dates", i, match)
    return hits


### BAR/QRCODES
def find_codes(pdf_document, code_type=None, args=None):
    print_type = "Barcodes" if code_type == "barcode" else "QR Codes"
    log(args, f"\n[i] Searching for {print_type}...")

    rects_by_page = defaultdict(list)

    if decode is None:
        print(f"[Warning] {PYZBAR_IMPORT_ERROR}. {print_type} detection disabled.")
        print(f"[Hint] {get_zbar_install_hint()}")
        return rects_by_page

    for page_num in tqdm(
        range(len(pdf_document)),
        desc="[i] Scanning Pages",
        unit="page",
        disable=is_quiet(args),
    ):
        page = pdf_document.load_page(page_num)
        zoom = 3
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB)
        pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        counter = 0
        for bar in decode(pil_img):
            if code_type == "barcode" and bar.type.startswith("QRCODE"):
                continue
            if code_type == "qrcode" and not bar.type.startswith("QRCODE"):
                continue

            counter += 1
            rect = bar.rect
            bbox = fitz.Rect(
                rect.left / zoom,
                rect.top / zoom,
                (rect.left + rect.width) / zoom,
                (rect.top + rect.height) / zoom,
            )
            rects_by_page[page_num].append(bbox)

        singular = "Barcode" if code_type == "barcode" else "QR Code"
        print_page_match_summary(args, counter, singular, print_type, page_num)

    return rects_by_page


def find_qrcode(pdf_document, args=None):
    return find_codes(pdf_document, code_type="qrcode", args=args)


def find_barcode(pdf_document, args=None):
    return find_codes(pdf_document, code_type="barcode", args=args)


def run_redaction(file_path, pdf_document, text_pages, args):
    log(args, f"[i] Analysing file '{file_path}'\n")

    rects_by_page = defaultdict(list)

    if args.phonenumber:
        merge_rect_maps(rects_by_page, locate_matches(pdf_document, find_phone_numbers(text_pages, args)))

    if args.link:
        merge_rect_maps(rects_by_page, find_link_rects(pdf_document, args))

    if args.email:
        merge_rect_maps(rects_by_page, locate_matches(pdf_document, find_email_addresses(text_pages, args)))

    if args.mask:
        merge_rect_maps(rects_by_page, locate_matches(pdf_document, find_custom_mask(text_pages, args.mask, args)))

    if args.iban:
        merge_rect_maps(rects_by_page, locate_matches(pdf_document, find_ibans(text_pages, args)))

    if args.bic:
        merge_rect_maps(rects_by_page, locate_matches(pdf_document, find_bics(text_pages, args)))

    if args.timestamp:
        merge_rect_maps(rects_by_page, locate_matches(pdf_document, find_timestamp(text_pages, args)))

    if args.date:
        merge_rect_maps(rects_by_page, locate_matches(pdf_document, find_date(text_pages, args)))

    if args.barcode:
        merge_rect_maps(rects_by_page, find_barcode(pdf_document, args))

    if args.qrcode:
        merge_rect_maps(rects_by_page, find_qrcode(pdf_document, args))

    if selected_content_redaction_targets(args):
        log(args, "\n[i] Applying Redactions...\n")
        for page_num in tqdm(
            range(len(pdf_document)),
            desc="[i] Redacting Pages",
            unit="page",
            disable=is_quiet(args),
        ):
            page = pdf_document.load_page(page_num)
            apply_redaction_batch(page, rects_by_page[page_num], args)

    redact_pdf_internals(pdf_document, args)

    return pdf_document


### MAIN
def main():
    parser = argparse.ArgumentParser(prog="pdf_redactor.py")
    parser.add_argument("-i", "--input", help="Filename to be processed.", required=True)
    parser.add_argument("-o", "--output", help="Output path.")
    parser.add_argument("-e", "--email", help="Redact all email addresses.", action="store_true")
    parser.add_argument("-l", "--link", help="Redact all links.", action="store_true")
    parser.add_argument("-p", "--phonenumber", help="Redact all phone numbers.", action="store_true")
    parser.add_argument("-v", "--preview", action="store_true", help="Preview page redactions before continuing.")
    parser.add_argument(
        "-g",
        "--geographic-code",
        type=str,
        help="Geographic code for phone number detection (e.g. US, GB, FR) for better accuracy.",
    )
    parser.add_argument(
        "-m",
        "--mask",
        action="append",
        type=str,
        help='Custom word mask to redact, e.g. "John Doe" (case insensitive). Multiple masks can be specified.',
    )
    parser.add_argument("-t", "--text", type=str, default=None, help="Text to show in redacted areas. Default: None.")
    parser.add_argument(
        "-c",
        "--color",
        default="black",
        type=str,
        help='Fill color of redacted areas. Default: "black".',
        choices=list(COLOR_MAP.keys()),
    )
    parser.add_argument(
        "-C",
        "--text-color",
        default="white",
        type=str,
        help='Fill color of replacement text. Default: "white".',
        choices=list(COLOR_MAP.keys()),
    )
    parser.add_argument("-d", "--date", action="store_true", help="Redact all dates (dd./-mm./-yyyy).")
    parser.add_argument("-f", "--timestamp", action="store_true", help="Redact all timestamps.")
    parser.add_argument("-s", "--iban", action="store_true", help="Redact all IBANs (International Bank Account Numbers).")
    parser.add_argument("-b", "--bic", action="store_true", help="Redact all BICs (Bank Identifier Codes).")
    parser.add_argument("-r", "--barcode", action="store_true", help="Redact all barcodes.")
    parser.add_argument("-q", "--qrcode", action="store_true", help="Redact all QR Codes.")
    parser.add_argument(
        "--sanitize",
        action="store_true",
        help=(
            "Remove PDF internals including metadata, embedded/attached files, "
            "annotations/comments, form fields, JavaScript, thumbnails, hidden text, "
            "and pending redactions."
        ),
    )
    parser.add_argument(
        "--document-metadata",
        action="store_true",
        help="Remove PDF document information and XMP metadata.",
    )
    parser.add_argument("--embedded-files", action="store_true", help="Remove embedded and attached files.")
    parser.add_argument("--annotations", action="store_true", help="Remove annotations and comments.")
    parser.add_argument("--form-fields", action="store_true", help="Remove interactive form fields and stored values.")
    parser.add_argument("-x", "--color-hex", type=str, help='Fill color of redacted areas in HEX ("#000000").')
    parser.add_argument("-X", "--text-color-hex", type=str, help='Text color of redacted areas in HEX ("#FFFFFF").')
    parser.add_argument("--quiet", action="store_true", help="Suppress routine output and progress bars.")
    parser.add_argument(
        "--show-matches",
        action="store_true",
        help="Print exact detected values in logs. Disabled by default to avoid exposing sensitive data.",
    )
    args = parser.parse_args()

    input_is_dir = validate_input_path(args.input)
    validate_redaction_targets(args, parser)
    validate_output_flag(args, input_is_dir)

    if not args.quiet:
        print_logo()

    if args.text:
        log(args, f"\n[i] Using custom redaction text {args.text}")

    if not input_is_dir:
        pdf_document = load_pdf(args.input)
        text_pages = extract_text_pages(pdf_document) if selected_content_redaction_targets(args) else []
        pdf_document = run_redaction(args.input, pdf_document, text_pages, args)
        output_path = resolve_single_file_output_path(args.input, args.output)
        save_redactions(pdf_document, output_path, args)
        return

    log(args, f"\n[i] Analysing directory '{args.input}'\n")
    for filename in os.listdir(args.input):
        if not filename.lower().endswith(".pdf"):
            continue
        file_path = os.path.join(args.input, filename)
        pdf_document = load_pdf(file_path)
        text_pages = extract_text_pages(pdf_document) if selected_content_redaction_targets(args) else []
        pdf_document = run_redaction(file_path, pdf_document, text_pages, args)
        output_path = (
            os.path.join(args.output, os.path.basename(default_output_path(filename)))
            if args.output
            else default_output_path(file_path)
        )
        save_redactions(pdf_document, output_path, args)


if __name__ == "__main__":
    main()

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


def save_redactions(pdf_document, output_path):
    print(f"\n[i] Saving changes to '{output_path}'")
    pdf_document.ez_save(output_path)


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


### PHONE NUMBERS
def find_phone_numbers(text_pages, args):
    print("\n[i] Searching for Phone Numbers...")
    all_phone_numbers = {}
    region_code = args.geographic_code if args.geographic_code else None
    for i, text_page in enumerate(text_pages):
        page_phone_numbers = [match.raw_string for match in phonenumbers.PhoneNumberMatcher(text_page, region_code)]
        all_phone_numbers[i] = page_phone_numbers
        print(
            f" |  Found {len(page_phone_numbers)} Phone Number{'' if len(page_phone_numbers) == 1 else 's'} "
            f"on Page {i + 1}: {', '.join(str(number) for number in page_phone_numbers)}"
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


def find_link_rects(pdf_document):
    print("\n[i] Searching for Links...")
    rects_by_page = defaultdict(list)

    for page_num in tqdm(range(len(pdf_document)), desc="[i] Scanning Pages", unit="page"):
        page = pdf_document.load_page(page_num)
        link_list = page.get_links()
        descriptions = ", ".join(describe_link(link) for link in link_list)
        print(
            f" |  Found {len(link_list)} Link{'' if len(link_list) == 1 else 's'} "
            f"on Page {page_num + 1}: {descriptions}"
        )
        rects_by_page[page_num].extend(link["from"] for link in link_list if "from" in link)

    return rects_by_page


### EMAIL ADDRESSES
def find_email_addresses(text_pages):
    print("\n[i] Searching for Email Addresses...")
    all_email_addresses = {}
    extract_email_pattern = r"\S+@\S+\.\S+"
    for i, page in enumerate(text_pages):
        match = re.findall(extract_email_pattern, page)
        all_email_addresses[i] = match
        print(
            f" |  Found {len(match)} Email Address{'' if len(match) == 1 else 'es'} "
            f"on Page {i + 1}: {', '.join(str(email) for email in match)}"
        )
    return all_email_addresses


### CUSTOM SEARCH MASK
def build_custom_mask_pattern(mask):
    prefix = r"\b" if mask and re.match(r"\w", mask[0]) else ""
    suffix = r"\b" if mask and re.match(r"\w", mask[-1]) else ""
    return re.compile(f"{prefix}{re.escape(mask)}{suffix}", flags=re.IGNORECASE)


def find_custom_mask(text_pages, custom_masks):
    print("\n[i] Searching for Custom Mask matches...")
    all_hits = {page_num: [] for page_num in range(len(text_pages))}

    for mask in custom_masks:
        print(f"\n[i] Searching for mask: '{mask}'")
        pattern = build_custom_mask_pattern(mask)
        for page_num, page_text in enumerate(text_pages):
            matches = pattern.findall(page_text)
            all_hits[page_num].extend(matches)
            if matches:
                print(
                    f" |  Found {len(matches)} match{'' if len(matches) == 1 else 'es'} "
                    f"on Page {page_num + 1}: {', '.join(str(match) for match in matches)}"
                )

    total_matches = sum(len(matches) for matches in all_hits.values())
    print(f"\n[i] Total mask matches found: {total_matches}")
    return all_hits


### IBAN
def find_ibans(text_pages):
    print("\n[i] Searching for IBANs...")
    hits = {}
    match_pattern = r"\b[A-Z]{2}[0-9]{2}(?:[ ]?[0-9]{4}){4}(?!(?:[ ]?[0-9]){3})(?:[ ]?[0-9]{1,2})?\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page, flags=re.IGNORECASE)
        hits[i] = match
        print(f" |  Found {len(match)} IBAN{'' if len(match) == 1 else 's'} on Page {i + 1}: {', '.join(str(item) for item in match)}")
    return hits


### BIC
def find_bics(text_pages):
    print("\n[i] Searching for BICs...")
    hits = {}
    match_pattern = r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page, flags=re.IGNORECASE)
        hits[i] = match
        print(f" |  Found {len(match)} BIC{'' if len(match) == 1 else 's'} on Page {i + 1}: {', '.join(str(item) for item in match)}")
    return hits


### TIME
def find_timestamp(text_pages):
    print("\n[i] Searching for Timestamps...")
    hits = {}
    match_pattern = r"\b(?:[0-1]?[0-9]|2[0-3]):[0-5][0-9]\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page)
        hits[i] = match
        print(
            f" |  Found {len(match)} Timestamp{'' if len(match) == 1 else 's'} "
            f"on Page {i + 1}: {', '.join(str(item) for item in match)}"
        )
    return hits


### DATE
def find_date(text_pages):
    print("\n[i] Searching for Dates...")
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
        print(f" |  Found {len(match)} Date{'' if len(match) == 1 else 's'} on Page {i + 1}: {', '.join(str(item) for item in match)}")
    return hits


### BAR/QRCODES
def find_codes(pdf_document, code_type=None):
    print_type = "Barcodes" if code_type == "barcode" else "QR Codes"
    print(f"\n[i] Searching for {print_type}...")

    rects_by_page = defaultdict(list)

    if decode is None:
        print(f"[Warning] {PYZBAR_IMPORT_ERROR}. {print_type} detection disabled.")
        print(f"[Hint] {get_zbar_install_hint()}")
        return rects_by_page

    for page_num in range(len(pdf_document)):
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

        print(f" |  Found {counter} {print_type[:-1]}{'' if counter == 1 else 's'} on Page {page_num + 1}")

    return rects_by_page


def find_qrcode(pdf_document):
    return find_codes(pdf_document, code_type="qrcode")


def find_barcode(pdf_document):
    return find_codes(pdf_document, code_type="barcode")


def run_redaction(file_path, pdf_document, text_pages, args):
    print(f"[i] Analysing file '{file_path}'\n")

    text_rects_by_page = defaultdict(list)
    media_rects_by_page = defaultdict(list)

    if args.phonenumber:
        merge_rect_maps(text_rects_by_page, locate_matches(pdf_document, find_phone_numbers(text_pages, args)))

    if args.link:
        merge_rect_maps(text_rects_by_page, find_link_rects(pdf_document))

    if args.email:
        merge_rect_maps(text_rects_by_page, locate_matches(pdf_document, find_email_addresses(text_pages)))

    if args.mask:
        merge_rect_maps(text_rects_by_page, locate_matches(pdf_document, find_custom_mask(text_pages, args.mask)))

    if args.iban:
        merge_rect_maps(text_rects_by_page, locate_matches(pdf_document, find_ibans(text_pages)))

    if args.bic:
        merge_rect_maps(text_rects_by_page, locate_matches(pdf_document, find_bics(text_pages)))

    if args.timestamp:
        merge_rect_maps(text_rects_by_page, locate_matches(pdf_document, find_timestamp(text_pages)))

    if args.date:
        merge_rect_maps(text_rects_by_page, locate_matches(pdf_document, find_date(text_pages)))

    if args.barcode:
        merge_rect_maps(media_rects_by_page, find_barcode(pdf_document))

    if args.qrcode:
        merge_rect_maps(media_rects_by_page, find_qrcode(pdf_document))

    print("\n[i] Applying Redactions...\n")
    for page_num in tqdm(range(len(pdf_document)), desc="[i] Redacting Pages", unit="page"):
        page = pdf_document.load_page(page_num)
        apply_redaction_batch(page, text_rects_by_page[page_num], args)
        apply_redaction_batch(page, media_rects_by_page[page_num], args)

    return pdf_document


### MAIN
def main():
    print_logo()

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
    parser.add_argument("-x", "--color-hex", type=str, help='Fill color of redacted areas in HEX ("#000000").')
    parser.add_argument("-X", "--text-color-hex", type=str, help='Text color of redacted areas in HEX ("#FFFFFF").')
    args = parser.parse_args()
    input_is_dir = validate_input_path(args.input)
    validate_output_flag(args, input_is_dir)

    if args.text:
        print(f"\n[i] Using custom redaction text {args.text}")

    if not input_is_dir:
        pdf_document = load_pdf(args.input)
        text_pages = extract_text_pages(pdf_document)
        pdf_document = run_redaction(args.input, pdf_document, text_pages, args)
        output_path = resolve_single_file_output_path(args.input, args.output)
        save_redactions(pdf_document, output_path)
        return

    print(f"\n[i] Analysing directory '{args.input}'\n")
    for filename in os.listdir(args.input):
        if not filename.lower().endswith(".pdf"):
            continue
        file_path = os.path.join(args.input, filename)
        pdf_document = load_pdf(file_path)
        text_pages = extract_text_pages(pdf_document)
        pdf_document = run_redaction(file_path, pdf_document, text_pages, args)
        output_path = (
            os.path.join(args.output, os.path.basename(default_output_path(filename)))
            if args.output
            else default_output_path(file_path)
        )
        save_redactions(pdf_document, output_path)


if __name__ == "__main__":
    main()

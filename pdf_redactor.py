#!/usr/bin/env python3

import pymupdf as fitz
import phonenumbers
import os
import argparse
import re
import sys
from tqdm import tqdm
from PIL import Image


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
    "blue": BLUE
}



### HELPER FUNCTIONS

# print logo
def print_logo():
        print(r"""
_____  _____  ______ _____          _            _             
|  __ \|  __ \|  ____|  __ \        | |          | |            
| |__) | |  | | |__  | |__) |___  __| | __ _  ___| |_ ___  _ __ 
|  ___/| |  | |  __| |  _  // _ \/ _` |/ _` |/ __| __/ _ \| '__|
| |    | |__| | |    | | \ \  __/ (_| | (_| | (__| || (_) | |   
|_|    |_____/|_|    |_|  \_\___|\__,_|\__,_|\___|\__\___/|_|                            
                                    PDFRedactor 
                                               by Lukas Tillmann
        """)

# save to file
def save_redactions_to_file(pdf_document, filename):
    filepath = os.path.dirname(os.path.abspath(__file__))+"/"+filename
    print(f"\n[i] Saving changes to '{filepath}'")
    pdf_document.ez_save(filepath)

def save_redactions_to_relative_file(pdf_document, pathname):
    print(f"\n[i] Saving changes to '{pathname}'")
    pdf_document.ez_save(pathname)

# check if path is directory
def is_directory(file_path):
    try:
        # Check if the path exists
        if os.path.exists(file_path):
            # Check if the path is a directory
            if os.path.isdir(file_path):
                return True

            # Check if the path is a file and has a .pdf extension
            elif os.path.isfile(file_path) and file_path.lower().endswith('.pdf'):
                return False
            
            else:
                print(f"[Error] File '{file_path}' is not a PDF file.")
            
        else:
            print(f"[Error] No such Path/File: {file_path}\nPlease specify path or make sure file exists.")
            sys.exit(1)

    except Exception as e:
        print(f"[Error] An unexpected Error has occurred: {e}")
    
# load pdf
def load_pdf(file_path):
    return fitz.open(file_path)
  
# ocr pdf
def ocr_pdf(pdf_document):
    text_pages = []
    # for every page in pdf, get tex and append to list of text pages
    for page_num in range(len(pdf_document)):
        page = pdf_document.load_page(page_num)
        text = page.get_text("text")
        text_pages.append(text)

    return text_pages

def validate_output_flag(args):
    "Validates the output flag to ensure correct format"
    if args.output:
        is_output_dir = os.path.isdir(args.output)
        is_output_pdf = args.output.lower().endswith(".pdf")

        # Case 1: Processing a single file, output should be a .pdf file
        if not is_directory(args.input) and not is_output_pdf:
            raise ValueError(f"Output file must be a '.pdf' file when processing a single PDF. Given: {args.output}")

        # Case 2: Processing a directory, output should be a directory (or not specified)
        if is_directory(args.input) and (args.output and not is_output_dir):
            raise ValueError(f"Output must be a directory when processing multiple PDFs. Given: {args.output}")
        


### PHONE NUMBERS
def find_phone_numbers(text_pages):
    print("\n[i] Searching for Phone Numbers...")
    all_phone_numbers = {}
    # for every text page in list of all pages, find all phone numbers and append to list of all phone numbers
    for i, text_page in enumerate(text_pages):
        page_phone_numbers = []
        for match in phonenumbers.PhoneNumberMatcher(text_page, None):
            page_phone_numbers.append(match.raw_string)
        all_phone_numbers[i] = page_phone_numbers
        print(f" |  Found {len(page_phone_numbers)} Phone Number{'' if len(page_phone_numbers)==1 else 's'} on Page {i+1}: {', '.join(str(p) for p in page_phone_numbers)}")

    return all_phone_numbers


def redact_phone_numbers(pdf_document, all_phone_numbers, args):
    if len(all_phone_numbers) > 0:
        print("\n[i] Redacting Phone Numbers...\n")
        # iterate through each page of pdf
        for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
            page = pdf_document.load_page(page_num)
            rect_list = []
            # for every detected phonenumber on page, find position on page and get Rect object, safe to list
            for phone_number in all_phone_numbers[page_num]:
                rect_list.extend(page.search_for(phone_number))
                # for every phone number found, add redaction
                for rect in rect_list:
                    anots = page.add_redact_annot(quad=rect, text=args.text, text_color=WHITE, fill=COLOR_MAP[args.color], cross_out=True)
                    if args.preview:
                            preview_redactions(page, anots)
                    else:
                        # apply redactions to page    
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    else:
        print("\n[i] No Phone Number found...\n")



### LINKS
def redact_links(pdf_document, args):
    print("\n[i] Searching for Links...")
    # for every text page in list of all pages, find all links and append to list of all links
    for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
        page = pdf_document.load_page(page_num)
        link_list = page.get_links()
        print(f" |  Found {len(link_list)} Link{'' if len(link_list)==1 else 's'} on Page {page_num+1}: {', '.join(str(p['uri']) for p in link_list)}")
        rect_list = [item['from'] for item in link_list]
        for rect in rect_list:
            anots = page.add_redact_annot(quad=rect, text=args.text, text_color=WHITE, fill=COLOR_MAP[args.color], cross_out=True)
            if args.preview:
                preview_redactions(page, anots)
            else:
                # apply redactions to page    
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)



### EMAIL ADRESSES
def find_email_addresses(text_pages):
    print("\n[i] Searching for Email Addresses...")
    all_email_addresses = {}
    extract_email_pattern = r"\S+@\S+\.\S+"
    for i, page in enumerate(text_pages):
        match = re.findall(extract_email_pattern, page)
        all_email_addresses[i] = match
        print(f" |  Found {len(match)} Email Address{'' if len(match)==1 else 'es'} on Page {i+1}: {', '.join(str(p) for p in match)}")
    return all_email_addresses        
    

def redact_email_adresses(pdf_document, all_email_addresses, args):
    if len(all_email_addresses) > 0:
        print("\n[i] Redacting Email Addresses...\n")
        for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
            page = pdf_document.load_page(page_num)
            rect_list = []
            for email_address in all_email_addresses[page_num]:
                    rect_list.extend(page.search_for(email_address))
                    # for every phone number found, add redaction
                    for rect in rect_list:
                        anots = page.add_redact_annot(quad=rect, text=args.text, text_color=WHITE, fill=COLOR_MAP[args.color], cross_out=True)
                        if args.preview:
                            preview_redactions(page, anots)
                        else:
                            # apply redactions to page    
                            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    else:
        print("\n[i] No Email Address found.\n")



### CUSTOM SEARCH MASK
def find_custom_mask(text_pages, custom_mask):
    print("\n[i] Searching for Custom Mask matches...")
    hits = {}
    match_pattern = r'\b'+custom_mask+r'\b'
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page, flags=re.IGNORECASE)
        hits[i] = match
        print(f" |  Found {len(match)} Mask Match{'' if len(match)==1 else 'es'} on Page {i+1}: {', '.join(str(p) for p in match)}")

    return hits     


def redact_custom_mask(pdf_document, hits, args):
    if len(hits) > 0:
        print("\n[i] Redacting Custom Mask Matches...\n")

        # Iterate through pages
        for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
            page = pdf_document.load_page(page_num)
            rect_list = []

            for match in hits[page_num]:
                rect_list.extend(page.search_for(match))

                # Iterate through found text positions and apply redaction
                for rect in rect_list:
                    anots = page.add_redact_annot(
                        quad=rect, text=args.text, text_color=WHITE, 
                        fill=COLOR_MAP[args.color], cross_out=True
                    )

                    if args.preview:
                        preview_redactions(page, anots)
                    else:
                        # Apply redactions to the page
                        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    else:
        print("\n[i] No Custom Mask matches found.\n")



### IBAN
def find_ibans(text_pages):
    print("\n[i] Searching for IBANs...")
    hits = {}
    match_pattern = r'\b[A-Z]{2}[0-9]{2}(?:[ ]?[0-9]{4}){4}(?!(?:[ ]?[0-9]){3})(?:[ ]?[0-9]{1,2})?\b'
    #match_pattern = r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page, flags=re.IGNORECASE)
        hits[i] = match
        print(f" |  Found {len(match)} IBAN{'' if len(match)==1 else 's'} on Page {i+1}: {', '.join(str(p) for p in match)}")

    return hits  

def redact_ibans(pdf_document, hits, args):
    if len(hits) > 0:
        print("\n[i] Redacting IBANs...\n")
        for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
            page = pdf_document.load_page(page_num)
            rect_list = []
            for match in hits[page_num]:
                    rect_list.extend(page.search_for(match))
                    # for every phone number found, add redaction
                    for rect in rect_list:
                        anots = page.add_redact_annot(quad=rect, text=args.text, text_color=WHITE, fill=COLOR_MAP[args.color], cross_out=True)
                        if args.preview:
                            preview_redactions(page, anots)
                        else:
                            # apply redactions to page    
                            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    else:
         print("\n[i] No IBAN found.\n")



### BIC
def find_bics(text_pages):
    print("\n[i] Searching for BICs...")
    hits = {}
    match_pattern = r"\b[A-Z]{6}[A-Z0-9]{2}[A-Z0-9]{3}?\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page)
        hits[i] = match
        print(f" |  Found {len(match)} BIC{'' if len(match)==1 else 's'} on Page {i+1}: {', '.join(str(p) for p in match)}")

    return hits  

def redact_bics(pdf_document, hits, args):
    if len(hits) > 0:
        print("\n[i] Redacting BICs...\n")
        for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
            page = pdf_document.load_page(page_num)
            rect_list = []
            for match in hits[page_num]:
                    rect_list.extend(page.search_for(match))
                    # for every phone number found, add redaction
                    for rect in rect_list:
                        anots = page.add_redact_annot(quad=rect, text=args.text, text_color=WHITE, fill=COLOR_MAP[args.color], cross_out=True)
                        if args.preview:
                            preview_redactions(page, anots)
                        else:
                            # apply redactions to page    
                            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    else:
         print("\n[i] No BIC found.\n")


### TIME
def find_timestamp(text_pages):
    print("\n[i] Searching for Timestamps...")
    hits = {}
    # \b([01][0-9]|2[0-3]):([0-5][0-9])\b
    match_pattern = r"\b([0-1]?[0-9]|2[0-3]):[0-5][0-9]\b"
    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page)
        hits[i] = match
        print(f" |  Found {len(match)} Timestamp{'' if len(match)==1 else 's'} on Page {i+1}: {', '.join(str(p) for p in match)}")

    return hits  

def redact_timestamp(pdf_document, hits, args):
    if len(hits) > 0:
        print("\n[i] Redacting Timestamps...\n")
        for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
            page = pdf_document.load_page(page_num)
            rect_list = []
            for match in hits[page_num]:
                    rect_list.extend(page.search_for(match))
                    # for every phone number found, add redaction
                    for rect in rect_list:
                        anots = page.add_redact_annot(quad=rect, text=args.text, text_color=WHITE, fill=COLOR_MAP[args.color], cross_out=True)
                        if args.preview:
                            preview_redactions(page, anots)
                        else:
                            # apply redactions to page    
                            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    else:
         print("\n[i] No Timestamp found.\n")



### DATE
def find_date(text_pages):
    print("\n[i] Searching for Dates...")
    hits = {}

    # this regex pattern matches all kinds of dates in dd/mm/yyyy format, seperators include "/.-"
    # it also matches english and german abbreviations for the written out months.
    # e.g. 10/5/2023, 12.1.2000, 10 Aug 2033, 7. Januar 2018
    # check https://regex101.com/r/T2lC8l/1
    match_pattern = r"((?:[0]?[1-9]|[12][0-9]|3[01])(?:.?)(?:[./-]|[' '])(?:0?[1-9]|1[0-2]|Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?|Jan(?:uar)?|Feb(?:uar)?|Mär(?:z)?|Apr(?:il)?|Mai|Jun(?:i)?|Jul(?:i)?|Aug(?:ust)?|Sep(?:tember)?|Okt(?:ober)?|Nov(?:ember)?|Dez(?:ember)?)(?:[./-]|[' '])(?:[0-9]{4}|[0-9]{2}))"

    for i, page in enumerate(text_pages):
        match = re.findall(match_pattern, page)
        hits[i] = match
        print(f" |  Found {len(match)} Date{'' if len(match)==1 else 's'} on Page {i+1}: {', '.join(str(p) for p in match)}")

    return hits  

def redact_date(pdf_document, hits, args):
    if len(hits) > 0:
        print("\n[i] Redacting Dates...\n")
        for page_num in tqdm(range(len(pdf_document)), desc="Redacting Pages", unit="page"):
            page = pdf_document.load_page(page_num)
            rect_list = []
            for match in hits[page_num]:
                    rect_list.extend(page.search_for(match))
                    # for every phone number found, add redaction
                    for rect in rect_list:
                        anots = page.add_redact_annot(quad=rect, text=args.text, text_color=WHITE, fill=COLOR_MAP[args.color], cross_out=True)
                        if args.preview:
                            preview_redactions(page, anots)
                        else:
                            # apply redactions to page    
                            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    else:
         print("\n[i] No Date found.\n")




# preview redacted files
def preview_redactions(page, anots):
    # zoom factor not to lose the quality
    zoom = 3
    mat = fitz.Matrix(zoom, zoom)
    # render page to an image
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img.show()
    # Wait for user input
    while True:
        user_input = input("[?] Continue with redaction? (Y/n): ").strip().lower()
        if user_input == 'y':
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            break
        elif user_input == 'n':
            print(" |  Redaction aborted.")
            page.delete_annot(anots)
            break
        else:
            print("[Error] Invalid input. Please enter 'Y' to continue or 'n' to abort.")


def run_redaction(file_path, text_pages, pdf_document, args):
    print(f"[i] Analysing file '{file_path}'\n")

    # load pdf and ocr
    pdf_document = load_pdf(file_path)
    text_pages = ocr_pdf(pdf_document)
    
    if args.phonenumber:
        all_phone_numbers = find_phone_numbers(text_pages)
        redact_phone_numbers(pdf_document, all_phone_numbers, args)

    if args.link:
        redact_links(pdf_document, args)

    if args.email:  
        emails = find_email_addresses(text_pages)
        redact_email_adresses(pdf_document, emails, args)
    
    if args.mask:
        hits = find_custom_mask(text_pages, args.mask)
        redact_custom_mask(pdf_document, hits, args)
    
    if args.iban:
        ibans = find_ibans(text_pages)
        redact_ibans(pdf_document, ibans, args)

    if args.bic:
        bics = find_bics(text_pages)
        redact_bics(pdf_document, bics, args)

    if args.timestamp:
        timestamps = find_timestamp(text_pages)
        redact_timestamp(pdf_document, timestamps, args)

    if args.date:
        dates = find_date(text_pages)
        redact_date(pdf_document, dates, args)

    return pdf_document




### MAIN
def main():
    # print ascii logo
    print_logo()    

    # init argument parser
    parser = argparse.ArgumentParser(prog='pdf_redactor.py')

    # add flags 
    parser.add_argument('-i', '--input', help='Filename to be processed.', required=True)
    parser.add_argument('-o', '--output', help = 'Output path.')
    parser.add_argument('-e', '--email', help='Redact all email addresses.', action='store_true')
    parser.add_argument('-l', '--link', help='Redact all links.', action='store_true')
    parser.add_argument('-p', '--phonenumber', help='Redact all phone numbers.', action='store_true')
    parser.add_argument('-v', '--preview', action='store_true', help='Preview redacted areas before continuing.')
    parser.add_argument('-m', '--mask', type=str, default=None, help='Custom Word mask to redact, e.g. "John Doe" (case insenitive).')
    parser.add_argument('-t', '--text', type=str, default=None, help='Text to show in redacted areas. Default: None.')
    parser.add_argument('-c', '--color', default='black', type=str, help='Fill Color of redacted areas. Default: "black".', choices=list(COLOR_MAP.keys()))
    parser.add_argument('-d', '--date', action='store_true', help='Redact all dates (dd./-mm./-yyyy).')
    parser.add_argument('-f', '--timestamp', action='store_true', help='Redact all timestamps.')
    parser.add_argument('-s', '--iban', action='store_true', help='Redact all IBANs (International Bank Account Numbers).')
    parser.add_argument('-b', '--bic', action='store_true', help='Redact all BICs (Bank Identifier Codes).')

    # parse args
    args = parser.parse_args()

    # assign args to variables
    path = args.input

    # Validate the output flag
    validate_output_flag(args)
    
    # if path is a pdf file 
    if not is_directory(path):
        if args.text:
            print(f"\n[i] Using custom redaction text {args.text}")
        # load pdf and ocr
        pdf_document = load_pdf(path)
        text_pages = ocr_pdf(pdf_document)
        
        # run redaction process
        pdf_document = run_redaction(path, text_pages, pdf_document, args)

        # save to file
        if args.output:
            out_path = args.output
            save_redactions_to_relative_file(pdf_document, out_path)
        else:
            out_path = "{0}_{2}{1}".format(*os.path.splitext(path) + ("redacted",))
            save_redactions_to_file(pdf_document, out_path)


    # if path is directory
    elif is_directory(path):
        print(f"\n[i] Analysing directory '{path}'\n")

        if args.text:
            print(f"\n[i] Using custom redaction text {args.text}")
        # Iterate over the pdf files in the directory
        for filename in os.listdir(path):
            if filename.lower().endswith('.pdf'):
                file_path = os.path.join(path, filename)

                # load pdf and ocr
                pdf_document = load_pdf(file_path)
                text_pages = ocr_pdf(pdf_document)

                # run redaction process
                pdf_document = run_redaction(file_path, text_pages, pdf_document, args)

                # save to file
                if args.output:
                    out_path =  os.path.join(args.output, "{0}_{2}{1}".format(*os.path.splitext(filename) + ("redacted",)))
                    save_redactions_to_relative_file(pdf_document, out_path)
                else:
                    out_path = os.path.join(path, "{0}_{2}{1}".format(*os.path.splitext(filename) + ("redacted",)))
                    save_redactions_to_file(pdf_document, out_path)


# init main
if __name__ == "__main__":
    main()

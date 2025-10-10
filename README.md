# PDFRedactor

PDFRedactor is a Python tool for redacting sensitive information from PDF files. The script can detect and redact phone numbers, email addresses, links, IBANs, BICs, timestamps, dates, QR Codes, Barcodes and custom text patterns from PDF documents.

## Features

- **Phone Numbers**: Redacts phone numbers.
- **Email Addresses**: Redacts email addresses.
- **Links**: Redacts links/urls/hyperlinks.
- **IBANs**: Redacts detected International Bank Account Numbers.
- **BICs**: Redacts detected Bank Identifier Codes.
- **Timestamps**: Redacts detected timestamps.
- **Dates**: Redacts detected dates in various formats.
- **Custom Text Patterns**: Redact any custom text pattern specified by the user.
- **QRCodes and Barcodes**

## Installation

To install PDFRedactor, follow these steps:

1. Clone the repository:

   ```bash
   git clone https://github.com/ltillmann/pdf-redactor.git
   ```

2. cd into the cloned directory

3. Install the required dependencies using pip:
   
   ```bash
   pip3 install -r requirements.txt
   ```
4. Make the script executable or pass the script directly to python:

   ```bash
   chmod +x pdf_redactor.py
   ```

## Quick start

You can run the executable script from the command line:

   ```bash
   ./pdf_redactor.py [-h] -i INPUT [-o OUTPUT] [-e] [-l] [-p] [-v] [-m MASK]
                     [-t TEXT] [-c {white,black,red,green,blue}]
                     [-C {white,black,red,green,blue}] [-d] [-f] [-s] [-b]
                     [-r] [-q] [-x COLOR_HEX] [-X TEXT_COLOR_HEX]
   ```
Below are the available options:

### Options

- `-h`, `--help`: Show help message and exit.
- `-i INPUT`, `--input INPUT`: Filename or directory path to be processed.
- `-o OUTPUT`, `--output OUTPUT`: Filename or directory path to save redacted files to.
- `-e`, `--email`: Redact all email addresses.
- `-l`, `--link`: Redact all links.
- `-p`, `--phonenumber`: Redact all phone numbers.
- `-v`, `--preview`: Preview redacted areas before continuing.
- `-g GEOGRAPHIC_CODE`, `--geographic-code GEOGRAPHIC_CODE`: Geographic code for phone number detection (e.g. US, GB, FR) for better accuracy.
- `-m MASK`, `--mask MASK`: Custom word mask to redact, e.g. "John Doe" (case insensitive). Multiple masks can be specified by using this flag multiple times, e.g. `-m "text1" -m "text2"`.
- `-t TEXT`, `--text TEXT`: Text to show in redacted areas. Default: None.
- `-c {white,black,red,green,blue}`, `--color {white,black,red,green,blue}`: Fill Color of redacted areas. Default: "black".
- `-C {white,black,red,green,blue}`, `--text_color {white,black,red,green,blue}`: Fill Color of text over redacted areas. Default: "white".
- `-d`, `--date`: Redact all dates (dd./-mm./-yyyy).
- `-f`, `--timestamp`: Redact all timestamps.
- `-s`, `--iban`: Redact all IBANs (International Bank Account Numbers).
- `-b`, `--bic`: Redact all BICs (Bank Identifier Codes).
- `-r`, `--barcode`: Redact all barcodes.
- `-q`, `--qrcode`: Redact all QR Codes.
- `-x COLOR_HEX`, `--color-hex COLOR_HEX`:
                        Fill color of redacted areas in HEX ("#000000").
- `-X, TEXT_COLOR_HEX`, `--text-color-hex TEXT_COLOR_HEX`:
                        Text color of redacted areas in HEX ("#FFFFFF").

## Examples

1. Redact phone numbers from a single PDF file:
   
   ```bash
   ./pdf_redactor.py -i input_file.pdf -p
   ```
   
2. Redact phone numbers with geographic code for better accuracy:
   
   ```bash
   ./pdf_redactor.py -i input_file.pdf -p -g US
   ```
   
3. To redact email addresses and preview redacted areas:

   ```bash
   ./pdf_redactor.py -i input_file.pdf -e -v
   ```
4. Redact a custom text pattern and specify redaction text for a directory of PDF files:

   ```bash
   ./pdf_redactor.py -i directory_path -m "CONFIDENTIAL" -t "[REDACTED]"
   ```

4. Redact multiple custom text patterns:

   ```bash
   ./pdf_redactor.py -i input_file.pdf -m "texte1" -m "texte2" -m "texte3"
   ```
   
## Preview Redactions

When using the `-v` or `--preview` option, the script will display a preview of each redacted area on each page and prompt you to continue with the redaction or abort.

## Limitations

- Most detection features rely on regular expressions, which may not cover all possible formats or variations.
- PDFRedactor CANNOT (yet) redact vector graphics, images, XObjects, metadata, names, adressess, SSNs, tables, labels etc.

## License

This project is licensed under the MIT License.

## Acknowledgments

- This tool utilizes the PyMuPDF library for OCR and PDF processing [PyMuPDF](https://github.com/pymupdf/PyMuPDF).
- To detect phone numbers, I used David Drysdales Python port of Google's libphonenumber [python-phonenumbers](https://github.com/daviddrysdale/python-phonenumbers).
- To detect QR/Barcodes, I utilized pyzbar library for the most consistent results [pyzbar](https://github.com/NaturalHistoryMuseum/pyzbar).

## Contributing

Contributions are welcome! Please feel free to open a pull request or report an issue.

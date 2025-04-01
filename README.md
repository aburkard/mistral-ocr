# Mistral OCR Document Processor

A command-line tool to process documents using the Mistral AI OCR API.

## Installation

### Option 1: Install from Source

```bash
git clone https://github.com/yourusername/mistral-ocr.git
cd mistral-ocr
pip install .
```

### Option 2: Install in Development Mode

```bash
git clone https://github.com/yourusername/mistral-ocr.git
cd mistral-ocr
pip install -e .
```

## Configuration

Create a `.env` file in your working directory with your Mistral API key:

```
MISTRAL_API_KEY="YOUR_MISTRAL_API_KEY_HERE"
```

## Usage

After installation, you can run the tool from anywhere:

```bash
mistral-ocr <document_source> [-v/--verbose]
```

Replace `<document_source>` with either:

- A URL to the document (e.g., `https://example.com/document.pdf`)
- A local file path (e.g., `./my_document.png`)

### Examples

Process a document from a URL:

```bash
mistral-ocr https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf
```

Process a local file with verbose logging:

```bash
mistral-ocr ./invoices/invoice_march.pdf --verbose
```

## Output

The tool prints the extracted text from the document in Markdown format.

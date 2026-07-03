# Mistral OCR

[![PyPI](https://img.shields.io/pypi/v/mistral-ocr-tool)](https://pypi.org/project/mistral-ocr-tool/)

A simple CLI to extract text from documents using the Mistral OCR API.

## Installation

```bash
pip install mistral-ocr-tool
```

To render HTML files or pages before OCR, install the optional HTML support:

```bash
pip install "mistral-ocr-tool[html]"
python -m playwright install chromium
```

Or install from source:

```bash
git clone https://github.com/aburkard/mistral-ocr.git
cd mistral-ocr
pip install .
```

## Configuration

Set your Mistral API key as an environment variable or in a `.env` file:

```
MISTRAL_API_KEY="your-api-key"
```

## Usage

```bash
mistral-ocr <document_source> [options]
```

The document source can be a URL, a local file path, or `-` to read from stdin.

### Examples

```bash
# Process a PDF from a URL
mistral-ocr https://example.com/document.pdf

# Process a local file
mistral-ocr ./invoice.pdf

# Render a local HTML file to PDF before OCR
mistral-ocr ./report.html

# Render an HTML page URL to PDF before OCR
mistral-ocr https://example.com/report

# Pipe from stdin
cat document.pdf | mistral-ocr -

# Process specific pages only (0-indexed)
mistral-ocr large-doc.pdf --pages 0,2,5

# Output as JSON (great for piping to jq)
mistral-ocr document.pdf --json | jq '.pages[0].markdown'

# Extract tables as HTML
mistral-ocr document.pdf --table-format html

# Include headers and footers
mistral-ocr document.pdf --extract-headers --extract-footers

# Save markdown and images to a directory
mistral-ocr document.pdf -o output/

# Include base64 images in JSON output (for programmatic use)
mistral-ocr document.pdf --json --include-images

# Check page count and estimated cost before processing
mistral-ocr large-doc.pdf --dry-run
```

### Options

| Option | Description |
|---|---|
| `-p, --pages` | Comma-separated page numbers to process (0-indexed) |
| `--json` | Output full JSON response instead of markdown |
| `-o, --output-dir` | Save markdown and images to a directory |
| `--table-format` | Table output format: `markdown` or `html` |
| `--extract-headers` | Include page headers |
| `--extract-footers` | Include page footers |
| `--include-images` | Include images (requires `--json` or `-o`) |
| `--image-limit N` | Maximum number of images to extract; use `0` to disable image extraction |
| `--image-min-size N` | Minimum image dimension in pixels |
| `--model NAME` | Model override (default: `mistral-ocr-latest`) |
| `--render-html MODE` | HTML rendering mode: `auto`, `always`, or `never` (default: `auto`) |
| `--html-timeout N` | Seconds to wait while rendering HTML (default: `30`) |
| `--dry-run` | Show page count and estimated cost without processing |
| `-v, --verbose` | Enable verbose logging |

Image extraction options require image output mode (`-o/--output-dir` or `--json --include-images`), except `--image-limit 0`, which is allowed in text-only mode to explicitly disable image extraction.

HTML inputs are rendered to a temporary PDF with Chromium via Playwright before being sent to Mistral OCR. In `auto` mode, local `.html`/`.htm` files and URLs with `Content-Type: text/html` are rendered; other URLs are passed directly to Mistral.

## Development

```bash
uv sync --group dev
uv run pytest tests/
```

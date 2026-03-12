# Mistral OCR

A simple CLI to extract text from documents using the Mistral OCR API.

## Installation

```bash
pip install .
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
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

# Include base64-encoded images in response
mistral-ocr document.pdf --include-images

# Check page count and estimated cost before processing
mistral-ocr large-doc.pdf --dry-run
```

### Options

| Option | Description |
|---|---|
| `-p, --pages` | Comma-separated page numbers to process (0-indexed) |
| `--json` | Output full JSON response instead of markdown |
| `--table-format` | Table output format: `markdown` or `html` |
| `--extract-headers` | Include page headers |
| `--extract-footers` | Include page footers |
| `--include-images` | Include base64-encoded images in response |
| `--image-limit N` | Maximum number of images to extract |
| `--image-min-size N` | Minimum image dimension in pixels |
| `--model NAME` | Model override (default: `mistral-ocr-latest`) |
| `--dry-run` | Show page count and estimated cost without processing |
| `-v, --verbose` | Enable verbose logging |

## Development

```bash
uv sync --group dev
uv run pytest tests/
```

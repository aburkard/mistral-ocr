# Mistral OCR Document Processor

This script processes a document, either from a URL or a local file path, using the Mistral AI OCR API and prints the response.

## Prerequisites

- Python 3.x
- `pip` (Python package installer)
- Mistral AI API Key

## Setup

1.  **Clone or Download:** Get the `main.py` script.
2.  **Install Dependencies:**
    Install the required Python libraries. It's recommended to create a `requirements.txt` file:

    ```text:requirements.txt
    mistralai
    python-dotenv
    validators
    ```

    Then install them:

    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure API Key:**
    Create a file named `.env` in the same directory as the script and add your Mistral API key:
    ```dotenv:.env
    MISTRAL_API_KEY="YOUR_MISTRAL_API_KEY_HERE"
    ```
    Replace `"YOUR_MISTRAL_API_KEY_HERE"` with your actual key.

## Usage

Run the script from your terminal, providing the document source (URL or file path) as a command-line argument:

```bash
python main.py <document_source>
```

Replace `<document_source>` with either:

- A publicly accessible URL to the document (e.g., `https://example.com/document.pdf`).
- A local file path to the document (e.g., `./my_document.png` or `/path/to/your/document.jpg`).

## Example

**Processing a document from a URL:**

```bash
python main.py https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf
```

**Processing a document from a local file:**

```bash
python main.py ./invoices/invoice_march.pdf
```

## Output

The script will print the JSON response received from the Mistral OCR API, which includes the extracted text, layout information, and optionally the base64 encoded image if `include_image_base64` is set to `True` (which it is by default in the script).

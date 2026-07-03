import base64
import io
import os
import sys
import json
import argparse
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    from mistralai import Mistral
except ImportError:
    from mistralai.client import Mistral
from dotenv import load_dotenv
from pypdf import PdfReader


def is_url(s):
    parsed = urlparse(s)
    return parsed.scheme in ("http", "https")


LOCAL_FILE_EXTENSIONS = {
    ".avif", ".bmp", ".csv", ".doc", ".docx", ".gif", ".htm", ".html", ".jpeg",
    ".jpg", ".json", ".md", ".pdf", ".png", ".ppt", ".pptx", ".tif", ".tiff",
    ".txt", ".webp", ".xls", ".xlsx",
}


def looks_like_bare_url(source):
    """Return True for URL-looking inputs without an explicit scheme."""
    if source == "-" or is_url(source) or os.path.exists(source):
        return False
    if "://" in source or source.startswith(("/", "./", "../", "~")):
        return False
    if any(char.isspace() for char in source):
        return False

    host = source.split("/", 1)[0]
    if not host or "@" in host:
        return False
    if Path(host).suffix.lower() in LOCAL_FILE_EXTENSIONS:
        return False

    host_without_port = host.rsplit(":", 1)[0]
    return "." in host_without_port or host_without_port == "localhost"


def normalize_document_source(source):
    """Normalize friendly CLI source forms before routing."""
    if looks_like_bare_url(source):
        return f"https://{source}"
    return source


def parse_pages(pages_str):
    """Parse a comma-separated list of 0-indexed page numbers."""
    pages = []
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        pages.append(int(part))
    return pages


def upload_file(client, file_path, file_name=None):
    """Upload a file to Mistral and return a signed URL document dict."""
    if file_name is None:
        file_name = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        uploaded = client.files.upload(
            file={"file_name": file_name, "content": f},
            purpose="ocr",
        )
    logging.info(f"File uploaded. ID: {uploaded.id}")
    signed = client.files.get_signed_url(file_id=uploaded.id)
    logging.info("Signed URL obtained.")
    return {"type": "document_url", "document_url": signed.url}


def build_document(client, source, render_html="auto", html_timeout=30):
    """Resolve a source (URL, file path, or '-' for stdin) into an API document dict."""
    source = normalize_document_source(source)
    if should_render_html(source, render_html):
        pdf_path = render_html_to_pdf(source, timeout_seconds=html_timeout)
        try:
            file_name = f"{get_doc_stem(source)}.pdf"
            return upload_file(client, pdf_path, file_name=file_name)
        finally:
            os.unlink(pdf_path)

    if source == "-":
        data = sys.stdin.buffer.read()
        if not data:
            logging.error("No data received from stdin.")
            sys.exit(1)
        tmp = tempfile.NamedTemporaryFile(delete=False)
        try:
            tmp.write(data)
            tmp.close()
            return upload_file(client, tmp.name, file_name="stdin")
        finally:
            os.unlink(tmp.name)
    elif is_url(source):
        return {"type": "document_url", "document_url": source}
    elif os.path.exists(source):
        logging.info(f"Uploading file: {source}...")
        return upload_file(client, source)
    else:
        logging.error(f"'{source}' is not a valid URL or an existing file path.")
        sys.exit(1)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
HTML_EXTENSIONS = {".html", ".htm"}


def is_html_path(source):
    """Return True when a local path or URL path looks like HTML."""
    path = urlparse(source).path if is_url(source) else source
    return Path(path).suffix.lower() in HTML_EXTENSIONS


def url_content_type(url):
    """Best-effort content type lookup for deciding whether a URL is HTML."""
    try:
        req = Request(url, method="HEAD")
        with urlopen(req, timeout=10) as resp:
            return resp.headers.get_content_type()
    except Exception as exc:
        logging.info(f"Could not detect content type for {url}: {exc}")
        return None


def should_render_html(source, render_html):
    """Decide whether the source should be rendered to PDF before OCR."""
    if render_html == "never":
        return False
    if render_html == "always":
        return True
    if source == "-":
        return False
    if is_html_path(source):
        return True
    if is_url(source):
        return url_content_type(source) == "text/html"
    return False


def render_html_to_pdf(source, timeout_seconds=30):
    """Render a local HTML file or URL to a temporary PDF path."""
    if source == "-":
        logging.error("HTML rendering is not supported for stdin.")
        sys.exit(1)
    if not is_url(source) and not os.path.exists(source):
        logging.error(f"'{source}' is not a valid URL or an existing file path.")
        sys.exit(1)

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        logging.error(
            "HTML rendering requires Playwright. Install it with "
            "`pip install 'mistral-ocr-tool[html]'` and then run "
            "`python -m playwright install chromium`."
        )
        sys.exit(1)

    target = source if is_url(source) else Path(source).resolve().as_uri()
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    pdf_path = tmp.name
    tmp.close()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page()
                page.goto(target, wait_until="load", timeout=timeout_seconds * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except PlaywrightError:
                    logging.info("Timed out waiting for network idle; rendering the loaded page.")
                page.emulate_media(media="screen")
                page.pdf(path=pdf_path, format="Letter", print_background=True)
            finally:
                browser.close()
    except PlaywrightError as exc:
        try:
            os.unlink(pdf_path)
        except OSError:
            pass
        logging.error(f"Failed to render HTML to PDF: {exc}")
        logging.error("If Chromium is not installed, run `python -m playwright install chromium`.")
        sys.exit(1)

    logging.info(f"Rendered HTML to temporary PDF: {pdf_path}")
    return pdf_path


def count_pages(source, pages_arg, render_html="auto", html_timeout=30):
    """Count pages that would be processed, without calling the API."""
    source = normalize_document_source(source)
    if should_render_html(source, render_html):
        pdf_path = render_html_to_pdf(source, timeout_seconds=html_timeout)
        try:
            reader = PdfReader(pdf_path)
            total = len(reader.pages)
        finally:
            os.unlink(pdf_path)
    elif source == "-":
        data = sys.stdin.buffer.read()
        if not data:
            logging.error("No data received from stdin.")
            sys.exit(1)
        try:
            reader = PdfReader(io.BytesIO(data))
            total = len(reader.pages)
        except Exception:
            # Not a PDF (image or other format) — assume 1 page
            total = 1
    elif is_url(source):
        ext = os.path.splitext(urlparse(source).path)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            total = 1
        else:
            logging.info(f"Downloading {source} to count pages...")
            with urlopen(source, timeout=30) as resp:
                data = resp.read()
            try:
                reader = PdfReader(io.BytesIO(data))
                total = len(reader.pages)
            except Exception:
                total = 1
    elif os.path.exists(source):
        ext = os.path.splitext(source)[1].lower()
        if ext in IMAGE_EXTENSIONS:
            total = 1
        elif ext == ".pdf":
            reader = PdfReader(source)
            total = len(reader.pages)
        else:
            logging.warning(f"Cannot count pages for '{ext}' files. Assuming 1 page.")
            total = 1
    else:
        logging.error(f"'{source}' is not a valid URL or an existing file path.")
        sys.exit(1)

    if pages_arg is not None:
        selected = parse_pages(pages_arg)
        return len([p for p in selected if p < total])
    return total


def get_doc_stem(source):
    """Get a filename stem from the document source for naming output files."""
    source = normalize_document_source(source)
    if source == "-":
        return "stdin"
    if is_url(source):
        path = urlparse(source).path
        return Path(path).stem or "document"
    return Path(source).stem


def save_to_directory(output_dir, response, doc_stem):
    """Save OCR response to a directory with markdown and image files."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    images_dir = out / "images"
    image_map = {}

    # Collect and save images
    for page in response.pages:
        for img in page.images or []:
            if img.image_base64:
                if not images_dir.exists():
                    images_dir.mkdir()
                img_filename = img.id
                img_path = images_dir / img_filename
                img_data = img.image_base64
                # Strip data URI prefix if present
                if "," in img_data[:100]:
                    img_data = img_data.split(",", 1)[1]
                img_path.write_bytes(base64.b64decode(img_data))
                image_map[img.id] = f"images/{img_filename}"
                logging.info(f"Saved image: {img_path}")

    # Build markdown with corrected image paths
    parts = []
    for page in response.pages:
        md = page.markdown
        for old_ref, new_path in image_map.items():
            md = md.replace(f"]({old_ref})", f"]({new_path})")
        parts.append(md)

    md_path = out / f"{doc_stem}.md"
    md_path.write_text("\n\n".join(parts))
    logging.info(f"Saved markdown: {md_path}")

    return md_path


def build_ocr_params(args):
    """Build the kwargs dict for client.ocr.process() from parsed args."""
    include_images = args.include_images or args.output_dir is not None
    params = {
        "model": args.model,
        "include_image_base64": include_images,
    }
    if not include_images and args.image_limit is None:
        params["image_limit"] = 0
    if args.pages is not None:
        params["pages"] = parse_pages(args.pages)
    if args.table_format is not None:
        params["table_format"] = args.table_format
    if args.extract_headers:
        params["extract_header"] = True
    if args.extract_footers:
        params["extract_footer"] = True
    if args.image_limit is not None:
        params["image_limit"] = args.image_limit
    if args.image_min_size is not None:
        params["image_min_size"] = args.image_min_size
    return params


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Extract text from documents using the Mistral OCR API.",
        epilog="Examples:\n"
               "  mistral-ocr document.pdf\n"
               "  mistral-ocr https://example.com/doc.pdf\n"
               "  mistral-ocr example.com/report\n"
               "  mistral-ocr doc.pdf --pages 0,2,5\n"
               "  mistral-ocr doc.pdf --json | jq '.pages[0].markdown'\n"
               "  mistral-ocr doc.pdf -o output/\n"
               "  mistral-ocr page.html\n"
               "  cat doc.pdf | mistral-ocr -\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "document_source",
        help="URL, bare domain URL, file path, or '-' to read from stdin.",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json",
        help="Output full JSON response instead of markdown.",
    )
    parser.add_argument(
        "-p", "--pages",
        help="Comma-separated list of page numbers to process (0-indexed).",
    )
    parser.add_argument(
        "--table-format", choices=["markdown", "html"],
        help="Table output format.",
    )
    parser.add_argument(
        "--extract-headers", action="store_true",
        help="Include page headers in output.",
    )
    parser.add_argument(
        "--extract-footers", action="store_true",
        help="Include page footers in output.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        help="Save markdown and images to this directory.",
    )
    parser.add_argument(
        "--include-images", action="store_true",
        help="Include images (requires --json or -o).",
    )
    parser.add_argument(
        "--image-limit", type=int,
        help="Maximum number of images to extract; use 0 to disable images. Requires image output unless set to 0.",
    )
    parser.add_argument(
        "--image-min-size", type=int,
        help="Minimum image dimension in pixels. Requires image output.",
    )
    parser.add_argument(
        "--model", default="mistral-ocr-latest",
        help="Model to use (default: mistral-ocr-latest).",
    )
    parser.add_argument(
        "--render-html", choices=["auto", "always", "never"], default="auto",
        help="Render HTML inputs to PDF before OCR (default: auto).",
    )
    parser.add_argument(
        "--html-timeout", type=int, default=30,
        help="Seconds to wait while rendering HTML (default: 30).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show page count and estimated cost without processing.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    if args.include_images and not args.output_json and not args.output_dir:
        parser.error("--include-images requires --json or -o/--output-dir")
    image_output = args.include_images or args.output_dir is not None
    if args.image_limit not in (None, 0) and not image_output:
        parser.error(
            "--image-limit N requires image output (-o/--output-dir or --json --include-images); "
            "use --image-limit 0 to disable images"
        )
    if args.image_min_size is not None and not image_output:
        parser.error("--image-min-size requires image output (-o/--output-dir or --json --include-images)")
    if args.html_timeout <= 0:
        parser.error("--html-timeout must be greater than 0")

    if args.dry_run:
        page_count = count_pages(
            args.document_source,
            args.pages,
            render_html=args.render_html,
            html_timeout=args.html_timeout,
        )
        cost = page_count * 0.002
        print(f"Pages: {page_count}")
        print(f"Estimated cost: ${cost:.4f}")
        return

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        logging.error("MISTRAL_API_KEY environment variable is not set.")
        sys.exit(1)

    client = Mistral(api_key=api_key)
    document = build_document(
        client,
        args.document_source,
        render_html=args.render_html,
        html_timeout=args.html_timeout,
    )
    ocr_params = build_ocr_params(args)

    logging.info("Processing document with Mistral OCR...")
    response = client.ocr.process(document=document, **ocr_params)

    if args.output_dir:
        doc_stem = get_doc_stem(args.document_source)
        md_path = save_to_directory(args.output_dir, response, doc_stem)
        print(md_path)
    elif args.output_json:
        print(json.dumps(response.model_dump(), indent=2, default=str))
    else:
        print("\n\n".join(page.markdown for page in response.pages))


if __name__ == "__main__":
    main()

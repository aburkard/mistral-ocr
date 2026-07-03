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

try:
    from mistralai import Mistral
except ImportError:
    from mistralai.client import Mistral
from dotenv import load_dotenv
from pypdf import PdfReader


def is_url(s):
    parsed = urlparse(s)
    return parsed.scheme in ("http", "https")


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


def build_document(client, source):
    """Resolve a source (URL, file path, or '-' for stdin) into an API document dict."""
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


def count_pages(source, pages_arg):
    """Count pages that would be processed, without calling the API."""
    if source == "-":
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
            import urllib.request
            logging.info(f"Downloading {source} to count pages...")
            with urllib.request.urlopen(source, timeout=30) as resp:
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
               "  mistral-ocr doc.pdf --pages 0,2,5\n"
               "  mistral-ocr doc.pdf --json | jq '.pages[0].markdown'\n"
               "  mistral-ocr doc.pdf -o output/\n"
               "  cat doc.pdf | mistral-ocr -\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "document_source",
        help="URL, file path, or '-' to read from stdin.",
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

    if args.dry_run:
        page_count = count_pages(args.document_source, args.pages)
        cost = page_count * 0.002
        print(f"Pages: {page_count}")
        print(f"Estimated cost: ${cost:.4f}")
        return

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        logging.error("MISTRAL_API_KEY environment variable is not set.")
        sys.exit(1)

    client = Mistral(api_key=api_key)
    document = build_document(client, args.document_source)
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

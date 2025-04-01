import os
import argparse
from mistralai import Mistral
from dotenv import load_dotenv
import validators
import logging


def main():
    load_dotenv()

    # Configure logging - will be updated based on args
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

    # --- Argument Parsing ---
    parser = argparse.ArgumentParser(description="Process a document URL or file path with Mistral OCR.")
    parser.add_argument("document_source", help="The URL or file path of the document to process.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging (INFO level).")
    args = parser.parse_args()

    # Update logging level if verbose flag is set
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    api_key = os.environ["MISTRAL_API_KEY"]
    client = Mistral(api_key=api_key)

    # Determine if the input is a URL or a file path and prepare the document data dictionary
    if validators.url(args.document_source):
        document_data = {"type": "document_url", "document_url": args.document_source}
    elif os.path.exists(args.document_source):
        logging.info(f"Uploading file: {args.document_source}...")
        try:
            file_name = os.path.basename(args.document_source)
            with open(args.document_source, "rb") as f:
                uploaded_file = client.files.upload(file={
                    "file_name": file_name,
                    "content": f,
                }, purpose="ocr")
            logging.info(f"File uploaded successfully. ID: {uploaded_file.id}")

            signed_url = client.files.get_signed_url(file_id=uploaded_file.id)
            logging.info("Signed URL obtained.")

            document_data = {"type": "document_url", "document_url": signed_url.url}
        except Exception as e:
            logging.error(f"Error during file upload or getting signed URL: {e}")
            exit(1)
    else:
        logging.error(f"Error: '{args.document_source}' is not a valid URL or an existing file path.")
        exit(1)

    logging.info("Processing document with Mistral OCR...")
    ocr_response = client.ocr.process(model="mistral-ocr-latest", document=document_data, include_image_base64=True)

    delim = "\n\n"
    s = delim.join([page.markdown for page in ocr_response.pages])

    print(s)


if __name__ == "__main__":
    main()

import os
import argparse
# Removed unused Pydantic model imports
from mistralai import Mistral
from dotenv import load_dotenv
import validators
import logging  # Add logging import

load_dotenv()

# Configure logging - will be updated based on args
# Set default level to WARNING, will be changed to INFO if verbose is True
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Argument Parsing ---
parser = argparse.ArgumentParser(description="Process a document URL or file path with Mistral OCR.")
# Changed argument name to be more general
parser.add_argument("document_source", help="The URL or file path of the document to process.")
parser.add_argument("-v", "--verbose", action="store_true",
                    help="Enable verbose logging (INFO level).")  # Add verbose flag
args = parser.parse_args()

# Update logging level if verbose flag is set
if args.verbose:
    logging.getLogger().setLevel(logging.INFO)
# --- End Argument Parsing ---

api_key = os.environ["MISTRAL_API_KEY"]
client = Mistral(api_key=api_key)

# Determine if the input is a URL or a file path and prepare the document data dictionary
if validators.url(args.document_source):
    # Use a dictionary for URLs directly
    document_data = {"type": "document_url", "document_url": args.document_source}
elif os.path.exists(args.document_source):
    # For local files, upload first and get a signed URL
    logging.info(f"Uploading file: {args.document_source}...")  # Use logging.info
    try:
        # Extract filename for the upload metadata
        file_name = os.path.basename(args.document_source)
        with open(args.document_source, "rb") as f:
            uploaded_file = client.files.upload(file={
                "file_name": file_name,
                "content": f,
            }, purpose="ocr")
        logging.info(f"File uploaded successfully. ID: {uploaded_file.id}")  # Use logging.info

        # Get the signed URL for the uploaded file
        signed_url = client.files.get_signed_url(file_id=uploaded_file.id)
        logging.info("Signed URL obtained.")  # Use logging.info

        # Use the signed URL in the document data dictionary
        document_data = {"type": "document_url", "document_url": signed_url.url}
    except Exception as e:
        logging.error(f"Error during file upload or getting signed URL: {e}")  # Use logging.error
        exit(1)
else:
    # Handle the case where the input is neither a valid URL nor an existing file path
    logging.error(f"Error: '{args.document_source}' is not a valid URL or an existing file path.")  # Use logging.error
    exit(1)  # Exit if the source is invalid

logging.info("Processing document with Mistral OCR...")  # Use logging.info
ocr_response = client.ocr.process(
    model="mistral-ocr-latest",
    document=document_data,  # Pass the dictionary
    include_image_base64=True
)  # Setting this True might not be needed for PDFs, but keeping it based on your original code

delim = "\n\n"
s = delim.join([page.markdown for page in ocr_response.pages])

# You'll probably want to do something with the response, like print it
print(s)  # Keep this print for the final output

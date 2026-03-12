import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from mistral_ocr import is_url, parse_pages, build_ocr_params, count_pages, main


class TestIsUrl:
    def test_http(self):
        assert is_url("http://example.com/doc.pdf") is True

    def test_https(self):
        assert is_url("https://example.com/doc.pdf") is True

    def test_file_path(self):
        assert is_url("/tmp/doc.pdf") is False

    def test_relative_path(self):
        assert is_url("doc.pdf") is False

    def test_stdin_dash(self):
        assert is_url("-") is False

    def test_ftp(self):
        assert is_url("ftp://example.com/doc.pdf") is False


class TestParsePages:
    def test_single_page(self):
        assert parse_pages("0") == [0]

    def test_multiple_pages(self):
        assert parse_pages("0,2,5") == [0, 2, 5]

    def test_spaces(self):
        assert parse_pages("0, 2, 5") == [0, 2, 5]

    def test_trailing_comma(self):
        assert parse_pages("0,2,") == [0, 2]

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_pages("abc")


class TestBuildOcrParams:
    def _make_args(self, **overrides):
        defaults = {
            "model": "mistral-ocr-latest",
            "pages": None,
            "table_format": None,
            "extract_headers": False,
            "extract_footers": False,
            "include_images": False,
            "image_limit": None,
            "image_min_size": None,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_defaults(self):
        params = build_ocr_params(self._make_args())
        assert params["model"] == "mistral-ocr-latest"
        assert params["include_image_base64"] is False
        assert "pages" not in params
        assert "table_format" not in params
        assert "extract_header" not in params
        assert "extract_footer" not in params

    def test_pages(self):
        params = build_ocr_params(self._make_args(pages="0,3"))
        assert params["pages"] == [0, 3]

    def test_table_format(self):
        params = build_ocr_params(self._make_args(table_format="html"))
        assert params["table_format"] == "html"

    def test_extract_headers_footers(self):
        params = build_ocr_params(self._make_args(extract_headers=True, extract_footers=True))
        assert params["extract_header"] is True
        assert params["extract_footer"] is True

    def test_include_images(self):
        params = build_ocr_params(self._make_args(include_images=True))
        assert params["include_image_base64"] is True

    def test_image_limit(self):
        params = build_ocr_params(self._make_args(image_limit=5))
        assert params["image_limit"] == 5

    def test_image_min_size(self):
        params = build_ocr_params(self._make_args(image_min_size=100))
        assert params["image_min_size"] == 100

    def test_custom_model(self):
        params = build_ocr_params(self._make_args(model="mistral-ocr-2512"))
        assert params["model"] == "mistral-ocr-2512"


class TestMainOutput:
    def _mock_response(self):
        page1 = MagicMock()
        page1.markdown = "# Page 1\nHello"
        page2 = MagicMock()
        page2.markdown = "# Page 2\nWorld"
        response = MagicMock()
        response.pages = [page1, page2]
        response.model_dump.return_value = {
            "pages": [
                {"index": 0, "markdown": "# Page 1\nHello"},
                {"index": 1, "markdown": "# Page 2\nWorld"},
            ],
            "model": "mistral-ocr-latest",
        }
        return response

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"})
    @patch("mistral_ocr.Mistral")
    def test_markdown_output(self, mock_mistral_cls, capsys):
        mock_client = MagicMock()
        mock_mistral_cls.return_value = mock_client
        mock_client.ocr.process.return_value = self._mock_response()

        with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf"]):
            main()

        captured = capsys.readouterr()
        assert "# Page 1" in captured.out
        assert "# Page 2" in captured.out
        assert captured.out.strip() == "# Page 1\nHello\n\n# Page 2\nWorld"

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"})
    @patch("mistral_ocr.Mistral")
    def test_json_output(self, mock_mistral_cls, capsys):
        mock_client = MagicMock()
        mock_mistral_cls.return_value = mock_client
        mock_client.ocr.process.return_value = self._mock_response()

        with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--json"]):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["model"] == "mistral-ocr-latest"
        assert len(data["pages"]) == 2

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"})
    @patch("mistral_ocr.Mistral")
    def test_pages_flag_passed_to_api(self, mock_mistral_cls):
        mock_client = MagicMock()
        mock_mistral_cls.return_value = mock_client
        mock_client.ocr.process.return_value = self._mock_response()

        with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--pages", "0,2"]):
            main()

        call_kwargs = mock_client.ocr.process.call_args
        assert call_kwargs.kwargs.get("pages") == [0, 2] or call_kwargs[1].get("pages") == [0, 2]

    @patch("mistral_ocr.load_dotenv")
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key_exits(self, mock_dotenv):
        with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf"]):
            with pytest.raises(SystemExit):
                main()


class TestCountPages:
    def test_local_image_file(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"fake png data")
        assert count_pages(str(img), None) == 1

    def test_local_image_with_pages_arg(self, tmp_path):
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake jpg data")
        # Only 1 page, requesting page 0 = 1 page
        assert count_pages(str(img), "0") == 1
        # Requesting page 1 = out of range, 0 pages
        assert count_pages(str(img), "1") == 0

    def test_local_pdf(self, tmp_path):
        # Create a minimal valid PDF with 2 pages
        from pypdf import PdfWriter
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_blank_page(width=72, height=72)
        pdf_path = tmp_path / "test.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)
        assert count_pages(str(pdf_path), None) == 2

    def test_local_pdf_with_pages_arg(self, tmp_path):
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(width=72, height=72)
        pdf_path = tmp_path / "test.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)
        assert count_pages(str(pdf_path), "0,2,4") == 3
        assert count_pages(str(pdf_path), "0,2,99") == 2  # page 99 out of range

    def test_unknown_extension(self, tmp_path):
        doc = tmp_path / "test.docx"
        doc.write_bytes(b"fake docx data")
        assert count_pages(str(doc), None) == 1

    def test_nonexistent_file_exits(self):
        with pytest.raises(SystemExit):
            count_pages("/nonexistent/file.pdf", None)

    def test_url_image(self):
        assert count_pages("https://example.com/photo.jpg", None) == 1

    def test_url_image_jpeg(self):
        assert count_pages("https://example.com/photo.jpeg", None) == 1


class TestDryRun:
    def test_dry_run_local_pdf(self, tmp_path, capsys):
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=72, height=72)
        pdf_path = tmp_path / "test.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        with patch("sys.argv", ["mistral-ocr", str(pdf_path), "--dry-run"]):
            main()

        captured = capsys.readouterr()
        assert "Pages: 10" in captured.out
        assert "Estimated cost: $0.0200" in captured.out

    def test_dry_run_with_pages(self, tmp_path, capsys):
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(10):
            writer.add_blank_page(width=72, height=72)
        pdf_path = tmp_path / "test.pdf"
        with open(pdf_path, "wb") as f:
            writer.write(f)

        with patch("sys.argv", ["mistral-ocr", str(pdf_path), "--dry-run", "--pages", "0,1,2"]):
            main()

        captured = capsys.readouterr()
        assert "Pages: 3" in captured.out
        assert "Estimated cost: $0.0060" in captured.out

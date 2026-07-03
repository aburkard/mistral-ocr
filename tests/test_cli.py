import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from mistral_ocr import (
    is_url, looks_like_bare_url, normalize_document_source, is_html_path,
    should_render_html, parse_pages, build_document, build_ocr_params,
    count_pages, get_doc_stem, save_to_directory, main,
)


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


class TestNormalizeDocumentSource:
    def test_bare_domain(self):
        assert looks_like_bare_url("espn.com") is True
        assert normalize_document_source("espn.com") == "https://espn.com"

    def test_bare_domain_with_path(self):
        assert looks_like_bare_url("example.com/report") is True
        assert normalize_document_source("example.com/report") == "https://example.com/report"

    def test_explicit_url_unchanged(self):
        assert normalize_document_source("http://example.com") == "http://example.com"
        assert normalize_document_source("https://example.com") == "https://example.com"

    def test_missing_local_html_is_not_bare_url(self):
        assert looks_like_bare_url("report.html") is False
        assert normalize_document_source("report.html") == "report.html"

    def test_local_file_is_not_bare_url(self, tmp_path):
        local_file = tmp_path / "espn.com"
        local_file.write_text("content")
        assert looks_like_bare_url(str(local_file)) is False
        assert normalize_document_source(str(local_file)) == str(local_file)


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


class TestHtmlRendering:
    def test_is_html_path(self):
        assert is_html_path("report.html") is True
        assert is_html_path("report.htm") is True
        assert is_html_path("report.pdf") is False
        assert is_html_path("https://example.com/report.html") is True

    def test_should_render_html_modes(self):
        assert should_render_html("report.html", "auto") is True
        assert should_render_html("report.html", "never") is False
        assert should_render_html("report.pdf", "always") is True

    def test_should_render_html_uses_url_content_type(self):
        with patch("mistral_ocr.url_content_type", return_value="text/html"):
            assert should_render_html("https://example.com/report", "auto") is True
        with patch("mistral_ocr.url_content_type", return_value="application/pdf"):
            assert should_render_html("https://example.com/report", "auto") is False

    def test_should_render_url_with_unknown_content_type_and_no_extension(self):
        with patch("mistral_ocr.url_content_type", return_value=None):
            assert should_render_html("https://news.ycombinator.com", "auto") is True

    def test_should_not_render_direct_document_url_extension(self):
        with patch("mistral_ocr.url_content_type") as mock_content_type:
            assert should_render_html("https://example.com/report.pdf", "auto") is False
        mock_content_type.assert_not_called()

    def test_should_not_render_direct_document_content_type_without_extension(self):
        with patch("mistral_ocr.url_content_type", return_value="application/pdf"):
            assert should_render_html("https://example.com/report", "auto") is False

    def test_bare_url_uses_content_type_after_normalization(self):
        with patch("mistral_ocr.url_content_type", return_value="text/html") as mock_content_type:
            assert should_render_html(normalize_document_source("espn.com"), "auto") is True
        mock_content_type.assert_called_once_with("https://espn.com")

    def test_bare_url_renders_when_content_type_probe_fails(self):
        with patch("mistral_ocr.url_content_type", return_value=None):
            assert should_render_html("news.ycombinator.com", "auto") is True

    def test_build_document_accepts_bare_url(self):
        document = build_document(MagicMock(), "espn.com", render_html="never")
        assert document == {"type": "document_url", "document_url": "https://espn.com"}

    def test_build_document_renders_html_before_upload(self, tmp_path):
        html_path = tmp_path / "report.html"
        html_path.write_text("<html><body>Hello</body></html>")
        pdf_path = tmp_path / "rendered.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")

        mock_client = MagicMock()
        with patch("mistral_ocr.render_html_to_pdf", return_value=str(pdf_path)) as mock_render:
            with patch("mistral_ocr.upload_file", return_value={"type": "document_url", "document_url": "signed"}) as mock_upload:
                document = build_document(mock_client, str(html_path))

        assert document == {"type": "document_url", "document_url": "signed"}
        mock_render.assert_called_once_with(str(html_path), timeout_seconds=30)
        mock_upload.assert_called_once()
        assert mock_upload.call_args.kwargs["file_name"] == "report.pdf"
        assert not pdf_path.exists()

    def test_build_document_can_skip_html_rendering(self):
        document = build_document(MagicMock(), "https://example.com/report.html", render_html="never")
        assert document == {"type": "document_url", "document_url": "https://example.com/report.html"}

    def test_count_pages_for_rendered_html(self, tmp_path):
        from pypdf import PdfWriter

        html_path = tmp_path / "report.html"
        html_path.write_text("<html><body>Hello</body></html>")
        pdf_path = tmp_path / "rendered.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_blank_page(width=72, height=72)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        with patch("mistral_ocr.render_html_to_pdf", return_value=str(pdf_path)):
            assert count_pages(str(html_path), None) == 2
        assert not pdf_path.exists()

    def test_missing_local_html_exits_before_playwright_import(self):
        with pytest.raises(SystemExit):
            build_document(MagicMock(), "/tmp/does-not-exist.html")


class TestBuildOcrParams:
    def _make_args(self, **overrides):
        defaults = {
            "model": "mistral-ocr-latest",
            "pages": None,
            "table_format": None,
            "extract_headers": False,
            "extract_footers": False,
            "include_images": False,
            "output_dir": None,
            "image_limit": None,
            "image_min_size": None,
        }
        defaults.update(overrides)
        return MagicMock(**defaults)

    def test_defaults(self):
        params = build_ocr_params(self._make_args())
        assert params["model"] == "mistral-ocr-latest"
        assert params["include_image_base64"] is False
        assert params["image_limit"] == 0
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
        assert "image_limit" not in params

    def test_image_limit(self):
        params = build_ocr_params(self._make_args(image_limit=5))
        assert params["image_limit"] == 5

    def test_image_min_size(self):
        params = build_ocr_params(self._make_args(image_min_size=100))
        assert params["image_min_size"] == 100

    def test_custom_model(self):
        params = build_ocr_params(self._make_args(model="mistral-ocr-2512"))
        assert params["model"] == "mistral-ocr-2512"

    def test_output_dir_implies_include_images(self):
        params = build_ocr_params(self._make_args(output_dir="out/"))
        assert params["include_image_base64"] is True
        assert "image_limit" not in params


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


class TestGetDocStem:
    def test_local_file(self):
        assert get_doc_stem("/path/to/report.pdf") == "report"

    def test_url(self):
        assert get_doc_stem("https://example.com/docs/paper.pdf") == "paper"

    def test_stdin(self):
        assert get_doc_stem("-") == "stdin"

    def test_url_no_extension(self):
        assert get_doc_stem("https://example.com/document") == "document"


class TestSaveToDirectory:
    def _mock_response_with_images(self):
        import base64
        img_data = base64.b64encode(b"\x89PNG\r\n\x1a\nfake").decode()

        img = MagicMock()
        img.id = "img-0.png"
        img.image_base64 = img_data

        page = MagicMock()
        page.markdown = "# Title\n![img-0.png](img-0.png)\nSome text"
        page.images = [img]

        response = MagicMock()
        response.pages = [page]
        return response

    def _mock_response_no_images(self):
        page = MagicMock()
        page.markdown = "# Title\nJust text"
        page.images = []

        response = MagicMock()
        response.pages = [page]
        return response

    def test_saves_markdown(self, tmp_path):
        response = self._mock_response_no_images()
        md_path = save_to_directory(str(tmp_path / "out"), response, "doc")
        assert md_path.exists()
        assert md_path.name == "doc.md"
        assert "Just text" in md_path.read_text()

    def test_saves_images(self, tmp_path):
        response = self._mock_response_with_images()
        md_path = save_to_directory(str(tmp_path / "out"), response, "doc")
        images_dir = tmp_path / "out" / "images"
        assert images_dir.exists()
        assert (images_dir / "img-0.png").exists()

    def test_fixes_image_refs_in_markdown(self, tmp_path):
        response = self._mock_response_with_images()
        md_path = save_to_directory(str(tmp_path / "out"), response, "doc")
        content = md_path.read_text()
        assert "](images/img-0.png)" in content
        assert "](img-0.png)" not in content


class TestIncludeImagesValidation:
    def test_include_images_without_json_or_output_dir_errors(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--include-images"]):
                main()

    def test_html_timeout_must_be_positive(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--html-timeout", "0"]):
                main()

    def test_image_limit_without_image_output_errors(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--image-limit", "5"]):
                main()

    def test_image_min_size_without_image_output_errors(self):
        with pytest.raises(SystemExit):
            with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--image-min-size", "100"]):
                main()

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"})
    @patch("mistral_ocr.Mistral")
    def test_image_limit_zero_without_image_output_ok(self, mock_mistral_cls, capsys):
        mock_client = MagicMock()
        mock_mistral_cls.return_value = mock_client
        page = MagicMock()
        page.markdown = "text"
        page.images = []
        response = MagicMock()
        response.pages = [page]
        mock_client.ocr.process.return_value = response

        with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--image-limit", "0"]):
            main()

        captured = capsys.readouterr()
        assert captured.out.strip() == "text"
        assert mock_client.ocr.process.call_args.kwargs["image_limit"] == 0

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"})
    @patch("mistral_ocr.Mistral")
    def test_include_images_with_json_ok(self, mock_mistral_cls, capsys):
        mock_client = MagicMock()
        mock_mistral_cls.return_value = mock_client
        page = MagicMock()
        page.markdown = "text"
        page.images = []
        response = MagicMock()
        response.pages = [page]
        response.model_dump.return_value = {"pages": [], "model": "m"}
        mock_client.ocr.process.return_value = response

        with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "--json", "--include-images"]):
            main()

        captured = capsys.readouterr()
        assert "pages" in captured.out

    @patch.dict(os.environ, {"MISTRAL_API_KEY": "test-key"})
    @patch("mistral_ocr.Mistral")
    def test_output_dir_mode(self, mock_mistral_cls, tmp_path, capsys):
        mock_client = MagicMock()
        mock_mistral_cls.return_value = mock_client
        page = MagicMock()
        page.markdown = "# Hello"
        page.images = []
        response = MagicMock()
        response.pages = [page]
        mock_client.ocr.process.return_value = response

        out_dir = str(tmp_path / "result")
        with patch("sys.argv", ["mistral-ocr", "https://example.com/doc.pdf", "-o", out_dir]):
            main()

        captured = capsys.readouterr()
        assert "doc.md" in captured.out
        assert (tmp_path / "result" / "doc.md").exists()

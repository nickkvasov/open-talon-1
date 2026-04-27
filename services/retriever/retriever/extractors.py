from __future__ import annotations

from html.parser import HTMLParser

from .providers import ExtractedDocument, ExtractedSegment


def _filename_ext(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower()


def _decode_text(payload: bytes) -> str:
    return payload.decode("utf-8", errors="replace")


class PlainTextExtractor:
    _extensions = {"txt", "md", "markdown", "json", "yaml", "yml", "csv", "tsv"}
    _content_types = {
        "text/plain",
        "text/markdown",
        "application/json",
        "application/yaml",
        "text/csv",
    }

    def supports(self, *, content_type: str | None, filename: str | None) -> bool:
        normalized = content_type.split(";", 1)[0].strip().lower() if content_type else None
        return normalized in self._content_types or _filename_ext(filename) in self._extensions

    def extract(
        self,
        payload: bytes,
        *,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> ExtractedDocument:
        text = _decode_text(payload)
        return ExtractedDocument(
            segments=[ExtractedSegment(text=text)],
            metadata={"content_type": content_type, "filename": filename},
        )


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)
                self._parts.append(" ")

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self._parts).splitlines()]
        return "\n".join(line for line in lines if line)


class HtmlTextExtractor:
    def supports(self, *, content_type: str | None, filename: str | None) -> bool:
        normalized = content_type.split(";", 1)[0].strip().lower() if content_type else None
        return normalized in {"text/html", "application/xhtml+xml"} or _filename_ext(filename) in {
            "html",
            "htm",
            "xhtml",
        }

    def extract(
        self,
        payload: bytes,
        *,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> ExtractedDocument:
        parser = _VisibleTextParser()
        parser.feed(_decode_text(payload))
        return ExtractedDocument(
            segments=[ExtractedSegment(text=parser.text())],
            metadata={"content_type": content_type, "filename": filename},
        )


class PdfTextExtractor:
    def supports(self, *, content_type: str | None, filename: str | None) -> bool:
        normalized = content_type.split(";", 1)[0].strip().lower() if content_type else None
        return normalized == "application/pdf" or _filename_ext(filename) == "pdf"

    def extract(
        self,
        payload: bytes,
        *,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> ExtractedDocument:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF extraction requires PyMuPDF") from exc
        segments: list[ExtractedSegment] = []
        with fitz.open(stream=payload, filetype="pdf") as document:
            for index, page in enumerate(document, start=1):
                text = page.get_text("text").strip()
                if text:
                    segments.append(
                        ExtractedSegment(
                            text=text,
                            page_start=index,
                            page_end=index,
                            metadata={"page": index},
                        )
                    )
        return ExtractedDocument(
            segments=segments,
            metadata={"content_type": content_type, "filename": filename},
        )

    def render_pages(self, payload: bytes, *, dpi: int = 160) -> list[tuple[int, bytes]]:
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF page rendering requires PyMuPDF") from exc
        rendered: list[tuple[int, bytes]] = []
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        with fitz.open(stream=payload, filetype="pdf") as document:
            for index, page in enumerate(document, start=1):
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                rendered.append((index, pixmap.tobytes("png")))
        return rendered


class ExtractorRegistry:
    def __init__(self, extractors: list[object] | None = None) -> None:
        self._extractors = extractors or [
            HtmlTextExtractor(),
            PdfTextExtractor(),
            PlainTextExtractor(),
        ]

    def extract(
        self,
        payload: bytes,
        *,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> ExtractedDocument:
        for extractor in self._extractors:
            if extractor.supports(content_type=content_type, filename=filename):
                return extractor.extract(payload, content_type=content_type, filename=filename)
        return PlainTextExtractor().extract(payload, content_type=content_type, filename=filename)

    def render_pdf_pages(self, payload: bytes) -> list[tuple[int, bytes]]:
        return PdfTextExtractor().render_pages(payload)

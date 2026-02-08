from __future__ import annotations

from datetime import datetime
from typing import Iterable


class PdfService:
    def _sanitize(self, text: str) -> str:
        safe = (text or "").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return safe.encode("ascii", "replace").decode("ascii")

    def _chunk_lines(self, lines: list[str], per_page: int = 46) -> list[list[str]]:
        if not lines:
            return [["(empty)"]]
        pages: list[list[str]] = []
        for idx in range(0, len(lines), per_page):
            pages.append(lines[idx : idx + per_page])
        return pages

    def _build_content_stream(self, lines: list[str]) -> bytes:
        commands: list[str] = []
        y = 810
        for idx, line in enumerate(lines):
            font_size = 14 if idx == 0 else 10
            commands.append(f"BT /F1 {font_size} Tf 40 {y} Td ({self._sanitize(line)}) Tj ET")
            y -= 16
            if y < 40:
                break
        return "\n".join(commands).encode("latin-1", "replace")

    def build_simple_report_pdf(self, title: str, lines: Iterable[str]) -> bytes:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        all_lines = [title, f"Generated at: {now}", ""] + [str(line) for line in lines]
        pages = self._chunk_lines(all_lines)

        total_objects = 3 + (2 * len(pages))
        objects: list[tuple[int, bytes]] = []

        # 1: Catalog
        objects.append((1, b"<< /Type /Catalog /Pages 2 0 R >>"))

        # 2: Pages root
        kids = " ".join(f"{4 + idx * 2} 0 R" for idx in range(len(pages)))
        objects.append((2, f"<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>".encode("latin-1")))

        # 3: Font
        objects.append((3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

        for idx, page_lines in enumerate(pages):
            page_obj_id = 4 + idx * 2
            content_obj_id = 5 + idx * 2
            page_obj = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_obj_id} 0 R >>"
            ).encode("latin-1")
            objects.append((page_obj_id, page_obj))

            stream = self._build_content_stream(page_lines)
            content_obj = (
                f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
                + stream
                + b"\nendstream"
            )
            objects.append((content_obj_id, content_obj))

        objects = sorted(objects, key=lambda x: x[0])

        out = bytearray()
        out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0] * (total_objects + 1)

        for obj_id, obj_content in objects:
            offsets[obj_id] = len(out)
            out.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
            out.extend(obj_content)
            out.extend(b"\nendobj\n")

        xref_start = len(out)
        out.extend(f"xref\n0 {total_objects + 1}\n".encode("latin-1"))
        out.extend(b"0000000000 65535 f \n")
        for obj_id in range(1, total_objects + 1):
            out.extend(f"{offsets[obj_id]:010} 00000 n \n".encode("latin-1"))

        trailer = (
            f"trailer\n<< /Size {total_objects + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF\n"
        )
        out.extend(trailer.encode("latin-1"))
        return bytes(out)


pdf_service = PdfService()

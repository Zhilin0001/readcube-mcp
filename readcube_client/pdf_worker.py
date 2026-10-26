"""Isolated text parser. No network, credentials, or library mutation."""

import json
import sys


def main():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    except (ImportError, ValueError, OSError):
        pass
    from pypdf import PdfReader

    try:
        reader = PdfReader(sys.argv[1])
        if reader.is_encrypted:
            raise ValueError("encrypted")
        if len(reader.pages) > 1000:
            raise ValueError("page_limit")
        pages, total, truncated = [], 0, False
        for page in reader.pages:
            text = page.extract_text() or ""
            if total + len(text) > 5_000_000:
                text = text[: max(0, 5_000_000 - total)]
                truncated = True
            pages.append(text)
            total += len(text)
            if truncated:
                break
        result = {
            "pages": pages,
            "page_count": len(reader.pages),
            "truncated": truncated,
            "ocr_required": not any(s.strip() for s in pages),
        }
    except Exception:  # noqa: BLE001 - isolate all failures of an untrusted document parser
        result = {"error": "PDF is encrypted, malformed, or exceeds parser limits"}
    with open(sys.argv[2], "w", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False)


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pypdf import PdfReader


@dataclass
class ParsedDocument:
    metadata: dict[str, Any]
    chunks: list[dict[str, Any]]


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "document"


def extract_year(text: str, config: dict[str, Any]) -> int | None:
    year_pattern = re.compile(config["patterns"]["year_regex"])
    match = year_pattern.search(text)
    if not match:
        return None
    year_match = re.search(r"(19|20)\d{2}", match.group(0))
    return int(year_match.group(0)) if year_match else None


def extract_year_range(text: str, config: dict[str, Any]) -> str | None:
    pattern = re.compile(config["patterns"]["year_range_regex"])
    match = pattern.search(text)
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(0)).replace("至", "-").replace("—", "-").replace("–", "-")


def infer_plan_type(text: str, config: dict[str, Any]) -> str | None:
    for plan_type, keywords in config["patterns"]["plan_type_keywords"].items():
        if any(keyword in text for keyword in keywords):
            return plan_type
    return None


def infer_plan_level(text: str, config: dict[str, Any]) -> str | None:
    for plan_level, keywords in config["patterns"]["plan_level_keywords"].items():
        if any(keyword in text for keyword in keywords):
            return plan_level
    return None


def infer_region(text: str, config: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    found = [item for item in config["lexicons"]["region_hints"] if item in text]
    region = found[0] if found else None
    province = next((item for item in found if item.endswith("省")), None)
    city = next((item for item in found if item.endswith("市")), None)
    return region or city or province, province, city


def clean_line(line: str) -> str:
    line = line.replace("\u3000", " ")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def extract_text_by_page(pdf_path: Path) -> list[dict[str, Any]]:
    reader = PdfReader(str(pdf_path))
    return [{"page": index, "text": page.extract_text() or ""} for index, page in enumerate(reader.pages, start=1)]


def detect_repeated_edge_lines(page_texts: list[dict[str, Any]]) -> set[str]:
    top_counter: Counter[str] = Counter()
    bottom_counter: Counter[str] = Counter()
    for page in page_texts:
        lines = [clean_line(line) for line in page["text"].splitlines() if clean_line(line)]
        for line in lines[:2]:
            top_counter[line] += 1
        for line in lines[-2:]:
            bottom_counter[line] += 1

    threshold = max(2, len(page_texts) // 3) if page_texts else 2
    repeated = {line for line, count in top_counter.items() if count >= threshold}
    repeated.update({line for line, count in bottom_counter.items() if count >= threshold})
    return repeated


def normalize_pages(page_texts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    repeated_lines = detect_repeated_edge_lines(page_texts)
    cleaned_pages: list[dict[str, Any]] = []
    for page in page_texts:
        lines = [clean_line(line) for line in page["text"].splitlines()]
        kept = [line for line in lines if line and line not in repeated_lines]
        normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
        cleaned_pages.append({"page": page["page"], "text": normalized})
    return cleaned_pages, bool(repeated_lines)


def iter_sections(cleaned_pages: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    patterns = [re.compile(pattern) for pattern in config["patterns"]["chapter_regexes"]]
    sections: list[dict[str, Any]] = []
    current_heading = "未识别章节"
    current_lines: list[str] = []
    current_page_start = cleaned_pages[0]["page"] if cleaned_pages else 1

    def flush(page_end: int) -> None:
        nonlocal current_lines, current_heading, current_page_start
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(
                {
                    "heading": current_heading,
                    "page_start": current_page_start,
                    "page_end": page_end,
                    "text": text,
                }
            )
        current_lines = []

    for page in cleaned_pages:
        lines = [line.strip() for line in page["text"].splitlines() if line.strip()]
        for line in lines:
            if any(pattern.search(line) for pattern in patterns):
                flush(page["page"])
                current_heading = line[:120]
                current_page_start = page["page"]
            current_lines.append(line)

    if cleaned_pages:
        flush(cleaned_pages[-1]["page"])
    return sections


def extract_keywords(text: str, config: dict[str, Any], limit: int = 8) -> list[str]:
    matched = [term for term in config["lexicons"]["planning_terms"] if term in text]
    if matched:
        return matched[:limit]

    words = re.findall(r"[\u4e00-\u9fff]{2,8}", text)
    counts = Counter(words)
    keywords: list[str] = []
    for word, _ in counts.most_common(limit * 2):
        if len(word) >= int(config["processing"]["min_keyword_length"]) and word not in keywords:
            keywords.append(word)
        if len(keywords) >= limit:
            break
    return keywords


def split_chunks(sections: list[dict[str, Any]], doc_id: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    max_chars = int(config["processing"]["chunk_size"])
    overlap = int(config["processing"]["chunk_overlap"])
    chunks: list[dict[str, Any]] = []
    chunk_index = 1
    for section in sections:
        text = section["text"]
        start = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            snippet = text[start:end].strip()
            if not snippet:
                break
            chunks.append(
                {
                    "id": f"{doc_id}-c{chunk_index:04d}",
                    "doc_id": doc_id,
                    "chunk_index": chunk_index,
                    "chapter_path": [section["heading"]],
                    "heading": section["heading"],
                    "page_start": section["page_start"],
                    "page_end": section["page_end"],
                    "text": snippet,
                    "text_length": len(snippet),
                    "keywords": extract_keywords(snippet, config),
                    "tags": ["章节正文"],
                    "chunk_type": "paragraph",
                    "is_appendix": "附录" in section["heading"],
                    "is_table_like": False,
                }
            )
            chunk_index += 1
            if end >= len(text):
                break
            start = max(0, end - overlap)
    return chunks


def summarize_text(text: str, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


def build_doc_id(file_stem: str, year: int | None, plan_type: str | None) -> str:
    return f"{slugify(file_stem)}-{slugify(plan_type or 'plan')}-{year or 'unknown'}-v1"


def parse_pdf(pdf_path: Path, config_path: Path, source_rel_path: str | None = None) -> ParsedDocument:
    config = load_config(config_path)
    page_texts = extract_text_by_page(pdf_path)
    cleaned_pages, header_footer_cleaned = normalize_pages(page_texts)
    all_text = "\n\n".join(page["text"] for page in cleaned_pages if page["text"])

    filename_text = pdf_path.stem
    year = extract_year(filename_text, config) or extract_year(all_text[:5000], config)
    year_range = extract_year_range(filename_text, config) or extract_year_range(all_text[:5000], config)
    region, province, city = infer_region(filename_text, config)
    if not region:
        region, province, city = infer_region(all_text[:3000], config)
    plan_type = infer_plan_type(filename_text, config) or infer_plan_type(all_text[:3000], config) or "未分类规划"
    plan_level = infer_plan_level(filename_text, config) or infer_plan_level(all_text[:3000], config) or "未识别层级"
    doc_id = build_doc_id(pdf_path.stem, year, plan_type)
    sections = iter_sections(cleaned_pages, config)
    chunks = split_chunks(sections, doc_id, config)
    keywords = extract_keywords(all_text[:8000], config)
    now = datetime.now().astimezone().isoformat()

    metadata = {
        "id": doc_id,
        "title": pdf_path.stem,
        "aliases": [],
        "region": region,
        "province": province,
        "city": city,
        "county": None,
        "admin_level": "city" if city else ("province" if province else "unknown"),
        "year": year,
        "year_range": year_range,
        "plan_level": plan_level,
        "plan_type": plan_type,
        "document_type": "规划文本",
        "status": "active",
        "version": "v1",
        "version_group": slugify(f"{region or 'unknown'}-{plan_type}"),
        "source_filename": pdf_path.name,
        "source_path": source_rel_path or str(pdf_path).replace("\\", "/"),
        "file_hash": sha256_file(pdf_path),
        "page_count": len(page_texts),
        "text_length": len(all_text),
        "language": config["project"]["language"],
        "keywords": keywords,
        "tags": list(dict.fromkeys([item for item in [province, city, region, plan_type, plan_level] if item] + keywords[:4])),
        "categories": ["规划知识库", plan_type],
        "summary": summarize_text(all_text, int(config["processing"]["max_summary_chars"])),
        "related_docs": [],
        "previous_version_id": None,
        "next_version_id": None,
        "has_ocr": False,
        "parser": {"engine": "pypdf", "ocr_engine": None, "parsed_at": now},
        "quality": {
            "text_extractable": len(all_text.strip()) > 0,
            "header_footer_cleaned": header_footer_cleaned,
            "chapter_detected": any(section["heading"] != "未识别章节" for section in sections),
            "table_text_noise": "unknown",
        },
        "extensions": {"graph_entity_ids": [], "timeline_topic_ids": [], "rag_ready": True},
        "created_at": now,
        "updated_at": now,
    }
    return ParsedDocument(metadata=metadata, chunks=chunks)


def write_parsed_outputs(parsed: ParsedDocument, config_path: Path) -> None:
    config = load_config(config_path)
    parsed_document_dir = Path(config["paths"]["parsed_document_dir"])
    parsed_chunk_dir = Path(config["paths"]["parsed_chunk_dir"])
    parsed_document_dir.mkdir(parents=True, exist_ok=True)
    parsed_chunk_dir.mkdir(parents=True, exist_ok=True)

    with (parsed_document_dir / f"{parsed.metadata['id']}.json").open("w", encoding="utf-8") as f:
        json.dump(parsed.metadata, f, ensure_ascii=False, indent=2)
    with (parsed_chunk_dir / f"{parsed.metadata['id']}.json").open("w", encoding="utf-8") as f:
        json.dump(parsed.chunks, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Parse a single PDF into metadata and chunks.")
    parser.add_argument("--pdf", required=True, help="Path to a local PDF file.")
    parser.add_argument("--config", default="config/config.yaml", help="Path to YAML config.")
    args = parser.parse_args()

    parsed_document = parse_pdf(Path(args.pdf), Path(args.config))
    write_parsed_outputs(parsed_document, Path(args.config))
    print(json.dumps(parsed_document.metadata, ensure_ascii=False, indent=2))

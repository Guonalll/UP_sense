from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_json_files(directory: Path) -> list[Any]:
    if not directory.exists():
        return []
    items: list[Any] = []
    for path in sorted(directory.glob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            items.append(json.load(f))
    return items


def build_facets(documents: list[dict[str, Any]]) -> dict[str, list[Any]]:
    facets: dict[str, set[Any]] = defaultdict(set)
    for doc in documents:
        for field in ["region", "province", "city", "year", "plan_type", "plan_level", "admin_level"]:
            value = doc.get(field)
            if value not in (None, "", []):
                facets[field].add(value)
        for tag in doc.get("tags", []):
            if tag:
                facets["tags"].add(tag)
    return {key: sorted(values, key=lambda v: str(v)) for key, values in facets.items()}


def build_stats(documents: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "region_count": len({doc["region"] for doc in documents if doc.get("region")}),
        "year_count": len({doc["year"] for doc in documents if doc.get("year")}),
        "updated_at": datetime.now().astimezone().isoformat(),
    }


def link_versions(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in documents:
        groups[doc.get("version_group", "unknown")].append(doc)

    for docs in groups.values():
        docs.sort(key=lambda d: (d.get("year") or 0, d.get("version") or ""))
        for index, doc in enumerate(docs):
            doc["previous_version_id"] = docs[index - 1]["id"] if index > 0 else None
            doc["next_version_id"] = docs[index + 1]["id"] if index < len(docs) - 1 else None
    return documents


def build_indexes(config_path: Path) -> None:
    config = load_config(config_path)
    parsed_document_dir = Path(config["paths"]["parsed_document_dir"])
    parsed_chunk_dir = Path(config["paths"]["parsed_chunk_dir"])
    data_dir = Path(config["paths"]["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)

    documents = [item for item in read_json_files(parsed_document_dir) if isinstance(item, dict)]
    chunk_lists = [item for item in read_json_files(parsed_chunk_dir) if isinstance(item, list)]
    chunks = [chunk for chunk_list in chunk_lists for chunk in chunk_list]

    documents = link_versions(documents)
    documents.sort(key=lambda d: (d.get("year") or 0, d.get("title") or ""), reverse=True)
    chunks.sort(key=lambda c: (c.get("doc_id") or "", c.get("chunk_index") or 0))

    outputs = {
        "documents.json": documents,
        "chunks.json": chunks,
        "facets.json": build_facets(documents),
        "stats.json": build_stats(documents, chunks),
    }
    for filename, payload in outputs.items():
        with (data_dir / filename).open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build aggregate indexes for the knowledge base.")
    parser.add_argument("--config", default="config/config.yaml", help="Path to YAML config.")
    args = parser.parse_args()
    build_indexes(Path(args.config))
    print("Index build completed.")

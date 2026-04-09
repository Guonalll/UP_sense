from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

import yaml
from tqdm import tqdm

from build_index import build_indexes
from parse_pdf import parse_pdf, write_parsed_outputs


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def ensure_dirs(config: dict[str, Any]) -> None:
    for path_key in ["raw_pdf_dir", "parsed_document_dir", "parsed_chunk_dir", "data_dir"]:
        Path(config["paths"][path_key]).mkdir(parents=True, exist_ok=True)


def collect_pdfs(input_dir: Path) -> list[Path]:
    return sorted(path for path in input_dir.rglob("*.pdf") if path.is_file())


def copy_pdf_to_repo(pdf_path: Path, raw_pdf_dir: Path) -> Path:
    target = raw_pdf_dir / pdf_path.name
    if target.resolve() != pdf_path.resolve():
        shutil.copy2(pdf_path, target)
    return target


def import_pdfs(input_dir: Path, config_path: Path) -> None:
    config = load_config(config_path)
    ensure_dirs(config)
    raw_pdf_dir = Path(config["paths"]["raw_pdf_dir"])
    pdf_files = collect_pdfs(input_dir)
    if not pdf_files:
        print(f"No PDF files found in: {input_dir}")
        return

    for pdf_path in tqdm(pdf_files, desc="Importing PDFs"):
        stored_pdf_path = copy_pdf_to_repo(pdf_path, raw_pdf_dir) if config["processing"]["copy_raw_pdf"] else pdf_path
        parsed = parse_pdf(stored_pdf_path, config_path, source_rel_path=stored_pdf_path.as_posix())
        write_parsed_outputs(parsed, config_path)

    build_indexes(config_path)
    print(f"Imported {len(pdf_files)} PDF files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch import local PDFs into the knowledge base.")
    parser.add_argument("--input-dir", required=True, help="Directory containing PDF files.")
    parser.add_argument("--config", default="config/config.yaml", help="Path to YAML config.")
    args = parser.parse_args()
    import_pdfs(Path(args.input_dir), Path(args.config))

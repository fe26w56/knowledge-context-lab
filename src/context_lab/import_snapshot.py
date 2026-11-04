"""Import explicitly exported Notion responses locally, without credentials.

Content stays verbatim. Semantic decision state is deliberately not inferred
from page-level properties or the page's most recent edit time.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re


def convert(data: dict) -> dict:
    documents = []
    for source in data["snapshots"]:
        if source.get("truncated") or source.get("unknown_block_count", 0):
            raise ValueError("Incomplete source snapshot cannot be silently accepted")
        text = source["text"]
        match = re.search(r"<content>\n([\s\S]*?)\n</content>", text)
        if not match:
            raise ValueError("Snapshot has no complete page content")
        body = match.group(1)
        properties = re.search(r"<properties>\n([\s\S]*?)\n</properties>", text)
        props = json.loads(properties.group(1)) if properties else {}
        source_url = source.get("url", source["id"])
        doc_id = "snapshot_" + hashlib.sha256(source_url.encode()).hexdigest()[:12]
        chunks = re.split(r"(?m)(?=^## )", body)
        sections = []
        for chunk in chunks:
            if not chunk.strip():
                continue
            first, sep, remainder = chunk.partition("\n")
            is_heading = first.startswith("## ")
            section_text = remainder.strip("\n") if is_heading else chunk.strip("\n")
            if not section_text:
                continue
            sections.append({
                "id": f"{doc_id}_s{len(sections) + 1}",
                "heading": first.removeprefix("## ") if is_heading else "Introduction",
                "text": section_text,
                "kind": "report", "adoption_status": "na",
                "valid_from": None, "valid_to": None,
                "verified_at": props.get("date:情報確認日:start"),
            })
        documents.append({
            "id": doc_id, "title": source["title"], "source_url": source_url,
            "recorded_at": source.get("page_last_edited_at"),
            "verified_at": props.get("date:情報確認日:start"),
            "scope": "private", "owner": "private-evaluator",
            "body": body, "raw_response": text, "sections": sections,
            "snapshot_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_page_properties": props,
            "ingest_note": "Automatic H2 segmentation; no semantic decision extraction. Page status is not inherited by every section.",
        })
    return {"schema_version": 1, "corpus_id": "private_notion_snapshot_pilot", "privacy": "private_do_not_publish", "documents": documents}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshots", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = convert(json.loads(args.snapshots.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"documents": len(result["documents"]), "sections": sum(len(d["sections"]) for d in result["documents"]), "privacy": result["privacy"]}))


if __name__ == "__main__":
    main()

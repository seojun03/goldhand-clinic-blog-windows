#!/usr/bin/env python3
"""Store reviewed information-reference summaries once, without source prose.

Input may be one curated source object, a list of source objects, or an object
with a ``sources`` list. Duplicate URLs and duplicate content hashes are skipped.
An existing URL whose hash changed is never refreshed unless ``--refresh`` is
explicitly supplied.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_LIBRARY = SKILL_DIR / "assets" / "user-general-information-references.json"
VALIDATOR_PATH = Path(__file__).with_name("validate_general_information_library.py")
RAW_PROSE_KEYS = {"body", "html", "paragraphs", "rawText", "sourceProse", "sourceSentences"}


def load_validator():
    spec = importlib.util.spec_from_file_location("goldhand_information_library_validator", VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"일반 정보 라이브러리 검증기를 불러올 수 없습니다: {VALIDATOR_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = load_validator()


def clean(value: Any) -> str:
    return " ".join(str(value).split()).strip()


def input_sources(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("sources"), list):
        raw = value["sources"]
    elif isinstance(value, list):
        raw = value
    elif isinstance(value, dict):
        raw = [value]
    else:
        raise ValueError("입력은 출처 객체, 출처 배열, 또는 sources 배열 객체여야 합니다.")
    if not all(isinstance(item, dict) for item in raw):
        raise ValueError("모든 출처는 JSON 객체여야 합니다.")
    return list(raw)


def reject_raw_prose(source: dict[str, Any]) -> None:
    found = sorted(key for key in RAW_PROSE_KEYS if key in source)
    if found:
        raise ValueError(
            f"{source.get('id', '출처')}에 원문 보관 필드가 있습니다: {', '.join(found)}"
        )


def upsert(
    library: dict[str, Any],
    additions: list[dict[str, Any]],
    *,
    refresh: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    stored = [item for item in library.get("sources", []) if isinstance(item, dict)]
    by_url = {clean(item.get("sourceUrl", "")): index for index, item in enumerate(stored)}
    by_hash = {
        clean(item.get("contentHash", "")): index
        for index, item in enumerate(stored)
        if clean(item.get("contentHash", ""))
    }
    by_id = {clean(item.get("id", "")): index for index, item in enumerate(stored)}
    added: list[str] = []
    updated: list[str] = []
    skipped: list[dict[str, str]] = []

    for source in additions:
        reject_raw_prose(source)
        source_id = clean(source.get("id", ""))
        source_url = clean(source.get("sourceUrl", ""))
        content_hash = clean(source.get("contentHash", ""))
        if not source_id or not source_url or not content_hash:
            raise ValueError("각 출처에는 id, sourceUrl, contentHash가 필요합니다.")

        url_index = by_url.get(source_url)
        if url_index is not None:
            previous_hash = clean(stored[url_index].get("contentHash", ""))
            if previous_hash == content_hash:
                skipped.append({"id": source_id, "reason": "same-url-and-hash-already-learned"})
                continue
            if not refresh:
                raise ValueError(
                    f"이미 학습한 URL의 본문 해시가 달라졌습니다. 명시적 --refresh가 필요합니다: {source_url}"
                )
            previous_id = clean(stored[url_index].get("id", ""))
            if source_id != previous_id and source_id in by_id:
                raise ValueError(f"다른 출처가 사용 중인 id입니다: {source_id}")
            stored[url_index] = source
            by_hash.pop(previous_hash, None)
            by_hash[content_hash] = url_index
            by_id.pop(previous_id, None)
            by_id[source_id] = url_index
            updated.append(source_id)
            continue

        if content_hash in by_hash:
            skipped.append({"id": source_id, "reason": "same-content-hash-already-learned"})
            continue
        if source_id in by_id:
            raise ValueError(f"다른 출처가 사용 중인 id입니다: {source_id}")
        stored.append(source)
        index = len(stored) - 1
        by_url[source_url] = index
        by_hash[content_hash] = index
        by_id[source_id] = index
        added.append(source_id)

    result = {**library, "sources": stored}
    doctor = result.get("knowledgeDoctor", {})
    if isinstance(doctor, dict):
        doctor = {
            **doctor,
            "lastStoredAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "storedSourceCount": len(stored),
        }
        result["knowledgeDoctor"] = doctor
    report = {
        "status": "changed" if added or updated else "unchanged",
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "storedSourceCount": len(stored),
    }
    return result, report


def atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        library = json.loads(args.library.read_text(encoding="utf-8"))
        additions = input_sources(json.loads(args.input.read_text(encoding="utf-8")))
        updated, report = upsert(library, additions, refresh=args.refresh)
        validation = VALIDATOR.validate_library(updated)
        if validation.get("status") != "pass":
            report = {**report, "status": "fail", "validation": validation}
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2))
            else:
                print("정보 박사 저장 검증 실패", file=sys.stderr)
            return 1
        if not args.dry_run and report["status"] == "changed":
            atomic_write(args.library, updated)
        report["dryRun"] = args.dry_run
    except (OSError, UnicodeError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"정보 박사 저장 실패: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"status: {report['status']}")
        print(f"추가: {len(report['added'])}편 / 갱신: {len(report['updated'])}편 / 건너뜀: {len(report['skipped'])}편")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared preflight used before publishing images, building, and final delivery."""
import importlib.util
from pathlib import Path


def load_script(name):
    spec = importlib.util.spec_from_file_location("goldhand_integrity_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ALIGNMENT = load_script("validate_title_alignment")
UNIQUE = load_script("validate_unique_images")


def validate(article, title):
    alignment = ALIGNMENT.validate(article, title, is_html=True)
    images = UNIQUE.validate(article)
    issues = alignment["issues"] + images["issues"]
    return {"status": "fail" if issues else "pass", "issues": issues,
            "titleAlignment": alignment, "uniqueImages": images}


def require(article, title):
    result = validate(article, title)
    if result["status"] != "pass":
        raise ValueError("제목·사진 제작 검증 실패: " + " / ".join(item["detail"] for item in result["issues"]))

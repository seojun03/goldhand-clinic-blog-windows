#!/usr/bin/env python3
"""Publish a validated Goldhand plugin update from the canonical source."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


REPOSITORY = "seojun03/goldhand-clinic-blog-windows"
WORKFLOW = "windows-install.yml"
PLUGIN_NAME = "goldhand-clinic-blog"
ARCHIVE_NAME = "goldhand-clinic-blog-plugin.zip"
CMD_NAME = "INSTALL-WINDOWS.cmd"
PUBLIC_VERSION_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)\+codex\."
    r"(?P<cachebuster>\d{14})$"
)
RELEASE_TAG_RE = re.compile(
    r"^v(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)-codex\."
    r"(?P<cachebuster>\d{14})$"
)
ALLOWED_BOOTSTRAP_PATHS = (
    ".github/workflows/windows-install.yml",
    "SETUP-IMAGES-WINDOWS.cmd",
    "install-from-download-windows.ps1",
    "README.md",
    "plugins/goldhand-clinic-blog/",
    "scripts/publish_update.py",
    "scripts/validate_distribution.py",
)


class PublishError(RuntimeError):
    pass


def command(
    args: list[str],
    *,
    cwd: Path,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(args), flush=True)
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def output(args: list[str], *, cwd: Path) -> str:
    result = command(args, cwd=cwd, capture=True)
    return result.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_fingerprint(root: Path) -> str:
    """Fingerprint a plugin tree while ignoring generated Python bytecode."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix == ".pyc":
            continue
        encoded = relative.as_posix().encode("utf-8")
        if path.is_symlink():
            digest.update(b"L\0" + encoded + b"\0" + path.readlink().as_posix().encode("utf-8"))
        elif path.is_file():
            digest.update(b"F\0" + encoded + b"\0")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def require_tools() -> None:
    missing = [name for name in ("git", "gh") if shutil.which(name) is None]
    if missing:
        raise PublishError(f"필수 배포 도구가 없습니다: {', '.join(missing)}")


def plugin_version(plugin_root: Path) -> str:
    manifest = plugin_root / ".codex-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"플러그인 manifest를 읽을 수 없습니다: {manifest}") from exc
    version = str(data.get("version", "")).strip()
    if PUBLIC_VERSION_RE.fullmatch(version) is None:
        raise PublishError(f"공개 배포용 버전 형식이 아닙니다: {version}")
    return version


def release_tag(version: str) -> str:
    return "v" + version.replace("+", "-", 1)


def release_tag_sort_key(tag: str) -> tuple[int, int, int, int]:
    match = RELEASE_TAG_RE.fullmatch(tag.strip())
    if match is None:
        raise PublishError(f"비교할 수 없는 공개 릴리스 태그입니다: {tag}")
    return (
        int(match.group("major")),
        int(match.group("minor")),
        int(match.group("patch")),
        int(match.group("cachebuster")),
    )


def git_status(distribution_root: Path) -> list[str]:
    result = command(
        ["git", "status", "--porcelain"],
        cwd=distribution_root,
        capture=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def status_path(line: str) -> str:
    path = line[3:].strip()
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path.strip('"')


def ensure_repository(
    distribution_root: Path,
    *,
    allow_existing_changes: bool,
) -> None:
    root = Path(output(["git", "rev-parse", "--show-toplevel"], cwd=distribution_root)).resolve()
    if root != distribution_root.resolve():
        raise PublishError(f"배포 저장소 루트가 아닙니다: {distribution_root}")
    branch = output(["git", "branch", "--show-current"], cwd=distribution_root)
    if branch != "main":
        raise PublishError(f"main 브랜치에서만 배포할 수 있습니다: {branch}")
    remote = output(["git", "remote", "get-url", "origin"], cwd=distribution_root)
    if "seojun03/goldhand-clinic-blog-windows" not in remote:
        raise PublishError(f"예상한 GitHub 저장소가 아닙니다: {remote}")
    command(["gh", "auth", "status"], cwd=distribution_root)
    command(["git", "fetch", "--prune", "origin"], cwd=distribution_root)
    head = output(["git", "rev-parse", "HEAD"], cwd=distribution_root)
    remote_head = output(["git", "rev-parse", "origin/main"], cwd=distribution_root)
    if head != remote_head:
        raise PublishError("로컬 main과 origin/main이 다릅니다. 배포 전에 분기 상태를 정리해야 합니다.")
    existing = git_status(distribution_root)
    if not existing:
        return
    if not allow_existing_changes:
        raise PublishError("배포 저장소에 기존 변경이 있습니다. 임의로 함께 커밋하지 않습니다.")
    unexpected = [
        line for line in existing
        if not any(status_path(line) == allowed or status_path(line).startswith(allowed)
                   for allowed in ALLOWED_BOOTSTRAP_PATHS)
    ]
    if unexpected:
        raise PublishError("허용되지 않은 기존 변경이 있습니다: " + ", ".join(unexpected))


def latest_release_tag(distribution_root: Path) -> str:
    result = command(
        ["gh", "release", "view", "--repo", REPOSITORY, "--json", "tagName"],
        cwd=distribution_root,
        capture=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return str(json.loads(result.stdout).get("tagName", ""))


def sync_canonical_plugin(plugin_root: Path, distribution_root: Path) -> None:
    updater = (
        Path.home()
        / ".codex"
        / "skills"
        / "codex-plugin-windows-distributor"
        / "scripts"
        / "update_existing_distribution.py"
    )
    if not updater.is_file():
        raise PublishError(f"배포 동기화 도구를 찾을 수 없습니다: {updater}")
    command(
        [
            sys.executable,
            str(updater),
            "--plugin-root",
            str(plugin_root),
            "--distribution-root",
            str(distribution_root),
        ],
        cwd=distribution_root,
    )
    command([sys.executable, "scripts/validate_distribution.py"], cwd=distribution_root)
    command(["git", "diff", "--check"], cwd=distribution_root)


def commit_and_push(version: str, distribution_root: Path) -> str:
    if git_status(distribution_root):
        command(["git", "add", "--all"], cwd=distribution_root)
        command(
            ["git", "commit", "-m", f"Release Goldhand Clinic Blog {version}"],
            cwd=distribution_root,
        )
    sha = output(["git", "rev-parse", "HEAD"], cwd=distribution_root)
    command(["git", "push", "origin", "main"], cwd=distribution_root)
    remote_sha = output(["git", "rev-parse", "origin/main"], cwd=distribution_root)
    if sha != remote_sha:
        raise PublishError("push 뒤 origin/main이 배포 커밋과 일치하지 않습니다.")
    return sha


def workflow_runs(distribution_root: Path, sha: str) -> list[dict[str, object]]:
    raw = output(
        [
            "gh",
            "run",
            "list",
            "--repo",
            REPOSITORY,
            "--workflow",
            WORKFLOW,
            "--commit",
            sha,
            "--limit",
            "30",
            "--json",
            "databaseId,status,conclusion,event,headSha,createdAt",
        ],
        cwd=distribution_root,
    )
    return json.loads(raw or "[]")


def wait_for_run(
    distribution_root: Path,
    sha: str,
    event: str,
    *,
    exclude_ids: set[int] | None = None,
    timeout_seconds: int = 1200,
) -> int:
    excluded = exclude_ids or set()
    deadline = time.monotonic() + timeout_seconds
    run_id = 0
    while time.monotonic() < deadline:
        candidates = [
            item for item in workflow_runs(distribution_root, sha)
            if item.get("event") == event and int(item.get("databaseId", 0)) not in excluded
        ]
        if candidates:
            candidates.sort(key=lambda item: str(item.get("createdAt", "")), reverse=True)
            run_id = int(candidates[0]["databaseId"])
            break
        time.sleep(5)
    if not run_id:
        raise PublishError(f"{event} Windows CI 실행을 찾지 못했습니다.")
    command(
        [
            "gh",
            "run",
            "watch",
            str(run_id),
            "--repo",
            REPOSITORY,
            "--exit-status",
            "--interval",
            "15",
        ],
        cwd=distribution_root,
    )
    return run_id


def build_release_assets(distribution_root: Path, sha: str, destination: Path) -> dict[str, Path]:
    archive = destination / ARCHIVE_NAME
    cmd = destination / CMD_NAME
    command(
        [
            "git",
            "archive",
            "--format=zip",
            "--prefix=goldhand-clinic-blog-windows/",
            f"--output={archive}",
            sha,
        ],
        cwd=distribution_root,
    )
    source_cmd = distribution_root / CMD_NAME
    cmd.write_bytes(source_cmd.read_bytes())
    return {ARCHIVE_NAME: archive, CMD_NAME: cmd}


def compare_asset_sets(expected: dict[str, Path], downloaded: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name, source in expected.items():
        target = downloaded / name
        if not target.is_file():
            raise PublishError(f"공개 릴리스 자산이 없습니다: {name}")
        source_hash = sha256(source)
        target_hash = sha256(target)
        if source_hash != target_hash:
            raise PublishError(f"공개 릴리스 SHA-256 불일치: {name}")
        hashes[name] = source_hash
    return hashes


def download_latest_asset(url: str, destination: Path, expected_sha256: str) -> None:
    last_error: Exception | None = None
    for _ in range(12):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "goldhand-owner-publisher/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            if not data.startswith(b"<!DOCTYPE html") and not data.startswith(b"<html"):
                destination.write_bytes(data)
                if sha256(destination) == expected_sha256:
                    return
        except Exception as exc:  # pragma: no cover - network failures are reported to the owner
            last_error = exc
        time.sleep(5)
    raise PublishError(f"latest 공개 파일을 내려받지 못했습니다: {url}: {last_error}")


def release_with_verified_assets(
    distribution_root: Path,
    *,
    version: str,
    sha: str,
) -> tuple[str, dict[str, str]]:
    tag = release_tag(version)
    with tempfile.TemporaryDirectory(prefix="goldhand-release-") as temp_name:
        temp = Path(temp_name)
        local = temp / "local"
        downloaded = temp / "downloaded"
        latest = temp / "latest"
        local.mkdir()
        downloaded.mkdir()
        latest.mkdir()
        assets = build_release_assets(distribution_root, sha, local)
        command(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                REPOSITORY,
                "--target",
                sha,
                "--title",
                f"Goldhand Clinic Blog {version}",
                "--notes",
                "Validated Goldhand Clinic Blog managed update.",
                "--draft",
                str(assets[CMD_NAME]),
                str(assets[ARCHIVE_NAME]),
            ],
            cwd=distribution_root,
        )
        try:
            command(
                ["gh", "release", "download", tag, "--repo", REPOSITORY, "--dir", str(downloaded)],
                cwd=distribution_root,
            )
            hashes = compare_asset_sets(assets, downloaded)
            command(
                ["gh", "release", "edit", tag, "--repo", REPOSITORY, "--draft=false", "--latest"],
                cwd=distribution_root,
            )
            for name, source in assets.items():
                url = f"https://github.com/{REPOSITORY}/releases/latest/download/{name}"
                download_latest_asset(url, latest / name, sha256(source))
            return tag, hashes
        except Exception:
            command(
                ["gh", "release", "delete", tag, "--repo", REPOSITORY, "--yes", "--cleanup-tag"],
                cwd=distribution_root,
                check=False,
            )
            raise


def dispatch_public_install_check(distribution_root: Path, sha: str, tag: str) -> int:
    before = {int(item["databaseId"]) for item in workflow_runs(distribution_root, sha)}
    try:
        command(
            ["gh", "workflow", "run", WORKFLOW, "--repo", REPOSITORY, "--ref", "main"],
            cwd=distribution_root,
        )
        return wait_for_run(
            distribution_root,
            sha,
            "workflow_dispatch",
            exclude_ids=before,
        )
    except Exception:
        command(
            ["gh", "release", "delete", tag, "--repo", REPOSITORY, "--yes", "--cleanup-tag"],
            cwd=distribution_root,
            check=False,
        )
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--distribution-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--allow-existing-changes", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plugin_root = args.plugin_root.expanduser().resolve()
    distribution_root = args.distribution_root.expanduser().resolve()
    try:
        require_tools()
        ensure_repository(
            distribution_root,
            allow_existing_changes=args.allow_existing_changes,
        )
        version = plugin_version(plugin_root)
        if args.preflight_only:
            print(f"publish preflight passed: {PLUGIN_NAME} {version}")
            return 0
        tag = release_tag(version)
        latest = latest_release_tag(distribution_root)
        distributed_plugin = distribution_root / "plugins" / PLUGIN_NAME
        if latest == tag:
            if git_status(distribution_root):
                raise PublishError("배포할 변경이 있지만 manifest 버전이 기존 공개 버전과 같습니다.")
            if tree_fingerprint(plugin_root) != tree_fingerprint(distributed_plugin):
                raise PublishError("원본이 공개본과 다르지만 manifest 버전이 기존 공개 버전과 같습니다.")
            print(f"already published: {tag}")
            return 0
        if latest and release_tag_sort_key(tag) <= release_tag_sort_key(latest):
            raise PublishError(f"새 버전이 기존 공개 버전보다 높지 않습니다: {tag} <= {latest}")
        if (
            plugin_version(distributed_plugin) == version
            and tree_fingerprint(plugin_root) == tree_fingerprint(distributed_plugin)
        ):
            command([sys.executable, "scripts/validate_distribution.py"], cwd=distribution_root)
            command(["git", "diff", "--check"], cwd=distribution_root)
        else:
            sync_canonical_plugin(plugin_root, distribution_root)
        distributed_version = plugin_version(distributed_plugin)
        if distributed_version != version:
            raise PublishError(
                f"동기화 버전 불일치: canonical={version}, distribution={distributed_version}"
            )
        sha = commit_and_push(version, distribution_root)
        push_run = wait_for_run(distribution_root, sha, "push")
        tag, hashes = release_with_verified_assets(
            distribution_root,
            version=version,
            sha=sha,
        )
        public_run = dispatch_public_install_check(distribution_root, sha, tag)
        command(["git", "fetch", "--tags", "origin"], cwd=distribution_root)
        print(json.dumps({
            "status": "published",
            "version": version,
            "tag": tag,
            "commit": sha,
            "pushCiRun": push_run,
            "publicInstallCiRun": public_run,
            "assets": hashes,
            "installerUrl": f"https://github.com/{REPOSITORY}/releases/latest/download/{CMD_NAME}",
        }, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, PublishError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"공개 배포 실패: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

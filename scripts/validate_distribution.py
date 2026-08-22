#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = 'goldhand-clinic-blog'
MARKETPLACE_NAME = 'goldhand-clinic-windows'
ENV_PREFIX = 'GOLDHANDBLOG'
SHORT_PREFIX = 'ghb'
PLUGIN_ROOT = ROOT / "plugins" / PLUGIN_NAME
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

def load_json(path: Path) -> dict:
    require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> int:
    manifest = load_json(PLUGIN_ROOT / ".codex-plugin" / "plugin.json")
    require(manifest.get("name") == PLUGIN_NAME, "plugin name mismatch")
    require(bool(SEMVER.fullmatch(str(manifest.get("version", "")))), "plugin version is not SemVer")
    require((PLUGIN_ROOT / "skills" / PLUGIN_NAME / "SKILL.md").is_file(), "skill entrypoint is missing")

    marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
    require(marketplace.get("name") == MARKETPLACE_NAME, "marketplace name mismatch")
    entries = [item for item in marketplace.get("plugins", []) if item.get("name") == PLUGIN_NAME]
    require(len(entries) == 1, "marketplace must contain exactly one plugin entry")
    require(entries[0].get("source") == {"source": "local", "path": f"./plugins/{PLUGIN_NAME}"}, "marketplace local source mismatch")

    required = [
        ROOT / "INSTALL-WINDOWS.cmd",
        ROOT / "install-from-download-windows.ps1",
        ROOT / "requirements-windows.txt",
        ROOT / "scripts" / "apply-local-edits-windows.ps1",
        ROOT / "scripts" / "update-windows.ps1",
        ROOT / ".github" / "workflows" / "windows-install.yml",
    ]
    for path in required:
        require(path.is_file(), f"missing required file: {path.relative_to(ROOT)}")

    root_requirements = (ROOT / "requirements-windows.txt").read_bytes()
    plugin_requirements = (PLUGIN_ROOT / "requirements-windows.txt").read_bytes()
    require(
        root_requirements == plugin_requirements,
        "top-level Windows requirements must exactly match the packaged plugin requirements",
    )

    forbidden = []
    long_paths = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        relative = path.relative_to(ROOT)
        if path.name in {".DS_Store", "__pycache__"} or path.suffix.lower() in {".pyc", ".pyo"}:
            forbidden.append(str(relative))
        if len(str(relative)) > 200:
            long_paths.append(str(relative))
    require(not forbidden, "forbidden cache files: " + ", ".join(forbidden))
    require(not long_paths, "Windows-safe relative path limit exceeded: " + ", ".join(long_paths))

    launcher = (ROOT / "INSTALL-WINDOWS.cmd").read_text(encoding="ascii")
    installer = (ROOT / "install-from-download-windows.ps1").read_text(encoding="ascii")
    updater = (ROOT / "scripts" / "update-windows.ps1").read_text(encoding="ascii")
    helper_bytes = (ROOT / "scripts" / "apply-local-edits-windows.ps1").read_bytes()
    require(helper_bytes.startswith(b"\xef\xbb\xbf"), "PowerShell 5.1 edit helper is missing UTF-8 BOM")
    require(f"{ENV_PREFIX}_BOOTSTRAP_ARCHIVE" in launcher, "isolated CMD archive override is missing")
    require("Get-ChildItem" in launcher and "install-from-download-windows.ps1" in launcher, "isolated CMD recovery is missing")
    require(f"('.{SHORT_PREFIX}-' + [Guid]::NewGuid()" in launcher, "short bootstrap extraction path is missing")
    require("DestinationPath $expanded -Force" not in launcher, "bootstrap must not use Expand-Archive -Force")
    require("function Remove-TempDirectoryBestEffort" in installer, "nonfatal cleanup helper is missing")
    require("Test-PythonAvailable" in installer and "Python.Python.3.14" in installer, "Python alias-safe dependency handling is missing")
    require("Install-PythonRequirements" in installer and "requirements-windows.txt" in installer, "plugin Python dependency installation is missing")
    require("plugin --help" in installer, "functional Codex CLI probe is missing")
    require("https://chatgpt.com/codex/install.ps1" in installer, "official Codex installer fallback is missing")
    require("Get-AppxPackage" not in installer and '-Filter "codex.exe"' not in installer, "protected Appx Codex discovery must not be used")
    require("if ($env:CODEX_HOME -and -not (Test-Path -LiteralPath $env:CODEX_HOME))" in installer, "CODEX_HOME creation guard is missing")
    require("sourceType" in installer and "local" in installer, "local marketplace verification is missing")
    require("Copy-ManagedTree" in installer and "Restore-ManagedTree" in installer, "transactional managed replacement is missing")
    require("Register-AutoUpdate" in installer and "New-ScheduledTaskTrigger" in installer, "automatic update registration is missing")
    require('goldhand-clinic-blog-plugin.zip' in launcher, "isolated CMD must download the validated release ZIP")
    require("releases/latest" in updater and 'goldhand-clinic-blog-plugin.zip' in updater, "release-only updater is missing")
    require("archive/refs/heads/main.zip" not in launcher and "archive/refs/heads/main.zip" not in updater, "Windows install paths must not consume unvalidated main branch ZIPs")
    print(f"distribution validation passed: {PLUGIN_NAME} {manifest['version']}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
        print(f"distribution validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)

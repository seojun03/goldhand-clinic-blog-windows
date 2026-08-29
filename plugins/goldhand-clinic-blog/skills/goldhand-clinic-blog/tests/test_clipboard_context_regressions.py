from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"


def load_module(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"goldhand_regression_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"모듈을 불러올 수 없습니다: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARTICLE_VALIDATOR = load_module("validate_article")
PAGE_BUILDER = load_module("build_naver_copy_page")
HTML_VALIDATOR = load_module("validate_html")

ASSET_ID = "GH0017"
VISIBLE_SCREENSHOT_SENTENCE = (
    "보호자분께 어르신의 양쪽 상하지 근육 및 근력 상태 비교하면서 설명해 드리고, "
    "어르신께서 노력해주셔야 하는 부분과 가정에서 도와주셔야 할 부분 상세히 설명드렸습니다."
)


def media_library() -> dict[str, dict[str, object]]:
    raw = json.loads((SKILL_DIR / "assets" / "media-library.json").read_text(encoding="utf-8"))
    return {
        str(asset["id"]): asset
        for asset in raw["assets"]
        if isinstance(asset, dict) and asset.get("id")
    }


class MediaContextLeakRegressionTests(unittest.TestCase):
    def test_selected_photo_context_paraphrase_is_detected_in_visible_prose(self) -> None:
        article = (
            f'<article><img data-goldhand-media="{ASSET_ID}" src="data:,">'
            f"<p>{VISIBLE_SCREENSHOT_SENTENCE}</p></article>"
        )

        leaks = ARTICLE_VALIDATOR.selected_media_context_leaks(article, media_library())

        self.assertEqual(len(leaks), 1, leaks)
        self.assertEqual(leaks[0]["assetId"], ASSET_ID)
        self.assertEqual(leaks[0]["field"], "context")
        self.assertEqual(
            leaks[0]["excerpt"],
            "상하지 근육 근력 상태 비교하면서 설명해 드리고",
        )

    def test_context_in_image_metadata_is_not_treated_as_visible_prose(self) -> None:
        article = (
            f'<article><img data-goldhand-media="{ASSET_ID}" '
            f'alt="{VISIBLE_SCREENSHOT_SENTENCE}" src="data:,">'
            "<p>진료 계획은 현재 상태를 확인한 뒤 설명드립니다.</p></article>"
        )

        leaks = ARTICLE_VALIDATOR.selected_media_context_leaks(article, media_library())

        self.assertEqual(leaks, [])

    def test_context_for_an_unselected_photo_is_ignored(self) -> None:
        article = (
            '<article><img data-goldhand-media="GH0001" src="data:,">'
            f"<p>{VISIBLE_SCREENSHOT_SENTENCE}</p></article>"
        )

        leaks = ARTICLE_VALIDATOR.selected_media_context_leaks(article, media_library())

        self.assertEqual(leaks, [])

    def test_article_validator_emits_visible_media_context_error(self) -> None:
        article = (
            f'<article data-goldhand-type="정보전달형"><img data-goldhand-media="{ASSET_ID}" src="data:,">'
            f"<p>{VISIBLE_SCREENSHOT_SENTENCE}</p></article>"
        )

        result = ARTICLE_VALIDATOR.validate_article(
            article,
            "동천동 한의원 움직임을 살펴보는 기준",
            "동천동 한의원",
            min_chars=0,
            max_chars=5000,
            media_library=media_library(),
        )

        context_issues = [
            issue for issue in result["issues"]
            if issue["code"] == "visible-media-context-leak"
        ]
        self.assertEqual(len(context_issues), 1, context_issues)
        self.assertIn(ASSET_ID, context_issues[0]["detail"])

    def test_copy_page_builder_blocks_the_screenshot_context_sentence(self) -> None:
        article = (
            f'<article><img data-goldhand-media="{ASSET_ID}" src="data:,">'
            f"<p>{VISIBLE_SCREENSHOT_SENTENCE}</p></article>"
        )

        with self.assertRaisesRegex(ValueError, rf"context 문장.*{ASSET_ID}"):
            PAGE_BUILDER.build_page("금손한의원 문맥 노출 회귀 테스트", article)


class ClipboardRegressionTests(unittest.TestCase):
    @staticmethod
    def page() -> str:
        return PAGE_BUILDER.build_page(
            "금손한의원 복사 회귀 테스트",
            "<article><p>전체 본문 첫 문장입니다.</p><p>전체 본문 두 번째 문장입니다.</p></article>",
        )

    def test_local_file_branch_synchronously_selects_the_full_native_payload(self) -> None:
        page = self.page()
        local_start = page.index("if (window.location.protocol === 'file:')")
        http_start = page.index("if (navigator.clipboard?.write", local_start)
        local_branch = page[local_start:http_start]

        self.assertIn("button.addEventListener('click', () =>", page)
        self.assertNotIn("button.addEventListener('click', async", page)
        self.assertNotIn("await copyImagesReady", page)
        self.assertIn("function nativeSelectionRoot(inputBuffer, nativeHtml)", page)
        self.assertIn("inputBuffer.cloneNode(true)", page)
        self.assertIn("selectionRoot.insertAdjacentHTML('beforeend',nativeHtml)", page)
        self.assertIn(
            "copyRenderedSelection(nativeSelectionRoot(inputBuffer,nativeHtml))",
            local_branch,
        )
        self.assertIn("range.selectNodeContents(copyRoot)", page)
        self.assertIn("selection.addRange(range)", page)
        self.assertIn("document.body.appendChild(copyRoot)", page)
        self.assertIn("copyRoot.remove()", page)
        self.assertNotIn("await", local_branch)
        self.assertNotIn(".then(", local_branch)
        self.assertNotIn("navigator.clipboard", local_branch)
        self.assertNotIn("copyWithDataTransfer", page)
        self.assertNotIn("document.addEventListener('copy'", page)

    def test_html_validator_requires_selection_and_clipboard_item_contracts(self) -> None:
        required = HTML_VALIDATOR.REQUIRED_SNIPPETS

        self.assertNotIn("clipboard-data-transfer-copy", required)
        self.assertNotIn("clipboard-payload-confirmation", required)
        self.assertEqual(required["native-selection-root"], "nativeSelectionRoot")
        self.assertEqual(
            required["native-selection-copy"],
            "copyRenderedSelection(nativeSelectionRoot(inputBuffer,nativeHtml))",
        )
        self.assertEqual(required["native-selection-input-buffer"], "inputBuffer.cloneNode(true)")
        self.assertEqual(
            required["native-selection-html"],
            "selectionRoot.insertAdjacentHTML('beforeend',nativeHtml)",
        )
        self.assertEqual(required["native-selection-attach"], "document.body.appendChild(copyRoot)")
        self.assertEqual(required["native-selection-range"], "range.selectNodeContents(copyRoot)")
        self.assertEqual(required["native-selection-add-range"], "selection.addRange(range)")
        self.assertEqual(required["native-selection-cleanup"], "copyRoot.remove()")
        self.assertEqual(required["clipboard-html-payload"], "'text/html':new Blob([htmlValue]")
        self.assertEqual(required["clipboard-plain-payload"], "'text/plain':new Blob([plainValue]")

    @unittest.skipUnless(shutil.which("node"), "Node.js가 없어 브라우저 복사 함수 실행 검사를 건너뜁니다.")
    def test_selection_copy_replaces_stale_content_and_always_cleans_up(self) -> None:
        page = self.page()
        function_start = page.index("function nativeSelectionRoot")
        function_end = page.index("function copySuccessMessage", function_start)
        function_source = page[function_start:function_end]
        node_script = function_source + r"""
function runScenario(mode) {
  class FakeElement {
    constructor(tagName) {
      this.tagName = tagName;
      this.style = {};
      this.children = [];
      this.parentNode = null;
      this.html = '';
      this.outerHTML = '';
      this.textContent = '';
    }
    appendChild(node) {
      node.parentNode = this;
      this.children.push(node);
      return node;
    }
    cloneNode() {
      const clone = new FakeElement(this.tagName);
      clone.outerHTML = this.outerHTML;
      clone.textContent = this.textContent;
      return clone;
    }
    insertAdjacentHTML(position, html) {
      if (position !== 'beforeend') throw new Error('unexpected-position');
      this.html += html;
    }
    remove() {
      if (!this.parentNode) return;
      const index = this.parentNode.children.indexOf(this);
      if (index >= 0) this.parentNode.children.splice(index, 1);
      this.parentNode = null;
    }
    get isConnected() {
      let current = this;
      while (current) {
        if (current === body) return true;
        current = current.parentNode;
      }
      return false;
    }
  }
  const body = new FakeElement('body');
  const selection = {
    ranges: [],
    removeAllRanges() { this.ranges = []; },
    addRange(range) { this.ranges = [range]; },
  };
  const clipboard = {
    html: '보호자분께 어르신의 양쪽 상하지 근육 및 근력 상태 비교하면서 설명해 드리고',
  };
  let connectedAtCopy = false;
  let rangeCountAtCopy = 0;
  global.document = {
    body,
    createElement(tagName) { return new FakeElement(tagName); },
    createRange() {
      return {
        node: null,
        selectNodeContents(node) { this.node = node; },
      };
    },
    execCommand(command) {
      if (command !== 'copy') throw new Error('unexpected-command');
      if (mode === 'throw') throw new Error('copy-blocked');
      const range = selection.ranges[0];
      connectedAtCopy = Boolean(range?.node?.isConnected);
      rangeCountAtCopy = selection.ranges.length;
      if (mode === 'success' && connectedAtCopy && rangeCountAtCopy === 1) {
        const root = range.node;
        clipboard.html = root.children.map((child) => child.outerHTML).join('') + root.html;
        return true;
      }
      return false;
    },
  };
  global.window = { getSelection() { return selection; } };
  const inputBuffer = new FakeElement('span');
  inputBuffer.outerHTML = '<span data-input-buffer="INPUT_BUFFER_DATA;Windows;blog.naver.com">&#8203;</span>';
  const nativeHtml = '<div class="se-component">전체 본문 첫 문장입니다.</div><div class="se-component">전체 본문 두 번째 문장입니다.</div>';
  const root = nativeSelectionRoot(inputBuffer, nativeHtml);
  const copied = copyRenderedSelection(root);
  return {
    copied,
    connectedAtCopy,
    rangeCountAtCopy,
    clipboardHtml: clipboard.html,
    bodyChildren: body.children.length,
    remainingRanges: selection.ranges.length,
  };
}
process.stdout.write(JSON.stringify({
  success: runScenario('success'),
  failed: runScenario('failed'),
  thrown: runScenario('throw'),
}));
"""

        completed = subprocess.run(
            [shutil.which("node") or "node", "-e", node_script],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)

        success = result["success"]
        self.assertTrue(success["copied"])
        self.assertTrue(success["connectedAtCopy"])
        self.assertEqual(success["rangeCountAtCopy"], 1)
        self.assertIn("INPUT_BUFFER_DATA", success["clipboardHtml"])
        self.assertIn("전체 본문 첫 문장입니다.", success["clipboardHtml"])
        self.assertIn("전체 본문 두 번째 문장입니다.", success["clipboardHtml"])
        self.assertNotIn("상하지 근육", success["clipboardHtml"])
        self.assertEqual(success["bodyChildren"], 0)
        self.assertEqual(success["remainingRanges"], 0)

        self.assertFalse(result["failed"]["copied"])
        self.assertIn("상하지 근육", result["failed"]["clipboardHtml"])
        self.assertEqual(result["failed"]["bodyChildren"], 0)
        self.assertEqual(result["failed"]["remainingRanges"], 0)
        self.assertFalse(result["thrown"]["copied"])
        self.assertIn("상하지 근육", result["thrown"]["clipboardHtml"])
        self.assertEqual(result["thrown"]["bodyChildren"], 0)
        self.assertEqual(result["thrown"]["remainingRanges"], 0)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import engine
import screening_engine
import styles


class JsonRepairTests(unittest.TestCase):
    def test_valid_json_is_not_marked_repaired(self) -> None:
        payload, repaired = engine._parse_json_content_with_meta('{"headline":"a","summary":"b"}')
        self.assertEqual(payload, {"headline": "a", "summary": "b"})
        self.assertFalse(repaired)

    def test_truncated_string_is_repaired_and_marked(self) -> None:
        payload, repaired = engine._parse_json_content_with_meta(
            '{"headline":"业绩标签","summary":"写到一半的字'
        )
        self.assertEqual(payload["summary"], "写到一半的字")
        self.assertTrue(repaired)

    def test_dangling_field_is_dropped_and_marked(self) -> None:
        payload, repaired = engine._parse_json_content_with_meta('{"headline":"a","summary":')
        self.assertEqual(payload, {"headline": "a"})
        self.assertTrue(repaired)

    def test_non_json_still_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "截断"):
            engine._parse_json_content("not json at all")


class ScreeningFailClosedTests(unittest.TestCase):
    def test_empty_result_is_unfinished_and_all_checks_unchecked(self) -> None:
        result = screening_engine.empty_fast_result("无可用原文")
        self.assertEqual(result["screening_conclusion"], "未完成")
        self.assertEqual(result["screening_unchecked"], screening_engine.CHECK_ORDER)
        self.assertEqual(screening_engine.risk_tag_class(result["screening_conclusion"]), "risk-gap")

    def test_model_failure_cannot_become_provisional_pass(self) -> None:
        original = screening_engine.OpenAI

        class BrokenClient:
            def __init__(self, *args, **kwargs) -> None:
                raise RuntimeError("模拟服务不可用")

        screening_engine.OpenAI = BrokenClient
        try:
            result = screening_engine.screen_fast(
                company_name="测试公司",
                stock_code="000001.SZ",
                report_type="半年度报告",
                report_year=2026,
                metrics={},
                evidence_text="候选原文",
                api_key="test-key",
                model="test-model",
                base_url="https://example.invalid",
                test_mode=False,
            )
        finally:
            screening_engine.OpenAI = original
        self.assertEqual(result["screening_conclusion"], "未完成")
        self.assertEqual(len(result["screening_unchecked"]), 19)


class BackgroundTests(unittest.TestCase):
    def test_background_is_embedded_as_portable_data_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "background.jpg"
            image_path.write_bytes(b"jpeg-test")
            css = styles.css_for_theme("Dark", image_path)
            login_css = styles.login_css(image_path)
        self.assertIn("data:image/jpeg;base64,", css)
        self.assertIn("background-size: cover", css)
        self.assertIn("data:image/jpeg;base64,", login_css)


if __name__ == "__main__":
    unittest.main()

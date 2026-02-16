"""Tests for page relevance scoring and selection."""

import pytest
from src.lib.page_relevance import split_ocr_by_page, score_page, select_relevant_pages


# ── split_ocr_by_page ──────────────────────────────────────────────────────

class TestSplitOcrByPage:
    def test_single_page_no_markers(self):
        text = "Heat 12345\nC 0.42 Mn 0.75"
        result = split_ocr_by_page(text)
        assert result == {1: text}

    def test_multi_page_standard_markers(self):
        text = (
            "\n--- Page 1 ---\n"
            "Page one content\n"
            "\n--- Page 2 ---\n"
            "Page two content\n"
            "\n--- Page 3 ---\n"
            "Page three content"
        )
        result = split_ocr_by_page(text)
        assert len(result) == 3
        assert "Page one content" in result[1]
        assert "Page two content" in result[2]
        assert "Page three content" in result[3]

    def test_empty_text(self):
        result = split_ocr_by_page("")
        assert result == {1: ""}


# ── score_page ──────────────────────────────────────────────────────────────

class TestScorePage:
    def test_chemistry_heavy_page(self):
        text = (
            "C 0.42 Mn 0.75 P 0.015 S 0.008 Si 0.25 "
            "Cr 1.05 Ni 0.12 Mo 0.20 Cu 0.15 V 0.003"
        )
        score = score_page(text, 1, 5)
        assert score > 25, f"Chemistry page should score >25, got {score}"

    def test_mechanical_page(self):
        text = (
            "Yield Strength: 95 ksi\n"
            "Tensile Strength: 120 ksi\n"
            "Elongation: 18%\n"
            "Hardness: 28 HRC"
        )
        score = score_page(text, 1, 5)
        assert score > 10, f"Mechanical page should score >10, got {score}"

    def test_filler_page(self):
        text = (
            "TERMS AND CONDITIONS\n"
            "This warranty is provided as-is.\n"
            "Limitation of liability applies.\n"
            "Disclaimer: the seller makes no guarantees."
        )
        score = score_page(text, 5, 5)
        assert score < 0, f"Filler page should score <0, got {score}"

    def test_false_positive_prose(self):
        """Words like 'C' and 'N' in prose should NOT trigger chemistry
        when fewer than 3 distinct elements are present."""
        text = "Condition: Normalized and Tempered. N/A for this requirement."
        score = score_page(text, 1, 1)
        # Should not get full chemistry weight; score should be modest
        assert score < 15, f"Prose page should score <15, got {score}"

    def test_page_position_favors_early(self):
        text = "some neutral text with numbers 12345"
        score_early = score_page(text, 1, 10)
        score_late = score_page(text, 10, 10)
        assert score_early > score_late


# ── select_relevant_pages ───────────────────────────────────────────────────

class TestSelectRelevantPages:
    def test_single_page_doc(self):
        assert select_relevant_pages("any text", total_pages=1) == [0]

    def test_selects_relevant_pages(self):
        """14-page doc with 2 relevant pages should return those 2."""
        pages = []
        for i in range(1, 15):
            pages.append(f"\n--- Page {i} ---\n")
            if i == 2:
                pages.append(
                    "C 0.42 Mn 0.75 P 0.015 S 0.008 Si 0.25 "
                    "Cr 1.05 Ni 0.12 Mo 0.20 Cu 0.15 V 0.003"
                )
            elif i == 3:
                pages.append(
                    "Yield Strength: 95 ksi\n"
                    "Tensile Strength: 120 ksi\n"
                    "Elongation: 18%"
                )
            else:
                pages.append(
                    "Terms and conditions. Warranty. Disclaimer. "
                    "Limitation of liability. This is boilerplate."
                )
        ocr_text = "".join(pages)
        result = select_relevant_pages(ocr_text, total_pages=14, max_pages=5)
        # Pages 2 and 3 (0-indexed: 1 and 2) should be selected
        assert 1 in result, f"Page 2 (idx 1) should be selected, got {result}"
        assert 2 in result, f"Page 3 (idx 2) should be selected, got {result}"
        assert len(result) <= 5

    def test_all_below_threshold_fallback(self):
        """When all pages are filler, fallback to first page."""
        pages = []
        for i in range(1, 4):
            pages.append(f"\n--- Page {i} ---\n")
            pages.append("Terms and conditions. Warranty. Disclaimer.")
        ocr_text = "".join(pages)
        result = select_relevant_pages(ocr_text, total_pages=3, min_pages=1)
        assert len(result) >= 1
        assert result[0] == 0  # fallback to first page

    def test_results_sorted_in_document_order(self):
        """Selected pages should be in ascending order."""
        pages = []
        for i in range(1, 8):
            pages.append(f"\n--- Page {i} ---\n")
            if i in (5, 2):
                pages.append("C 0.42 Mn 0.75 P 0.015 S 0.008 Si 0.25 Cr 1.05 Ni 0.12")
            else:
                pages.append("boilerplate text nothing useful")
        ocr_text = "".join(pages)
        result = select_relevant_pages(ocr_text, total_pages=7, max_pages=5)
        assert result == sorted(result), f"Results should be sorted, got {result}"

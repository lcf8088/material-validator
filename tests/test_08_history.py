"""
Test 08: ValidationHistory - Audit trail.
"""

import pytest
from lib.history import ValidationHistory
from lib.validator import CertValidation, ValidationResult


@pytest.fixture
def history(tmp_path):
    return ValidationHistory(str(tmp_path / "history"))


@pytest.fixture
def sample_validation():
    return CertValidation(
        spec_id="ES-M0001C",
        heat_number="TEST-HEAT-001",
        material_grade="4140",
        overall_status="PASS",
        chemistry_results=[
            ValidationResult("C", spec_min=0.38, spec_max=0.43, actual_value=0.42, status="PASS"),
        ],
    )


class TestHistoryRecording:
    def test_record_returns_id(self, history, sample_validation):
        vid = history.record(
            sample_validation,
            {"heat_number": "TEST-HEAT-001"},
            {"id": "ES-M0001C"},
            "test.pdf",
        )
        assert isinstance(vid, str)
        assert len(vid) > 0

    def test_record_and_retrieve(self, history, sample_validation):
        vid = history.record(sample_validation, {}, {}, "test.pdf")
        record = history.get(vid)
        assert record is not None
        assert record["heat_number"] == "TEST-HEAT-001"
        assert record["spec_id"] == "ES-M0001C"
        assert record["result"] == "PASS"

    def test_get_nonexistent_returns_none(self, history):
        assert history.get("nonexistent-id") is None


class TestHistorySearch:
    def test_find_by_heat(self, history, sample_validation):
        history.record(sample_validation, {}, {}, "test.pdf")
        results = history.find_by_heat("TEST-HEAT-001")
        assert len(results) == 1

    def test_find_by_spec(self, history, sample_validation):
        history.record(sample_validation, {}, {}, "test.pdf")
        results = history.find_by_spec("ES-M0001C")
        assert len(results) == 1

    def test_find_by_heat_no_results(self, history):
        results = history.find_by_heat("NONEXISTENT")
        assert len(results) == 0


class TestHistoryStats:
    def test_empty_stats(self, history):
        stats = history.stats()
        assert stats["total"] == 0
        assert stats["pass"] == 0

    def test_stats_after_records(self, history, sample_validation):
        history.record(sample_validation, {}, {}, "test.pdf")

        fail_val = CertValidation(
            spec_id="ES-M0001C", heat_number="H2", material_grade="4140",
            overall_status="FAIL",
        )
        history.record(fail_val, {}, {}, "test2.pdf")

        stats = history.stats()
        assert stats["total"] == 2
        assert stats["pass"] == 1
        assert stats["fail"] == 1


class TestHistoryRecent:
    def test_recent_empty(self, history):
        assert history.recent() == []

    def test_recent_returns_latest(self, history, sample_validation):
        for i in range(5):
            v = CertValidation(
                spec_id="ES-M0001C",
                heat_number=f"H{i}",
                material_grade="4140",
                overall_status="PASS",
            )
            history.record(v, {}, {}, f"test{i}.pdf")

        recent = history.recent(3)
        assert len(recent) == 3
        assert recent[-1]["heat_number"] == "H4"  # Most recent last

    def test_format_recent(self, history, sample_validation):
        history.record(sample_validation, {}, {}, "test.pdf")
        text = history.format_recent()
        assert "Recent Validations" in text
        assert "TEST-HEAT-001" in text

"""
Test 02: SpecLoader - YAML spec loading and singleton pattern.
"""

import pytest
from lib.spec_loader import SpecLoader


class TestSpecLoaderSingleton:
    def test_get_instance_returns_same_object(self, specs_dir):
        a = SpecLoader.get_instance(specs_dir)
        b = SpecLoader.get_instance(specs_dir)
        assert a is b

    def test_get_instance_without_args(self, specs_dir):
        # Prime the singleton first
        SpecLoader.get_instance(specs_dir)
        loader = SpecLoader.get_instance()
        assert loader is not None


class TestSpecLoaderLoading:
    def test_list_ids_returns_expected_specs(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        ids = loader.list_ids()
        assert "ES-M0001C" in ids
        assert "ES-M0001G" in ids
        assert "ES-M0003A" in ids
        assert "ES-M0003E" in ids
        assert len(ids) == 4

    def test_get_valid_spec(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        spec = loader.get("ES-M0001C")
        assert spec is not None
        assert spec["id"] == "ES-M0001C"
        assert "chemistry" in spec
        assert "mechanical" in spec

    def test_get_invalid_spec_returns_none(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        assert loader.get("NONEXISTENT-SPEC") is None

    def test_spec_has_chemistry(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        spec = loader.get("ES-M0001C")
        chem = spec["chemistry"]
        assert "C" in chem
        assert "Cr" in chem
        assert "Mo" in chem

    def test_spec_chemistry_keys_are_title_case(self, specs_dir):
        """Critical: element keys must be title case (Cr, not CR or cr)."""
        loader = SpecLoader.get_instance(specs_dir)
        for spec_id in loader.list_ids():
            spec = loader.get(spec_id)
            for elem in spec.get("chemistry", {}):
                assert elem == elem.strip().capitalize(), \
                    f"Spec {spec_id}: element '{elem}' should be title case '{elem.capitalize()}'"

    def test_spec_has_grades(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        spec = loader.get("ES-M0001C")
        assert "grades" in spec
        assert "4140" in spec["grades"]

    def test_spec_has_uns(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        spec = loader.get("ES-M0001C")
        assert spec.get("uns") == "G41400"

    def test_all_specs_returns_dict(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        all_specs = loader.all_specs()
        assert isinstance(all_specs, dict)
        assert len(all_specs) == 4

    def test_reload_does_not_crash(self, specs_dir):
        loader = SpecLoader.get_instance(specs_dir)
        loader.reload()
        assert len(loader.list_ids()) == 4

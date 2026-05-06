import pytest

from lambdas.anpr_processor.plate_validator import clean_plate, validate_nz_plate, process_plate


class TestCleanPlate:
    def test_strips_spaces_and_special_chars(self):
        assert clean_plate("AB C-123") == "ABC123"

    def test_uppercases(self):
        assert clean_plate("abc123") == "ABC123"

    def test_empty(self):
        assert clean_plate("") == ""


class TestValidateNzPlate:
    def test_standard_format(self):
        assert validate_nz_plate("ABC123") is True

    def test_two_letter_four_digit(self):
        assert validate_nz_plate("AB1234") is True

    def test_older_formats(self):
        assert validate_nz_plate("ABC12") is True
        assert validate_nz_plate("AB123") is True

    def test_single_letter(self):
        assert validate_nz_plate("A1234") is True
        assert validate_nz_plate("A12345") is True

    def test_trailer(self):
        assert validate_nz_plate("ABC123D") is True

    def test_too_short(self):
        assert validate_nz_plate("A") is False

    def test_too_long(self):
        assert validate_nz_plate("ABCD12345") is False

    def test_invalid_pattern(self):
        assert validate_nz_plate("123ABC") is False


class TestProcessPlate:
    def test_valid_plate_preserves_confidence(self):
        rego, conf = process_plate("ABC123", 0.9)
        assert rego == "ABC123"
        assert conf == 0.9

    def test_invalid_format_penalises_confidence(self):
        rego, conf = process_plate("123ABC", 0.9)
        assert rego == "123ABC"
        assert conf == pytest.approx(0.6)

    def test_empty_returns_none(self):
        rego, conf = process_plate("", 0.9)
        assert rego is None
        assert conf == 0.0

    def test_cleans_input(self):
        rego, conf = process_plate("ab c-123", 0.85)
        assert rego == "ABC123"
        assert conf == 0.85

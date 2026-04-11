from app.services.normalization import (
    extract_detail,
    extract_merchant,
    normalize_description,
)


class TestNormalizeDescription:
    def test_strips_whitespace(self):
        assert normalize_description("  hello  ") == "hello"

    def test_collapses_spaces(self):
        assert normalize_description("a   b   c") == "a b c"

    def test_replaces_nbsp(self):
        assert normalize_description("a\u00a0b") == "a b"

    def test_empty_string(self):
        assert normalize_description("") == ""

    def test_none_input(self):
        assert normalize_description(None) == ""


class TestExtractMerchant:
    def test_simple_description(self):
        result = extract_merchant("WALMART SUPERCENTER")
        assert result == "WALMART SUPERCENTER"

    def test_removes_leading_reference(self):
        result = extract_merchant("8521333D701012T4L SAM'S CLUB #123")
        assert result == "SAM'S CLUB"

    def test_sams_club_special_case(self):
        result = extract_merchant("SAM'S CLUB #8255, BENTONVILLE AR")
        assert result == "SAM'S CLUB"

    def test_check_returns_check(self):
        assert extract_merchant("CHECK - ITEM PROCESSING 1234") == "CHECK"
        assert extract_merchant("CHECK 5678") == "CHECK"

    def test_removes_trailing_reference(self):
        result = extract_merchant("ALERT 360 *040410443")
        assert result == "ALERT 360"

    def test_asterisk_processor_prefix(self):
        # Short alpha left side = processor prefix, take right side
        result = extract_merchant("SQ *COFFEE SHOP")
        assert result == "COFFEE SHOP"

    def test_asterisk_non_prefix(self):
        # Left side > 8 chars or non-alpha, take left side
        result = extract_merchant("SOME MERCHANT *1234567")
        assert result == "SOME MERCHANT"

    def test_removes_dotcom(self):
        result = extract_merchant("AMAZON.COM")
        assert result == "AMAZON"

    def test_anbtx_prefix_removal(self):
        result = extract_merchant("EXTERNAL WITHDRAWAL WALMART")
        assert result == "WALMART"

    def test_external_deposit_prefix(self):
        result = extract_merchant("EXTERNAL DEPOSIT PAYROLL INC")
        assert result == "PAYROLL INC"


class TestExtractDetail:
    def test_extracts_remainder_after_merchant(self):
        result = extract_detail("WALMART SUPERCENTER - GROCERIES", "WALMART SUPERCENTER")
        assert result == "GROCERIES"

    def test_sams_club_comma_split(self):
        result = extract_detail("SAM'S CLUB #8255, UNLEADED FUEL 10GAL", "SAM'S CLUB")
        assert result == "UNLEADED FUEL 10GAL"

    def test_returns_full_description_when_merchant_not_found(self):
        result = extract_detail("RANDOM STORE PURCHASE", "NOT FOUND MERCHANT")
        assert result == "RANDOM STORE PURCHASE"

    def test_empty_merchant(self):
        result = extract_detail("SOME DESCRIPTION", "")
        assert result == "SOME DESCRIPTION"

    def test_returns_original_when_remainder_empty(self):
        result = extract_detail("WALMART", "WALMART")
        assert result == "WALMART"

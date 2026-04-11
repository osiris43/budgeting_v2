from app.models import MerchantRule
from app.services.categorization import apply_rules


class TestApplyRules:
    def test_matching_rule_returns_category(self, db, categories):
        db.session.add(MerchantRule(
            pattern="WALMART",
            category_id=categories["Groceries"].id,
        ))
        db.session.flush()

        result = apply_rules(merchant="WALMART", description_clean="some detail")
        assert result is not None
        assert result.name == "Groceries"

    def test_no_matching_rule_returns_none(self, db, categories):
        db.session.add(MerchantRule(
            pattern="WALMART",
            category_id=categories["Groceries"].id,
        ))
        db.session.flush()

        result = apply_rules(merchant="TARGET", description_clean="some detail")
        assert result is None

    def test_case_insensitive_matching(self, db, categories):
        db.session.add(MerchantRule(
            pattern="walmart",
            category_id=categories["Groceries"].id,
        ))
        db.session.flush()

        result = apply_rules(merchant="WALMART", description_clean="stuff")
        assert result is not None
        assert result.name == "Groceries"

    def test_matches_against_description_clean(self, db, categories):
        db.session.add(MerchantRule(
            pattern="UNLEADED",
            category_id=categories["Gas"].id,
        ))
        db.session.flush()

        result = apply_rules(merchant="SAM'S CLUB", description_clean="UNLEADED FUEL")
        assert result is not None
        assert result.name == "Gas"

    def test_none_merchant(self, db, categories):
        db.session.add(MerchantRule(
            pattern="PAYROLL",
            category_id=categories["Income"].id,
        ))
        db.session.flush()

        result = apply_rules(merchant=None, description_clean="PAYROLL DEPOSIT")
        assert result is not None
        assert result.name == "Income"

    def test_first_matching_rule_wins(self, db, categories):
        db.session.add(MerchantRule(
            pattern="SAMS",
            category_id=categories["Groceries"].id,
        ))
        db.session.flush()
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            category_id=categories["Gas"].id,
        ))
        db.session.flush()

        result = apply_rules(merchant="SAMS CLUB", description_clean="stuff")
        assert result is not None
        # First rule matched
        assert result.name == "Groceries"


class TestDetailPatternRules:
    def test_detail_pattern_matches(self, db, categories):
        """Rule with matching detail_pattern returns its category."""
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            detail_pattern="UNLEADED|GALLONS|GAS",
            category_id=categories["Gas"].id,
        ))
        db.session.flush()

        result = apply_rules(
            merchant="SAMS CLUB",
            description_clean="UNLEADED FUEL 10 GALLONS",
        )
        assert result is not None
        assert result.name == "Gas"

    def test_detail_pattern_no_match_falls_to_fallback(self, db, categories):
        """When detail_pattern doesn't match, fallback rule (no detail_pattern) is used."""
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            detail_pattern="UNLEADED|GALLONS|GAS",
            category_id=categories["Gas"].id,
        ))
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            category_id=categories["Groceries"].id,
        ))
        db.session.flush()

        result = apply_rules(
            merchant="SAMS CLUB",
            description_clean="CHICKEN BREAST ORGANIC",
        )
        assert result is not None
        assert result.name == "Groceries"

    def test_detail_pattern_no_match_no_fallback_returns_none(self, db, categories):
        """When detail_pattern doesn't match and there's no fallback, returns None."""
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            detail_pattern="UNLEADED|GALLONS|GAS",
            category_id=categories["Gas"].id,
        ))
        db.session.flush()

        result = apply_rules(
            merchant="SAMS CLUB",
            description_clean="CHICKEN BREAST ORGANIC",
        )
        assert result is None

    def test_detail_pattern_takes_priority_over_fallback(self, db, categories):
        """Specific rule (with detail_pattern) wins over fallback rule."""
        # Fallback rule added first
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            category_id=categories["Groceries"].id,
        ))
        db.session.flush()
        # Specific rule added second
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            detail_pattern="UNLEADED|GALLONS|GAS",
            category_id=categories["Gas"].id,
        ))
        db.session.flush()

        result = apply_rules(
            merchant="SAMS CLUB",
            description_clean="UNLEADED FUEL 10 GALLONS",
        )
        assert result is not None
        assert result.name == "Gas"

    def test_detail_pattern_case_insensitive(self, db, categories):
        """detail_pattern matching is case-insensitive."""
        db.session.add(MerchantRule(
            pattern="SAMS CLUB",
            detail_pattern="unleaded|gallons",
            category_id=categories["Gas"].id,
        ))
        db.session.flush()

        result = apply_rules(
            merchant="SAMS CLUB",
            description_clean="UNLEADED FUEL 10 GALLONS",
        )
        assert result is not None
        assert result.name == "Gas"

    def test_rule_without_detail_pattern_still_works(self, db, categories):
        """Rules without detail_pattern continue to work as before."""
        db.session.add(MerchantRule(
            pattern="WALMART",
            category_id=categories["Groceries"].id,
        ))
        db.session.flush()

        result = apply_rules(merchant="WALMART", description_clean="GROCERIES")
        assert result is not None
        assert result.name == "Groceries"

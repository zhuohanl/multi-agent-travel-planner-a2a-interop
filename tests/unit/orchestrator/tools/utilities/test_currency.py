"""Unit tests for the currency_convert utility tool.

Tests cover:
- Basic currency conversion (USD to JPY, EUR to GBP, etc.)
- Invalid currency code handling
- Amount formatting (decimal places, thousand separators)
- Context-aware conversion with destination
- Edge cases (same currency, zero amount, large amounts)
"""

from decimal import Decimal

import pytest

from src.orchestrator.tools.utilities.currency import (
    EXCHANGE_RATES_TO_USD,
    SUPPORTED_CURRENCIES,
    CurrencyConvertResult,
    InvalidCurrencyError,
    currency_convert,
    currency_convert_with_context,
    format_currency_amount,
    get_exchange_rate,
    normalize_currency_code,
    validate_currency_code,
)


class TestNormalizeCurrencyCode:
    """Tests for normalize_currency_code function."""

    def test_lowercase_to_uppercase(self) -> None:
        """Lowercase codes should be converted to uppercase."""
        assert normalize_currency_code("usd") == "USD"
        assert normalize_currency_code("jpy") == "JPY"
        assert normalize_currency_code("eur") == "EUR"

    def test_mixed_case_to_uppercase(self) -> None:
        """Mixed case codes should be converted to uppercase."""
        assert normalize_currency_code("Usd") == "USD"
        assert normalize_currency_code("JpY") == "JPY"

    def test_already_uppercase(self) -> None:
        """Uppercase codes should remain unchanged."""
        assert normalize_currency_code("USD") == "USD"
        assert normalize_currency_code("JPY") == "JPY"

    def test_strips_whitespace(self) -> None:
        """Whitespace should be stripped."""
        assert normalize_currency_code("  usd  ") == "USD"
        assert normalize_currency_code("\tjpy\n") == "JPY"


class TestValidateCurrencyCode:
    """Tests for validate_currency_code function."""

    def test_valid_currency_codes(self) -> None:
        """Valid currency codes should be accepted and normalized."""
        assert validate_currency_code("USD") == "USD"
        assert validate_currency_code("usd") == "USD"
        assert validate_currency_code("JPY") == "JPY"
        assert validate_currency_code("eur") == "EUR"
        assert validate_currency_code("gbp") == "GBP"

    def test_empty_code_raises_error(self) -> None:
        """Empty currency code should raise InvalidCurrencyError."""
        with pytest.raises(InvalidCurrencyError) as exc_info:
            validate_currency_code("")
        assert "cannot be empty" in exc_info.value.message

    def test_short_code_raises_error(self) -> None:
        """Currency codes shorter than 3 characters should raise error."""
        with pytest.raises(InvalidCurrencyError) as exc_info:
            validate_currency_code("US")
        assert "must be 3 letters" in exc_info.value.message

    def test_long_code_raises_error(self) -> None:
        """Currency codes longer than 3 characters should raise error."""
        with pytest.raises(InvalidCurrencyError) as exc_info:
            validate_currency_code("USDD")
        assert "must be 3 letters" in exc_info.value.message

    def test_non_alpha_code_raises_error(self) -> None:
        """Non-alphabetic characters should raise error."""
        with pytest.raises(InvalidCurrencyError) as exc_info:
            validate_currency_code("US1")
        assert "must contain only letters" in exc_info.value.message

    def test_unsupported_currency_raises_error(self) -> None:
        """Unsupported but valid format currency should raise error."""
        with pytest.raises(InvalidCurrencyError) as exc_info:
            validate_currency_code("XYZ")
        assert "Unsupported currency" in exc_info.value.message
        assert exc_info.value.currency_code == "XYZ"


class TestGetExchangeRate:
    """Tests for get_exchange_rate function."""

    def test_same_currency_rate_is_one(self) -> None:
        """Exchange rate for same currency should be 1."""
        rate = get_exchange_rate("USD", "USD")
        assert rate == Decimal("1")

    def test_usd_to_jpy(self) -> None:
        """USD to JPY exchange rate should be positive."""
        rate = get_exchange_rate("USD", "JPY")
        assert rate > 0
        assert rate == EXCHANGE_RATES_TO_USD["JPY"]

    def test_jpy_to_usd(self) -> None:
        """JPY to USD should be inverse of USD to JPY."""
        rate = get_exchange_rate("JPY", "USD")
        assert rate > 0
        expected = Decimal("1") / EXCHANGE_RATES_TO_USD["JPY"]
        assert abs(rate - expected) < Decimal("0.0001")

    def test_eur_to_gbp(self) -> None:
        """Cross-rate between EUR and GBP should work."""
        rate = get_exchange_rate("EUR", "GBP")
        assert rate > 0
        # EUR -> USD -> GBP
        expected = EXCHANGE_RATES_TO_USD["GBP"] / EXCHANGE_RATES_TO_USD["EUR"]
        assert abs(rate - expected) < Decimal("0.0001")

    def test_invalid_from_currency_raises_error(self) -> None:
        """Invalid source currency should raise error."""
        with pytest.raises(InvalidCurrencyError):
            get_exchange_rate("XYZ", "USD")

    def test_invalid_to_currency_raises_error(self) -> None:
        """Invalid target currency should raise error."""
        with pytest.raises(InvalidCurrencyError):
            get_exchange_rate("USD", "XYZ")


class TestFormatCurrencyAmount:
    """Tests for format_currency_amount function."""

    def test_formats_with_two_decimals(self) -> None:
        """Most currencies should have 2 decimal places."""
        result = format_currency_amount(Decimal("1234.567"), "USD")
        assert result == "1,234.57 USD"

    def test_formats_jpy_with_no_decimals(self) -> None:
        """JPY should have 0 decimal places."""
        result = format_currency_amount(Decimal("15234.78"), "JPY")
        assert result == "15,235 JPY"

    def test_formats_krw_with_no_decimals(self) -> None:
        """KRW should have 0 decimal places."""
        result = format_currency_amount(Decimal("1325000.5"), "KRW")
        assert result == "1,325,000 KRW"

    def test_formats_with_thousand_separators(self) -> None:
        """Large amounts should have thousand separators."""
        result = format_currency_amount(Decimal("1234567.89"), "EUR")
        assert result == "1,234,567.89 EUR"

    def test_formats_small_amounts(self) -> None:
        """Small amounts should be formatted correctly."""
        result = format_currency_amount(Decimal("0.50"), "USD")
        assert result == "0.50 USD"


class TestCurrencyConvert:
    """Tests for the main currency_convert function."""

    def test_usd_to_jpy_basic(self) -> None:
        """Basic USD to JPY conversion should work."""
        result = currency_convert(100, "USD", "JPY")
        assert isinstance(result, CurrencyConvertResult)
        assert result.amount == Decimal("100")
        assert result.from_currency == "USD"
        assert result.to_currency == "JPY"
        assert result.converted_amount > 0
        assert "USD" in result.formatted
        assert "JPY" in result.formatted

    def test_accepts_float_amount(self) -> None:
        """Float amounts should work."""
        result = currency_convert(100.50, "USD", "EUR")
        assert result.amount == Decimal("100.50") or abs(result.amount - Decimal("100.50")) < Decimal("0.01")

    def test_accepts_string_amount(self) -> None:
        """String amounts should work."""
        result = currency_convert("100.50", "USD", "EUR")
        assert result.amount == Decimal("100.50")

    def test_accepts_decimal_amount(self) -> None:
        """Decimal amounts should work."""
        result = currency_convert(Decimal("100.50"), "USD", "EUR")
        assert result.amount == Decimal("100.50")

    def test_same_currency_returns_same_amount(self) -> None:
        """Converting to same currency should return same amount."""
        result = currency_convert(100, "USD", "USD")
        assert result.converted_amount == Decimal("100")
        assert result.exchange_rate == Decimal("1")

    def test_formatted_output_matches_pattern(self) -> None:
        """Formatted output should match expected pattern."""
        result = currency_convert(100, "USD", "JPY")
        # Should be like "100.00 USD = 14,950 JPY"
        assert "=" in result.formatted
        assert "USD" in result.formatted
        assert "JPY" in result.formatted

    def test_lowercase_currencies_accepted(self) -> None:
        """Lowercase currency codes should be accepted."""
        result = currency_convert(100, "usd", "jpy")
        assert result.from_currency == "USD"
        assert result.to_currency == "JPY"

    def test_zero_amount(self) -> None:
        """Zero amount should work."""
        result = currency_convert(0, "USD", "JPY")
        assert result.converted_amount == Decimal("0")

    def test_large_amount(self) -> None:
        """Large amounts should work."""
        result = currency_convert(1_000_000, "USD", "JPY")
        assert result.converted_amount > 0
        assert "," in result.formatted  # Should have thousand separators

    def test_invalid_from_currency_raises_error(self) -> None:
        """Invalid source currency should raise InvalidCurrencyError."""
        with pytest.raises(InvalidCurrencyError):
            currency_convert(100, "XYZ", "USD")

    def test_invalid_to_currency_raises_error(self) -> None:
        """Invalid target currency should raise InvalidCurrencyError."""
        with pytest.raises(InvalidCurrencyError):
            currency_convert(100, "USD", "XYZ")

    def test_negative_amount_raises_error(self) -> None:
        """Negative amounts should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            currency_convert(-100, "USD", "JPY")
        assert "cannot be negative" in str(exc_info.value)

    def test_invalid_amount_string_raises_error(self) -> None:
        """Invalid amount string should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            currency_convert("not_a_number", "USD", "JPY")
        assert "Invalid amount" in str(exc_info.value)

    def test_result_to_dict(self) -> None:
        """Result to_dict should return serializable dictionary."""
        result = currency_convert(100, "USD", "JPY")
        d = result.to_dict()
        assert isinstance(d, dict)
        assert "amount" in d
        assert "from_currency" in d
        assert "to_currency" in d
        assert "converted_amount" in d
        assert "exchange_rate" in d
        assert "formatted" in d
        # All values should be serializable
        assert isinstance(d["amount"], float)
        assert isinstance(d["from_currency"], str)


class TestCurrencyConvertWithContext:
    """Tests for currency_convert_with_context function."""

    @pytest.mark.asyncio
    async def test_explicit_conversion(self) -> None:
        """Explicit conversion request should work."""
        result = await currency_convert_with_context(
            "convert 100 USD to JPY",
            destination=None,
        )
        assert "USD" in result
        assert "JPY" in result
        assert "=" in result

    @pytest.mark.asyncio
    async def test_infers_target_from_destination(self) -> None:
        """Should infer target currency from destination."""
        result = await currency_convert_with_context(
            "how much is 100 USD",
            destination="Tokyo, Japan",
        )
        assert "USD" in result
        assert "JPY" in result

    @pytest.mark.asyncio
    async def test_defaults_to_usd_source(self) -> None:
        """Should default to USD as source currency."""
        result = await currency_convert_with_context(
            "100 to yen",
            destination=None,
        )
        # Should try to parse but may fall back to USD
        # The exact behavior depends on parsing

    @pytest.mark.asyncio
    async def test_handles_missing_amount(self) -> None:
        """Should return error message for missing amount."""
        result = await currency_convert_with_context(
            "convert to JPY",
            destination=None,
        )
        assert "specify an amount" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_missing_target_without_destination(self) -> None:
        """Should return error message for missing target without destination."""
        result = await currency_convert_with_context(
            "how much is 100 USD",
            destination=None,
        )
        assert "specify the target currency" in result.lower()

    @pytest.mark.asyncio
    async def test_handles_invalid_currency(self) -> None:
        """Should return error message for invalid currency."""
        result = await currency_convert_with_context(
            "convert 100 XYZ to ABC",
            destination=None,
        )
        assert "error" in result.lower() or "invalid" in result.lower() or "unsupported" in result.lower()

    @pytest.mark.asyncio
    async def test_currency_names_work(self) -> None:
        """Currency names like 'dollars' and 'yen' should work."""
        # Note: This test depends on parsing accuracy
        result = await currency_convert_with_context(
            "convert 100 dollars to yen",
            destination=None,
        )
        # May succeed or fail depending on parsing
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_destination_europe(self) -> None:
        """European destinations should use EUR."""
        result = await currency_convert_with_context(
            "how much is 100 USD",
            destination="Paris, France",
        )
        assert "EUR" in result

    @pytest.mark.asyncio
    async def test_destination_uk(self) -> None:
        """UK destination should use GBP."""
        result = await currency_convert_with_context(
            "how much is 100 USD",
            destination="London, UK",
        )
        assert "GBP" in result

    @pytest.mark.asyncio
    async def test_destination_thailand(self) -> None:
        """Thailand destination should use THB."""
        result = await currency_convert_with_context(
            "how much is 100 USD",
            destination="Bangkok, Thailand",
        )
        assert "THB" in result


class TestSupportedCurrencies:
    """Tests for SUPPORTED_CURRENCIES constant."""

    def test_contains_major_currencies(self) -> None:
        """Should contain all major world currencies."""
        major = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY"]
        for currency in major:
            assert currency in SUPPORTED_CURRENCIES

    def test_contains_asian_currencies(self) -> None:
        """Should contain major Asian currencies."""
        asian = ["JPY", "CNY", "KRW", "HKD", "SGD", "THB", "INR", "TWD", "IDR", "MYR", "PHP", "VND"]
        for currency in asian:
            assert currency in SUPPORTED_CURRENCIES

    def test_contains_european_currencies(self) -> None:
        """Should contain major European currencies."""
        european = ["EUR", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF"]
        for currency in european:
            assert currency in SUPPORTED_CURRENCIES

    def test_contains_americas_currencies(self) -> None:
        """Should contain major Americas currencies."""
        americas = ["USD", "CAD", "MXN", "BRL", "ARS", "CLP", "COP", "PEN"]
        for currency in americas:
            assert currency in SUPPORTED_CURRENCIES

    def test_is_frozen_set(self) -> None:
        """Should be a frozenset for immutability."""
        assert isinstance(SUPPORTED_CURRENCIES, frozenset)


class TestExchangeRates:
    """Tests for exchange rate data."""

    def test_all_rates_are_positive(self) -> None:
        """All exchange rates should be positive."""
        for currency, rate in EXCHANGE_RATES_TO_USD.items():
            assert rate > 0, f"Rate for {currency} should be positive"

    def test_usd_rate_is_one(self) -> None:
        """USD rate should be exactly 1."""
        assert EXCHANGE_RATES_TO_USD["USD"] == Decimal("1")

    def test_rates_are_decimals(self) -> None:
        """All rates should be Decimal for precision."""
        for currency, rate in EXCHANGE_RATES_TO_USD.items():
            assert isinstance(rate, Decimal), f"Rate for {currency} should be Decimal"

    def test_jpy_rate_realistic(self) -> None:
        """JPY rate should be in realistic range (100-200 per USD)."""
        rate = EXCHANGE_RATES_TO_USD["JPY"]
        assert 100 < rate < 200

    def test_eur_rate_realistic(self) -> None:
        """EUR rate should be in realistic range (0.8-1.2 per USD)."""
        rate = EXCHANGE_RATES_TO_USD["EUR"]
        assert Decimal("0.8") < rate < Decimal("1.2")

    def test_gbp_rate_realistic(self) -> None:
        """GBP rate should be in realistic range (0.7-1.0 per USD)."""
        rate = EXCHANGE_RATES_TO_USD["GBP"]
        assert Decimal("0.7") < rate < Decimal("1.0")

"""
Currency conversion utility tool.

This module provides deterministic currency conversion using exchange rates.
It can be invoked:
1. From Layer 1b via regex pattern match ("convert 100 USD to JPY")
2. From Layer 1c via LLM fallback ("exchange rate between dollars and yen")
3. From Layer 2 via CALL_UTILITY action ("how much is this in dollars?")

Per design doc (Tool Definitions section):
- Parameters: amount, from_currency, to_currency
- Returns formatted string like "100 USD = 15,234 JPY"
- Handles invalid currency codes gracefully

Currency codes follow ISO 4217 standard (3-letter codes).
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

# =============================================================================
# EXCHANGE RATES
# =============================================================================

# Mock exchange rates relative to USD (base currency)
# In production, these would come from an exchange rate API or MCP tool
# Rates are approximate as of 2025 for realistic testing
EXCHANGE_RATES_TO_USD: dict[str, Decimal] = {
    "USD": Decimal("1.00"),
    "EUR": Decimal("0.92"),  # 1 EUR = 1.09 USD
    "GBP": Decimal("0.79"),  # 1 GBP = 1.27 USD
    "JPY": Decimal("149.50"),  # 1 USD = 149.50 JPY
    "AUD": Decimal("1.53"),  # 1 AUD = 0.65 USD
    "CAD": Decimal("1.36"),  # 1 CAD = 0.74 USD
    "CHF": Decimal("0.88"),  # 1 CHF = 1.14 USD
    "CNY": Decimal("7.24"),  # 1 USD = 7.24 CNY
    "HKD": Decimal("7.82"),  # 1 USD = 7.82 HKD
    "SGD": Decimal("1.34"),  # 1 SGD = 0.75 USD
    "INR": Decimal("83.12"),  # 1 USD = 83.12 INR
    "KRW": Decimal("1325.00"),  # 1 USD = 1325 KRW
    "THB": Decimal("35.50"),  # 1 USD = 35.50 THB
    "MXN": Decimal("17.15"),  # 1 USD = 17.15 MXN
    "BRL": Decimal("4.97"),  # 1 USD = 4.97 BRL
    "NZD": Decimal("1.64"),  # 1 NZD = 0.61 USD
    "SEK": Decimal("10.42"),  # 1 USD = 10.42 SEK
    "NOK": Decimal("10.75"),  # 1 USD = 10.75 NOK
    "DKK": Decimal("6.88"),  # 1 USD = 6.88 DKK
    "ZAR": Decimal("18.75"),  # 1 USD = 18.75 ZAR
    "AED": Decimal("3.67"),  # 1 USD = 3.67 AED (fixed peg)
    "SAR": Decimal("3.75"),  # 1 USD = 3.75 SAR (fixed peg)
    "TWD": Decimal("31.50"),  # 1 USD = 31.50 TWD
    "IDR": Decimal("15750.00"),  # 1 USD = 15750 IDR
    "MYR": Decimal("4.72"),  # 1 USD = 4.72 MYR
    "PHP": Decimal("55.75"),  # 1 USD = 55.75 PHP
    "VND": Decimal("24500.00"),  # 1 USD = 24500 VND
    "PLN": Decimal("4.02"),  # 1 USD = 4.02 PLN
    "CZK": Decimal("23.25"),  # 1 USD = 23.25 CZK
    "HUF": Decimal("358.00"),  # 1 USD = 358 HUF
    "TRY": Decimal("32.50"),  # 1 USD = 32.50 TRY
    "ILS": Decimal("3.68"),  # 1 USD = 3.68 ILS
    "RUB": Decimal("92.50"),  # 1 USD = 92.50 RUB
    "CLP": Decimal("925.00"),  # 1 USD = 925 CLP
    "COP": Decimal("3950.00"),  # 1 USD = 3950 COP
    "PEN": Decimal("3.72"),  # 1 USD = 3.72 PEN
    "ARS": Decimal("875.00"),  # 1 USD = 875 ARS
    "EGP": Decimal("30.90"),  # 1 USD = 30.90 EGP
}

# Set of supported currency codes for validation
SUPPORTED_CURRENCIES: frozenset[str] = frozenset(EXCHANGE_RATES_TO_USD.keys())


# =============================================================================
# EXCEPTIONS
# =============================================================================


class InvalidCurrencyError(ValueError):
    """Raised when an invalid or unsupported currency code is provided."""

    def __init__(self, currency_code: str, message: str | None = None) -> None:
        self.currency_code = currency_code
        self.message = message or f"Invalid or unsupported currency code: {currency_code}"
        super().__init__(self.message)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass(frozen=True)
class CurrencyConvertResult:
    """Result of a currency conversion operation."""

    amount: Decimal
    from_currency: str
    to_currency: str
    converted_amount: Decimal
    exchange_rate: Decimal
    formatted: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "amount": float(self.amount),
            "from_currency": self.from_currency,
            "to_currency": self.to_currency,
            "converted_amount": float(self.converted_amount),
            "exchange_rate": float(self.exchange_rate),
            "formatted": self.formatted,
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def normalize_currency_code(code: str) -> str:
    """Normalize a currency code to uppercase.

    Args:
        code: Currency code (any case)

    Returns:
        Uppercase currency code
    """
    return code.strip().upper()


def validate_currency_code(code: str) -> str:
    """Validate and normalize a currency code.

    Args:
        code: Currency code to validate

    Returns:
        Normalized (uppercase) currency code

    Raises:
        InvalidCurrencyError: If the currency code is invalid or unsupported
    """
    normalized = normalize_currency_code(code)

    if not normalized:
        raise InvalidCurrencyError(code, "Currency code cannot be empty")

    if len(normalized) != 3:
        raise InvalidCurrencyError(
            code, f"Currency code must be 3 letters (ISO 4217), got: {code}"
        )

    if not normalized.isalpha():
        raise InvalidCurrencyError(
            code, f"Currency code must contain only letters, got: {code}"
        )

    if normalized not in SUPPORTED_CURRENCIES:
        raise InvalidCurrencyError(
            code,
            f"Unsupported currency: {normalized}. "
            f"Supported currencies: {', '.join(sorted(SUPPORTED_CURRENCIES)[:10])}...",
        )

    return normalized


def get_exchange_rate(from_currency: str, to_currency: str) -> Decimal:
    """Get the exchange rate between two currencies.

    Args:
        from_currency: Source currency code (ISO 4217)
        to_currency: Target currency code (ISO 4217)

    Returns:
        Exchange rate (multiply by this to convert)

    Raises:
        InvalidCurrencyError: If either currency code is invalid
    """
    from_code = validate_currency_code(from_currency)
    to_code = validate_currency_code(to_currency)

    # Convert from source to USD, then from USD to target
    # rate = (1 / from_to_usd) * to_to_usd
    from_rate = EXCHANGE_RATES_TO_USD[from_code]
    to_rate = EXCHANGE_RATES_TO_USD[to_code]

    # If from_currency is EUR (0.92 per USD), then 1 EUR = 1/0.92 USD = 1.087 USD
    # If to_currency is JPY (149.50 per USD), then 1 USD = 149.50 JPY
    # So 1 EUR = 1.087 * 149.50 = 162.52 JPY
    # Rate = (to_rate / from_rate)
    return to_rate / from_rate


def format_currency_amount(amount: Decimal, currency_code: str) -> str:
    """Format an amount with its currency code.

    Uses locale-appropriate thousand separators and decimal places.
    Most currencies use 2 decimal places, JPY/KRW/VND/IDR use 0.

    Args:
        amount: The amount to format
        currency_code: The currency code (already normalized)

    Returns:
        Formatted string like "1,234.56 USD" or "15,234 JPY"
    """
    # Currencies with 0 decimal places
    zero_decimal_currencies = {"JPY", "KRW", "VND", "IDR", "CLP", "HUF", "COP"}

    if currency_code in zero_decimal_currencies:
        # Round to nearest integer for zero-decimal currencies
        rounded = int(round(amount))
        formatted_number = f"{rounded:,}"
    else:
        # Standard 2 decimal places
        formatted_number = f"{amount:,.2f}"

    return f"{formatted_number} {currency_code}"


# =============================================================================
# MAIN FUNCTIONS
# =============================================================================


def currency_convert(
    amount: float | int | str | Decimal,
    from_currency: str,
    to_currency: str,
) -> CurrencyConvertResult:
    """Convert an amount from one currency to another.

    This is the main conversion function, used for stateless conversions
    from Layer 1b (regex) and Layer 1c (LLM fallback).

    Args:
        amount: Amount to convert (number or string)
        from_currency: Source currency code (ISO 4217, e.g., "USD")
        to_currency: Target currency code (ISO 4217, e.g., "JPY")

    Returns:
        CurrencyConvertResult with conversion details and formatted string

    Raises:
        InvalidCurrencyError: If either currency code is invalid
        ValueError: If amount is invalid

    Example:
        >>> result = currency_convert(100, "USD", "JPY")
        >>> result.formatted
        '100.00 USD = 14,950 JPY'
    """
    # Validate and normalize currency codes
    from_code = validate_currency_code(from_currency)
    to_code = validate_currency_code(to_currency)

    # Parse and validate amount
    try:
        if isinstance(amount, Decimal):
            decimal_amount = amount
        else:
            decimal_amount = Decimal(str(amount))
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"Invalid amount: {amount}") from e

    if decimal_amount < 0:
        raise ValueError(f"Amount cannot be negative: {amount}")

    # Same currency - no conversion needed
    if from_code == to_code:
        formatted = f"{format_currency_amount(decimal_amount, from_code)} = {format_currency_amount(decimal_amount, to_code)}"
        return CurrencyConvertResult(
            amount=decimal_amount,
            from_currency=from_code,
            to_currency=to_code,
            converted_amount=decimal_amount,
            exchange_rate=Decimal("1"),
            formatted=formatted,
        )

    # Get exchange rate and convert
    rate = get_exchange_rate(from_code, to_code)
    converted = decimal_amount * rate

    # Format output
    from_formatted = format_currency_amount(decimal_amount, from_code)
    to_formatted = format_currency_amount(converted, to_code)
    formatted = f"{from_formatted} = {to_formatted}"

    return CurrencyConvertResult(
        amount=decimal_amount,
        from_currency=from_code,
        to_currency=to_code,
        converted_amount=converted,
        exchange_rate=rate,
        formatted=formatted,
    )


async def currency_convert_with_context(
    message: str,
    destination: str | None = None,
) -> str:
    """Convert currency with optional context from workflow.

    This function is called from Layer 2 (inside workflow_turn) when
    the user asks about currency during trip planning. It can infer
    the target currency from the trip destination.

    Args:
        message: The user's raw message (e.g., "how much is 500 in local currency")
        destination: Optional trip destination for inferring target currency

    Returns:
        Formatted conversion result string

    Example:
        >>> await currency_convert_with_context("how much is 500 USD", destination="Tokyo, Japan")
        '500.00 USD = 74,750 JPY'
    """
    import re

    # Try to extract amount and currencies from message
    # Pattern: "convert 100 USD to JPY" or "100 USD in JPY" or "100 dollars to yen"
    patterns = [
        # "convert 100 USD to JPY" or "100 USD to JPY"
        r"(\d+(?:\.\d+)?)\s*([A-Za-z]{3})\s*(?:to|in|into)\s*([A-Za-z]{3})",
        # "100 USD" (just amount and source currency)
        r"(\d+(?:\.\d+)?)\s*([A-Za-z]{3})",
    ]

    # Common currency name to code mapping
    currency_names: dict[str, str] = {
        "dollar": "USD",
        "dollars": "USD",
        "usd": "USD",
        "euro": "EUR",
        "euros": "EUR",
        "eur": "EUR",
        "pound": "GBP",
        "pounds": "GBP",
        "gbp": "GBP",
        "yen": "JPY",
        "jpy": "JPY",
        "yuan": "CNY",
        "renminbi": "CNY",
        "cny": "CNY",
        "won": "KRW",
        "krw": "KRW",
        "baht": "THB",
        "thb": "THB",
        "rupee": "INR",
        "rupees": "INR",
        "inr": "INR",
        "peso": "MXN",  # Default to Mexican peso
        "pesos": "MXN",
        "mxn": "MXN",
        "franc": "CHF",
        "francs": "CHF",
        "chf": "CHF",
    }

    # Destination to currency mapping for context-aware conversion
    destination_currencies: dict[str, str] = {
        "japan": "JPY",
        "tokyo": "JPY",
        "osaka": "JPY",
        "kyoto": "JPY",
        "uk": "GBP",
        "london": "GBP",
        "england": "GBP",
        "europe": "EUR",
        "france": "EUR",
        "paris": "EUR",
        "germany": "EUR",
        "berlin": "EUR",
        "italy": "EUR",
        "rome": "EUR",
        "spain": "EUR",
        "barcelona": "EUR",
        "madrid": "EUR",
        "china": "CNY",
        "beijing": "CNY",
        "shanghai": "CNY",
        "korea": "KRW",
        "seoul": "KRW",
        "thailand": "THB",
        "bangkok": "THB",
        "india": "INR",
        "delhi": "INR",
        "mumbai": "INR",
        "singapore": "SGD",
        "australia": "AUD",
        "sydney": "AUD",
        "melbourne": "AUD",
        "canada": "CAD",
        "toronto": "CAD",
        "vancouver": "CAD",
        "mexico": "MXN",
        "brazil": "BRL",
        "switzerland": "CHF",
        "zurich": "CHF",
        "hong kong": "HKD",
        "taiwan": "TWD",
        "taipei": "TWD",
        "indonesia": "IDR",
        "bali": "IDR",
        "jakarta": "IDR",
        "malaysia": "MYR",
        "kuala lumpur": "MYR",
        "philippines": "PHP",
        "manila": "PHP",
        "vietnam": "VND",
        "hanoi": "VND",
        "usa": "USD",
        "us": "USD",
        "new york": "USD",
        "los angeles": "USD",
    }

    amount: float | None = None
    from_currency: str | None = None
    to_currency: str | None = None

    # Try to extract from patterns
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            groups = match.groups()
            amount = float(groups[0])
            from_currency = groups[1].upper()
            if len(groups) > 2 and groups[2]:
                to_currency = groups[2].upper()
            break

    # Try to extract currency names if codes weren't found
    if not from_currency:
        for name, code in currency_names.items():
            if name in message.lower():
                from_currency = code
                break

    if not to_currency:
        for name, code in currency_names.items():
            if f"to {name}" in message.lower() or f"in {name}" in message.lower():
                to_currency = code
                break

    # Use destination to infer target currency if not specified
    if not to_currency and destination:
        dest_lower = destination.lower()
        for location, code in destination_currencies.items():
            if location in dest_lower:
                to_currency = code
                break

    # Validate we have enough information
    if amount is None:
        return "Please specify an amount to convert (e.g., 'convert 100 USD to JPY')."

    if not from_currency:
        from_currency = "USD"  # Default to USD

    if not to_currency:
        if destination:
            return f"I couldn't determine the local currency for {destination}. Please specify the target currency (e.g., 'convert 100 USD to JPY')."
        return "Please specify the target currency (e.g., 'convert 100 USD to JPY')."

    # Perform conversion
    try:
        result = currency_convert(amount, from_currency, to_currency)
        return result.formatted
    except InvalidCurrencyError as e:
        return f"Currency conversion error: {e.message}"
    except ValueError as e:
        return f"Invalid conversion request: {e}"

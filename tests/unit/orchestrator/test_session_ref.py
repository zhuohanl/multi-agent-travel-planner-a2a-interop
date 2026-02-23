"""Unit tests for SessionRef and ID generation utilities."""

import pytest

from src.orchestrator.models.session_ref import SessionRef
from src.orchestrator.utils.id_generator import (
    PREFIX_BOOKING,
    PREFIX_CONSULTATION,
    PREFIX_ITINERARY,
    PREFIX_SESSION,
    extract_prefix,
    generate_booking_id,
    generate_consultation_id,
    generate_id,
    generate_itinerary_id,
    generate_session_id,
    validate_id_format,
)


class TestSessionRef:
    """Tests for the SessionRef dataclass."""

    def test_session_ref_allows_multiple_id_types(self):
        """SessionRef can hold any combination of IDs."""
        # All IDs
        ref_all = SessionRef(
            session_id="sess_abc",
            consultation_id="cons_def",
            itinerary_id="itn_ghi",
            booking_id="book_jkl",
        )
        assert ref_all.session_id == "sess_abc"
        assert ref_all.consultation_id == "cons_def"
        assert ref_all.itinerary_id == "itn_ghi"
        assert ref_all.booking_id == "book_jkl"

        # Only session_id
        ref_session = SessionRef(session_id="sess_only")
        assert ref_session.session_id == "sess_only"
        assert ref_session.consultation_id is None

        # Only consultation_id
        ref_cons = SessionRef(consultation_id="cons_only")
        assert ref_cons.session_id is None
        assert ref_cons.consultation_id == "cons_only"

        # Only itinerary_id
        ref_itn = SessionRef(itinerary_id="itn_only")
        assert ref_itn.itinerary_id == "itn_only"

        # Only booking_id
        ref_book = SessionRef(booking_id="book_only")
        assert ref_book.booking_id == "book_only"

    def test_session_ref_has_any_id(self):
        """has_any_id returns True if at least one ID is present."""
        assert SessionRef(session_id="sess_x").has_any_id() is True
        assert SessionRef(consultation_id="cons_x").has_any_id() is True
        assert SessionRef(itinerary_id="itn_x").has_any_id() is True
        assert SessionRef(booking_id="book_x").has_any_id() is True
        assert SessionRef().has_any_id() is False

    def test_session_ref_primary_id_priority(self):
        """primary_id returns highest-priority ID present."""
        # Priority: session_id > consultation_id > itinerary_id > booking_id
        ref = SessionRef(
            session_id="sess_1",
            consultation_id="cons_2",
            itinerary_id="itn_3",
            booking_id="book_4",
        )
        assert ref.primary_id() == "sess_1"

        ref = SessionRef(
            consultation_id="cons_2",
            itinerary_id="itn_3",
            booking_id="book_4",
        )
        assert ref.primary_id() == "cons_2"

        ref = SessionRef(itinerary_id="itn_3", booking_id="book_4")
        assert ref.primary_id() == "itn_3"

        ref = SessionRef(booking_id="book_4")
        assert ref.primary_id() == "book_4"

        ref = SessionRef()
        assert ref.primary_id() is None

    def test_session_ref_to_dict_omits_none(self):
        """to_dict excludes None values."""
        ref = SessionRef(session_id="sess_x", consultation_id="cons_y")
        d = ref.to_dict()
        assert d == {"session_id": "sess_x", "consultation_id": "cons_y"}
        assert "itinerary_id" not in d
        assert "booking_id" not in d

    def test_session_ref_to_dict_empty(self):
        """to_dict returns empty dict when no IDs present."""
        ref = SessionRef()
        assert ref.to_dict() == {}

    def test_session_ref_from_dict(self):
        """from_dict creates SessionRef from dictionary."""
        data = {
            "session_id": "sess_a",
            "consultation_id": "cons_b",
            "itinerary_id": "itn_c",
            "booking_id": "book_d",
        }
        ref = SessionRef.from_dict(data)
        assert ref.session_id == "sess_a"
        assert ref.consultation_id == "cons_b"
        assert ref.itinerary_id == "itn_c"
        assert ref.booking_id == "book_d"

    def test_session_ref_from_dict_partial(self):
        """from_dict handles partial dictionaries."""
        ref = SessionRef.from_dict({"session_id": "sess_only"})
        assert ref.session_id == "sess_only"
        assert ref.consultation_id is None

        ref = SessionRef.from_dict({})
        assert ref.session_id is None
        assert ref.consultation_id is None

    def test_session_ref_is_frozen(self):
        """SessionRef is immutable (frozen dataclass)."""
        ref = SessionRef(session_id="sess_x")
        with pytest.raises(AttributeError):
            ref.session_id = "sess_y"  # type: ignore

    def test_session_ref_equality(self):
        """SessionRef instances are equal if all fields match."""
        ref1 = SessionRef(session_id="sess_a", consultation_id="cons_b")
        ref2 = SessionRef(session_id="sess_a", consultation_id="cons_b")
        ref3 = SessionRef(session_id="sess_a", consultation_id="cons_c")

        assert ref1 == ref2
        assert ref1 != ref3

    def test_session_ref_hashable(self):
        """SessionRef can be used as a dict key or set member."""
        ref1 = SessionRef(session_id="sess_a")
        ref2 = SessionRef(session_id="sess_a")

        # Can use as set member
        s = {ref1, ref2}
        assert len(s) == 1

        # Can use as dict key
        d = {ref1: "value"}
        assert d[ref2] == "value"


class TestGenerateId:
    """Tests for the generate_id function."""

    def test_generate_id_prefixes(self):
        """generate_id produces correctly prefixed IDs."""
        sess_id = generate_id("sess")
        assert sess_id.startswith("sess_")

        cons_id = generate_id("cons")
        assert cons_id.startswith("cons_")

        itn_id = generate_id("itn")
        assert itn_id.startswith("itn_")

        book_id = generate_id("book")
        assert book_id.startswith("book_")

        # Custom prefix
        custom_id = generate_id("custom")
        assert custom_id.startswith("custom_")

    def test_generate_id_uniqueness(self):
        """generate_id produces unique values."""
        # Generate 1000 IDs and verify uniqueness
        ids = [generate_id("test") for _ in range(1000)]
        assert len(set(ids)) == 1000

    def test_generate_id_format(self):
        """generate_id produces valid UUID hex after prefix."""
        id_value = generate_id("test")
        prefix, uuid_part = id_value.split("_", 1)

        assert prefix == "test"
        # UUID hex is 32 characters
        assert len(uuid_part) == 32
        # All characters are valid hex
        int(uuid_part, 16)  # Should not raise

    def test_generate_session_id(self):
        """generate_session_id uses correct prefix."""
        sid = generate_session_id()
        assert sid.startswith(f"{PREFIX_SESSION}_")
        assert validate_id_format(sid, PREFIX_SESSION)

    def test_generate_consultation_id(self):
        """generate_consultation_id uses correct prefix."""
        cid = generate_consultation_id()
        assert cid.startswith(f"{PREFIX_CONSULTATION}_")
        assert validate_id_format(cid, PREFIX_CONSULTATION)

    def test_generate_itinerary_id(self):
        """generate_itinerary_id uses correct prefix."""
        iid = generate_itinerary_id()
        assert iid.startswith(f"{PREFIX_ITINERARY}_")
        assert validate_id_format(iid, PREFIX_ITINERARY)

    def test_generate_booking_id(self):
        """generate_booking_id uses correct prefix."""
        bid = generate_booking_id()
        assert bid.startswith(f"{PREFIX_BOOKING}_")
        assert validate_id_format(bid, PREFIX_BOOKING)


class TestValidateIdFormat:
    """Tests for the validate_id_format function."""

    def test_validate_valid_ids(self):
        """validate_id_format accepts valid IDs."""
        # Generated IDs should all be valid
        assert validate_id_format(generate_session_id())
        assert validate_id_format(generate_consultation_id())
        assert validate_id_format(generate_itinerary_id())
        assert validate_id_format(generate_booking_id())

    def test_validate_with_expected_prefix(self):
        """validate_id_format checks prefix when specified."""
        sid = generate_session_id()
        assert validate_id_format(sid, PREFIX_SESSION) is True
        assert validate_id_format(sid, PREFIX_CONSULTATION) is False

    def test_validate_rejects_invalid_formats(self):
        """validate_id_format rejects invalid ID formats."""
        # No underscore
        assert validate_id_format("sessinvalid") is False

        # Empty string
        assert validate_id_format("") is False

        # None
        assert validate_id_format(None) is False  # type: ignore

        # Wrong length UUID part
        assert validate_id_format("sess_abc") is False
        assert validate_id_format("sess_" + "a" * 31) is False  # 31 chars
        assert validate_id_format("sess_" + "a" * 33) is False  # 33 chars

        # Invalid hex characters
        assert validate_id_format("sess_" + "g" * 32) is False

        # Unknown prefix (when no expected prefix specified)
        assert validate_id_format("unknown_" + "a" * 32) is False

    def test_validate_accepts_all_known_prefixes(self):
        """validate_id_format accepts all standard prefixes."""
        valid_hex = "a" * 32

        assert validate_id_format(f"sess_{valid_hex}")
        assert validate_id_format(f"cons_{valid_hex}")
        assert validate_id_format(f"itn_{valid_hex}")
        assert validate_id_format(f"book_{valid_hex}")


class TestExtractPrefix:
    """Tests for the extract_prefix function."""

    def test_extract_prefix_valid(self):
        """extract_prefix returns the prefix from valid IDs."""
        assert extract_prefix(generate_session_id()) == "sess"
        assert extract_prefix(generate_consultation_id()) == "cons"
        assert extract_prefix(generate_itinerary_id()) == "itn"
        assert extract_prefix(generate_booking_id()) == "book"
        assert extract_prefix("custom_abc123") == "custom"

    def test_extract_prefix_invalid(self):
        """extract_prefix returns None for invalid formats."""
        assert extract_prefix("") is None
        assert extract_prefix(None) is None  # type: ignore
        assert extract_prefix("nounderscore") is None


class TestIdNonGuessability:
    """Tests ensuring IDs are non-guessable (high entropy)."""

    def test_ids_have_sufficient_entropy(self):
        """IDs have 128 bits of entropy (UUID v4)."""
        # UUID v4 has 122 bits of randomness (6 bits are version/variant)
        # The hex representation should be 32 characters
        for generator in [
            generate_session_id,
            generate_consultation_id,
            generate_itinerary_id,
            generate_booking_id,
        ]:
            id_value = generator()
            _, uuid_part = id_value.split("_", 1)
            # 32 hex chars = 128 bits
            assert len(uuid_part) == 32

    def test_sequential_ids_not_predictable(self):
        """Sequential ID generation doesn't produce predictable patterns."""
        ids = [generate_consultation_id() for _ in range(100)]

        # Check that consecutive IDs don't have predictable relationships
        for i in range(len(ids) - 1):
            # Extract UUID parts
            uuid1 = ids[i].split("_")[1]
            uuid2 = ids[i + 1].split("_")[1]

            # Convert to integers for comparison
            val1 = int(uuid1, 16)
            val2 = int(uuid2, 16)

            # They should not be sequential
            assert abs(val2 - val1) > 1, "IDs appear to be sequential"

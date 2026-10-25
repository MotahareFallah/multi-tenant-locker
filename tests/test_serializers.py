import pytest

from accounts.serializers import OTPRequestSerializer, OTPVerifySerializer


def digits(text, base):
    return "".join(chr(base + int(d)) for d in text)


def persian(text):
    return digits(text, 0x06F0)


def arabic_indic(text):
    return digits(text, 0x0660)


@pytest.mark.parametrize(
    "raw",
    [
        "09123456789",
        "+98 912 345 6789",
        "+989123456789",
        persian("09123456789"),
        arabic_indic("09123456789"),
    ],
    ids=["national", "spaced", "e164", "persian-digits", "arabic-indic-digits"],
)
def test_phone_number_is_normalized_to_e164(raw):
    serializer = OTPRequestSerializer(data={"phone_number": raw})
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {"phone_number": "+989123456789"}


@pytest.mark.parametrize(
    "raw",
    ["", "abc", "12345", "02188776655", "1" * 100, 9123456789, None, True, ["0912"]],
    ids=[
        "empty",
        "letters",
        "too-short",
        "landline",
        "too-long",
        "integer",
        "null",
        "boolean",
        "list",
    ],
)
def test_invalid_phone_numbers_are_rejected(raw):
    serializer = OTPRequestSerializer(data={"phone_number": raw})
    assert not serializer.is_valid()
    assert "phone_number" in serializer.errors


@pytest.mark.parametrize(
    "raw",
    ["111111", " 111111 ", persian("111111"), arabic_indic("111111")],
    ids=["ascii", "trimmed", "persian-digits", "arabic-indic-digits"],
)
def test_code_is_normalized_to_ascii_digits(raw):
    serializer = OTPVerifySerializer(
        data={"phone_number": "09123456789", "code": raw}
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["code"] == "111111"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "11111",
        "12345678901",
        "abcdef",
        "1111 11",
        "\uff11" * 6,
        "1" * 100,
        111111,
        None,
        True,
    ],
    ids=[
        "empty",
        "too-short",
        "too-long",
        "letters",
        "inner-space",
        "fullwidth-digits",
        "huge",
        "integer",
        "null",
        "boolean",
    ],
)
def test_invalid_codes_are_rejected(raw):
    serializer = OTPVerifySerializer(
        data={"phone_number": "09123456789", "code": raw}
    )
    assert not serializer.is_valid()
    assert "code" in serializer.errors


def test_verify_serializer_returns_normalized_values():
    serializer = OTPVerifySerializer(
        data={"phone_number": "0912 345 6789", "code": persian("123456")}
    )
    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data == {
        "phone_number": "+989123456789",
        "code": "123456",
    }


def test_verify_serializer_requires_both_fields():
    serializer = OTPVerifySerializer(data={})
    assert not serializer.is_valid()
    assert set(serializer.errors) == {"phone_number", "code"}


def test_request_serializer_requires_a_phone_number():
    serializer = OTPRequestSerializer(data={})
    assert not serializer.is_valid()
    assert set(serializer.errors) == {"phone_number"}

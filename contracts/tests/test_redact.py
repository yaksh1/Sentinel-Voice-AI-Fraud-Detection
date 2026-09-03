"""PAN redaction (PLAN 2.6, and the test PLAN 5.2 turns into a CI gate).

The fixtures are fake but Luhn-valid, which is the point: a redactor that only
catches the literal string "4111111111111111" proves nothing.
"""

import pytest

from sentinel_contracts.redact import PLACEHOLDER, luhn_ok, redact_pan

# Luhn-valid test numbers from the public test-card ranges. Never real.
VISA = "4111111111111111"
MASTERCARD = "5500005555555559"
AMEX = "378282246310005"  # 15 digits


@pytest.mark.parametrize("number", [VISA, MASTERCARD, AMEX])
def test_luhn_accepts_valid_numbers(number):
    assert luhn_ok(number)


@pytest.mark.parametrize(
    "number",
    [
        "4111111111111112",  # last digit wrong
        "411111111111",  # 12 digits, too short
        "41111111111111111111",  # 20 digits, too long
        "4111-1111-1111-1111",  # separators must be stripped first
        "",
    ],
)
def test_luhn_rejects(number):
    assert not luhn_ok(number)


@pytest.mark.parametrize(
    "text",
    [
        f"my card is {VISA}",
        f"it's {MASTERCARD} expiring soon",
        f"the amex is {AMEX}",
        "4111 1111 1111 1111 is the number",
        "4111-1111-1111-1111 is the number",
    ],
)
def test_written_pans_are_redacted(text):
    out = redact_pan(text)
    assert PLACEHOLDER in out
    assert "4111" not in out or "1111" not in out.replace(PLACEHOLDER, "")


def test_spoken_pan_is_redacted():
    spoken = "four one one one one one one one one one one one one one one one"
    assert redact_pan(f"it is {spoken}") == f"it is {PLACEHOLDER}"


def test_spoken_pan_with_commas_is_redacted():
    spoken = "four, one, one, one, one, one, one, one, one, one, one, one, one, one, one, one"
    assert PLACEHOLDER in redact_pan(spoken)


@pytest.mark.parametrize(
    "text",
    [
        "the charge was nine hundred and forty dollars",
        "my last four are 4242",
        "order number 12345678",
        "call me on 555 0100",
        "the transaction id is 00000000-0000-0000-0000-000000000003",
        "4111111111111112 is not a card number",  # fails Luhn
        "0000000000000000 satisfies Luhn but is not a card",
        "ids 00000000-0000-0000-0000-000000000001 and 00000000-0000-0000-0000-000000000002",
    ],
)
def test_ordinary_text_is_left_alone(text):
    assert redact_pan(text) == text


def test_multiple_pans_in_one_line():
    out = redact_pan(f"first {VISA} then {MASTERCARD}")
    assert out.count(PLACEHOLDER) == 2
    assert VISA not in out and MASTERCARD not in out


def test_redaction_is_idempotent():
    once = redact_pan(f"card {VISA}")
    assert redact_pan(once) == once

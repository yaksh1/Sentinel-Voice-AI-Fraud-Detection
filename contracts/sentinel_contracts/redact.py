"""PAN redaction (PLAN 2.6).

Lives in `contracts` rather than in either service because both need it and a
security control with two implementations has none. `agent` redacts every log
line carrying caller speech; `core-api` redacts before a turn is persisted. The
schema names the columns `text_redacted` and `args_redacted` and deliberately
provides no unredacted counterpart to write to.

Regex finds candidates, Luhn decides. The Luhn step is what stops the redactor
eating order numbers, amounts and phone numbers, which in a bank transcript are
common and worth keeping.

Known gap, recorded rather than papered over: this only catches digits. Deepgram
is configured with `numerals=False`, so a caller reading a card number aloud can
come back as words — "four two four two" — which no digit regex will match.
`spell_out_digits` in `SPOKEN_DIGITS` covers the common word forms as a second
pass; anything stranger gets through. The real defence is that the agent never
asks for a full card number (BRIEF §4, and the system prompt).
"""

import re

PLACEHOLDER = "[REDACTED-PAN]"

# 13 to 19 digits, optionally single-spaced or dashed. The boundaries exclude
# `-` as well as digits so that a UUID — 00000000-0000-0000-0000-000000000003,
# which this repo's seed data is full of — cannot have a card-length run picked
# out of its middle. A genuinely dashed card number is still matched, because
# its own boundaries are whitespace rather than another dash.
_CANDIDATE = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")

SPOKEN_DIGITS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

# A run of at least 13 spoken digit words, which is what a card number read
# aloud looks like when the transcriber is not writing numerals.
_SPOKEN_RUN = re.compile(
    r"\b(?:(?:"
    + "|".join(SPOKEN_DIGITS)
    + r")[\s,-]+){12,18}(?:"
    + "|".join(SPOKEN_DIGITS)
    + r")\b",
    re.IGNORECASE,
)


def luhn_ok(digits: str) -> bool:
    """Whether a string of digits satisfies the Luhn checksum."""
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, char in enumerate(reversed(digits)):
        value = int(char)
        if i % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _is_pan(digits: str) -> bool:
    """Luhn, plus a guard against degenerate runs.

    `0000000000000000` satisfies Luhn — the checksum of nothing is zero — and no
    issuer has ever put it on a card. Without this, every all-zero identifier in
    the system reads as a card number.
    """
    return luhn_ok(digits) and len(set(digits)) > 1


def redact_pan(text: str) -> str:
    """Replace every Luhn-valid card number in `text`, written or spoken."""

    def _written(match: re.Match[str]) -> str:
        digits = re.sub(r"[ -]", "", match.group())
        return PLACEHOLDER if _is_pan(digits) else match.group()

    def _spoken(match: re.Match[str]) -> str:
        words = re.split(r"[\s,-]+", match.group().strip())
        digits = "".join(
            SPOKEN_DIGITS[w.casefold()] for w in words if w.casefold() in SPOKEN_DIGITS
        )
        return PLACEHOLDER if _is_pan(digits) else match.group()

    return _SPOKEN_RUN.sub(_spoken, _CANDIDATE.sub(_written, text))

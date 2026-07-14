"""Deterministic Vietnamese input transforms.

Every transform is meaning-preserving by construction: it changes how a question
is typed, not what it asks. That is what lets the metamorphic runner assert
"the classification must not change".

All randomness is drawn from a caller-supplied seeded Random, so a run with the
same seed produces byte-identical variants.
"""

from __future__ import annotations

import random
import unicodedata
from collections.abc import Callable

Transform = Callable[[str, random.Random], str]

# Common real-world Vietnamese typing slips, not random character noise.
TYPO_MAP = {
    "không": "khong",
    "được": "duoc",
    "nhưng": "nhung",
    "tôi": "toi",
    "phải": "phai",
    "giấy": "giay",
    "tiền": "tien",
    "cọc": "coc",
    "nhà": "nha",
    "làm": "lam",
    "kinh doanh": "kinh doanh",
}
TELEX_FRAGMENTS = {
    "ê": "ee",
    "ô": "oo",
    "ơ": "ow",
    "ư": "uw",
    "đ": "dd",
    "ă": "aw",
    "â": "aa",
}
POLITE_PREFIXES = (
    "Xin hỏi, ",
    "Cho em hỏi ",
    "Dạ cho hỏi ",
    "Chào anh/chị, ",
    "Mình muốn hỏi là ",
)
POLITE_SUFFIXES = (
    " ạ?",
    " ạ, cảm ơn.",
    ", em cảm ơn ạ.",
    " nhé?",
)
FILLERS = ("thật ra là", "kiểu như", "nói chung là", "đại khái là")


def remove_accents(text: str, _rng: random.Random) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "D")


def lowercase(text: str, _rng: random.Random) -> str:
    return text.lower()


def uppercase(text: str, _rng: random.Random) -> str:
    return text.upper()


def strip_punctuation(text: str, _rng: random.Random) -> str:
    return "".join(ch for ch in text if ch not in ".,?!;:")


def messy_punctuation(text: str, rng: random.Random) -> str:
    base = text.rstrip(" .?!")
    return base + rng.choice(("???", "!!!", " ...", " ?!"))


def extra_whitespace(text: str, rng: random.Random) -> str:
    words = text.split()
    return "  ".join(words) + " " * rng.randint(1, 4)


def common_typos(text: str, _rng: random.Random) -> str:
    out = text
    for correct, typo in TYPO_MAP.items():
        out = out.replace(correct, typo)
    return out


def telex_fragment(text: str, _rng: random.Random) -> str:
    out = text
    for char, telex in TELEX_FRAGMENTS.items():
        out = out.replace(char, telex)
    return out


def polite_wrap(text: str, rng: random.Random) -> str:
    body = text[0].lower() + text[1:] if text else text
    return rng.choice(POLITE_PREFIXES) + body.rstrip("?. ") + rng.choice(POLITE_SUFFIXES)


def add_filler(text: str, rng: random.Random) -> str:
    words = text.split()
    if len(words) < 3:
        return text
    position = rng.randint(1, len(words) - 1)
    words.insert(position, rng.choice(FILLERS))
    return " ".join(words)


def unicode_nfd(text: str, _rng: random.Random) -> str:
    """Same characters, decomposed form. A backend must normalise this."""
    return unicodedata.normalize("NFD", text)


def d_confusion(text: str, _rng: random.Random) -> str:
    return text.replace("đ", "d").replace("Đ", "D")


def duplicate_spaces_and_lowercase(text: str, rng: random.Random) -> str:
    return extra_whitespace(lowercase(text, rng), rng)


NOISE_TRANSFORMS: dict[str, Transform] = {
    "remove_accents": remove_accents,
    "lowercase": lowercase,
    "uppercase": uppercase,
    "strip_punctuation": strip_punctuation,
    "messy_punctuation": messy_punctuation,
    "extra_whitespace": extra_whitespace,
    "common_typos": common_typos,
    "telex_fragment": telex_fragment,
    "polite_wrap": polite_wrap,
    "add_filler": add_filler,
    "unicode_nfd": unicode_nfd,
    "d_confusion": d_confusion,
    "lowercase_no_accent": lambda t, r: remove_accents(lowercase(t, r), r),
    "noisy_lowercase": duplicate_spaces_and_lowercase,
}

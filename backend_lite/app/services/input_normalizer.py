from __future__ import annotations

import re
import unicodedata


class InputNormalizer:
    def normalize(self, value: str) -> tuple[str, str]:
        lowered = value.lower().strip()
        normalized = re.sub(r"[^\w\sÀ-ỹđĐ]", " ", lowered, flags=re.UNICODE)
        normalized = " ".join(normalized.split())
        decomposed = unicodedata.normalize("NFD", normalized)
        accentless = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
        accentless = accentless.replace("đ", "d")
        return normalized, " ".join(accentless.split())

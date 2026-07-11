from __future__ import annotations


class LiteLanguageDetector:
    _english_terms = {
        "what", "which", "where", "when", "documents", "document", "need", "start",
        "open", "business", "food", "legal", "advice", "write", "poem", "please",
        "how", "can", "should", "vietnam", "english", "license",
    }
    _vietnamese_ascii_terms = {
        "toi", "ban", "can", "gi", "lam", "sao", "de", "thue", "nha", "chu", "giu",
        "tien", "coc", "khong", "tra", "muon", "ban", "do", "an", "online", "que",
        "giay", "to", "phat", "giao", "thong", "bien", "dang", "ky", "kinh", "doanh",
        "vay", "no", "hop", "dong", "cong", "an", "luat", "su", "vu", "viec",
    }

    def detect(self, normalized: str, accentless: str, requested_language: str) -> str:
        if requested_language.lower() != "vi":
            return "unsupported"
        if any(ch in normalized for ch in "àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"):
            return "vi"
        terms = set(accentless.split())
        vietnamese_score = len(terms & self._vietnamese_ascii_terms)
        english_score = len(terms & self._english_terms)
        if english_score >= 4 and english_score > vietnamese_score * 2:
            return "unsupported"
        if vietnamese_score >= 2:
            return "vi"
        if english_score >= 3:
            return "unsupported"
        return "vi"

from __future__ import annotations


class ChatTitleService:
    _titles = {
        "rental_deposit": "Tranh chấp tiền cọc thuê nhà",
        "loan_dispute": "Vay tiền chưa được hoàn trả",
        "consumer_purchase": "Mua hàng chưa được giao",
        "traffic_fine": "Biên bản giao thông",
        "traffic_documents": "Giấy tờ xử lý giao thông",
        "food_business": "Bán đồ ăn online",
        "business_registration": "Đăng ký hộ kinh doanh",
    }

    def make(self, question: str, topic: str | None = None) -> str:
        if topic in self._titles:
            return self._titles[topic]
        compact = " ".join(question.split())
        return compact[:72] + ("..." if len(compact) > 72 else "")

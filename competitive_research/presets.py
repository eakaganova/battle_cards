from __future__ import annotations

from typing import Dict, List


PRESET_RESEARCHES: Dict[str, Dict[str, object]] = {
    "КНЗ: кредит под залог недвижимости": {
        "research_type": "КНЗ",
        "competitors": [
            {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/credit_zalog"},
            {"name": "ВТБ", "url": "https://www.vtb.ru/personal/ipoteka/ipoteka-pod-zalog-nedvizhimosti/"},
            {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/alternativa"},
            {"name": "МТС Банк", "url": "https://www.mtsbank.ru/chastnim-licam/ipoteka/kredit-pod-zalog/"},
            {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/bail/pod-zalog/"},
            {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/pod-zalog/"},
        ],
        "groups": {
            "Источник": [
                "URL источника",
                "Статус парсинга",
            ],
            "Ключевые условия": [
                "Процентная ставка",
                "ПСК",
                "Максимальная сумма кредита",
                "Минимальная сумма кредита",
                "Срок",
                "LTV / доля от стоимости недвижимости",
            ],
            "Залог и требования": [
                "Обеспечение / объект залога",
                "Требования к заёмщику",
                "Требования к недвижимости",
                "Подтверждение дохода",
                "Страхование",
            ],
            "Оформление": [
                "Способ получения денег",
                "Досрочное погашение",
                "Комиссии",
                "Документы",
                "Как оформить",
            ],
            "Риски и пробелы": [
                "Особые условия / ограничения",
                "Что не указано на странице",
            ],
        },
    },
    "КНА: кредит под залог автомобиля": {
        "research_type": "КНА",
        "competitors": [
            {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/cash-loan/auto/"},
            {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/pod-zalog-avto-"},
            {"name": "ВТБ", "url": "https://www.vtb.ru/personal/kredit/pod-zalog-avto/"},
        ],
        "groups": {
            "Источник": [
                "URL источника",
                "Статус парсинга",
            ],
            "Ключевые условия": [
                "Процентная ставка",
                "ПСК",
                "Максимальная сумма",
                "Минимальная сумма",
                "Срок",
                "LTV / доля от стоимости автомобиля",
            ],
            "Залог и требования": [
                "Требуется ли авто в залог",
                "Кто может пользоваться автомобилем",
                "Требования к автомобилю",
                "Требования к заёмщику",
                "Подтверждение дохода",
                "Страхование",
            ],
            "Оформление": [
                "Комиссии",
                "Документы",
                "Как оформить",
            ],
            "Риски и пробелы": [
                "Особые условия / ограничения",
                "Что не указано на странице",
            ],
        },
    },
    "Кредит наличными: банки": {
        "research_type": "Fintech",
        "competitors": [
            {"name": "Сбер", "url": "https://www.sberbank.ru"},
            {"name": "ВТБ", "url": "https://www.vtb.ru"},
        ],
        "groups": {
            "Источник": [
                "URL источника",
                "Статус парсинга",
            ],
            "Ключевые условия": [
                "Процентная ставка",
                "ПСК",
                "Сумма",
                "Срок",
            ],
            "Клиент и оформление": [
                "Требования к заёмщику",
                "Документы",
                "Страхование",
                "Комиссии",
                "Как оформить",
            ],
            "Риски и пробелы": [
                "Что не указано на странице",
            ],
        },
    },
}


def preset_names() -> List[str]:
    return list(PRESET_RESEARCHES.keys())


def preset_competitors(name: str) -> List[Dict[str, str]]:
    preset = PRESET_RESEARCHES[name]
    return [
        {
            "name": str(item.get("name", "")),
            "url": str(item.get("url", "")),
            "manual_text": "",
            "uploaded_text": "",
        }
        for item in preset.get("competitors", [])
    ]


def preset_groups(name: str) -> Dict[str, List[str]]:
    preset = PRESET_RESEARCHES[name]
    return {str(group): list(values) for group, values in dict(preset.get("groups", {})).items()}


def preset_research_type(name: str) -> str:
    return str(PRESET_RESEARCHES[name].get("research_type", "Custom"))

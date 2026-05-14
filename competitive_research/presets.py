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
            {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/bail/pod-zalog-kvartiry/"},
            {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/pod-zalog/"},
        ],
        "groups": {
            "Источник и доверие": [
                "URL источника",
                "Статус парсинга",
                "Дата актуальности условий",
                "Что не указано на странице",
            ],
            "Финансовые условия": [
                "Процентная ставка",
                "ПСК",
                "Максимальная сумма кредита",
                "Минимальная сумма кредита",
                "Срок кредита",
                "LTV / доля от стоимости недвижимости",
            ],
            "Залог и требования": [
                "Объект залога",
                "Требования к недвижимости",
                "Требования к заёмщику",
                "Подтверждение дохода",
                "Страхование",
            ],
            "Оформление и обслуживание": [
                "Способ подачи заявки",
                "Срок рассмотрения",
                "Способ получения денег",
                "Досрочное погашение",
                "Комиссии",
                "Документы",
            ],
        },
    },
    "КНА: кредит под залог автомобиля": {
        "research_type": "КНА",
        "competitors": [
            {"name": "ВТБ", "url": "https://www.vtb.ru/personal/kredit/pod-zalog-avto/"},
            {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/cash-loan/auto/"},
        ],
        "groups": {
            "Источник и доверие": [
                "URL источника",
                "Статус парсинга",
                "Дата актуальности условий",
                "Что не указано на странице",
            ],
            "Финансовые условия": [
                "Процентная ставка",
                "ПСК",
                "Максимальная сумма",
                "Минимальная сумма",
                "Срок кредита",
                "Размер ежемесячного платежа",
            ],
            "Автомобиль и залог": [
                "Требуется ли авто в залог",
                "Кто может пользоваться автомобилем",
                "Нужно ли передавать ПТС",
                "Требования к автомобилю",
                "Ограничения на автомобиль в залоге",
            ],
            "Клиент и оформление": [
                "Требования к заёмщику",
                "Подтверждение дохода",
                "Страхование / КАСКО",
                "Документы",
                "Срок решения",
                "Как оформить",
                "Комиссии",
            ],
        },
    },
    "Ипотека: покупка жилья": {
        "research_type": "Ипотека",
        "competitors": [
            {"name": "Т-Банк", "url": "https://www.tbank.ru/mortgage/"},
            {"name": "ВТБ", "url": "https://www.vtb.ru/personal/ipoteka/"},
            {"name": "Сбер / Домклик", "url": "https://domclick.ru/ipoteka"},
            {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/mortgage/"},
            {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/mortgage/"},
        ],
        "groups": {
            "Источник и доверие": [
                "URL источника",
                "Статус парсинга",
                "Дата актуальности условий",
                "Что не указано на странице",
            ],
            "Программы и ставки": [
                "Типы ипотечных программ",
                "Процентная ставка",
                "ПСК",
                "Максимальная сумма",
                "Минимальная сумма",
                "Срок кредитования",
                "Первоначальный взнос",
            ],
            "Объекты и заёмщик": [
                "Тип недвижимости",
                "Требования к объекту",
                "Требования к заёмщику",
                "Созаемщики",
                "Подтверждение дохода",
                "Страхование",
            ],
            "Сделка и UX": [
                "Онлайн-заявка",
                "Срок решения",
                "Электронная регистрация",
                "Безопасные расчёты",
                "Документы",
                "Комиссии",
                "Досрочное погашение",
            ],
        },
    },
    "ОСАГО: онлайн-оформление": {
        "research_type": "ОСАГО",
        "competitors": [
            {"name": "Т-Страхование", "url": "https://www.tbank.ru/insurance/osago/"},
            {"name": "СберСтрахование", "url": "https://sberbankins.ru/products/auto/osago/"},
            {"name": "АльфаСтрахование", "url": "https://www.alfastrah.ru/individuals/auto/osago/"},
            {"name": "Ингосстрах", "url": "https://www.ingos.ru/auto/osago/"},
            {"name": "РЕСО-Гарантия", "url": "https://www.reso.ru/Retail/AGO/OSAGO/"},
        ],
        "groups": {
            "Источник и доверие": [
                "URL источника",
                "Статус парсинга",
                "Дата актуальности условий",
                "Что не указано на странице",
            ],
            "Расчёт и оформление": [
                "Онлайн-калькулятор",
                "Необходимые данные для расчёта",
                "Необходимые документы",
                "Срок оформления",
                "Оплата онлайн",
                "Получение электронного полиса",
            ],
            "Условия полиса": [
                "Базовый тариф / факторы цены",
                "КБМ",
                "Ограниченный / неограниченный список водителей",
                "Территория использования",
                "Срок страхования",
                "Продление полиса",
            ],
            "Сервис и урегулирование": [
                "Проверка полиса",
                "Внесение изменений",
                "Расторжение",
                "Заявление о страховом случае",
                "Поддержка",
                "Мобильное приложение",
            ],
        },
    },
    "Накопительные счета": {
        "research_type": "Накопительные счета",
        "competitors": [
            {"name": "Т-Банк", "url": "https://www.tbank.ru/savings/saving-account/"},
            {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/contributions/accounts/sberaccount"},
            {"name": "ВТБ", "url": "https://www.vtb.ru/personal/vklady-i-scheta/nakopitelnyy-schet/"},
            {"name": "Альфа-Банк", "url": "https://alfabank.ru/make-money/savings-account/"},
            {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/increase/deposits-and-accounts/"},
        ],
        "groups": {
            "Источник и доверие": [
                "URL источника",
                "Статус парсинга",
                "Дата актуальности условий",
                "Что не указано на странице",
            ],
            "Доходность": [
                "Базовая ставка",
                "Максимальная ставка",
                "Условия повышенной ставки",
                "Промопериод",
                "Порядок начисления процентов",
                "Периодичность выплаты процентов",
            ],
            "Ограничения и операции": [
                "Минимальная сумма",
                "Максимальная сумма для повышенной ставки",
                "Пополнение",
                "Частичное снятие",
                "Потеря процентов при снятии",
                "Валюта счёта",
            ],
            "Оформление и клиентский путь": [
                "Кто может открыть",
                "Нужна ли карта банка",
                "Открытие онлайн",
                "Количество счетов",
                "Закрытие счёта",
                "Мобильное приложение",
                "Подписка / пакет услуг",
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
    return str(PRESET_RESEARCHES[name].get("research_type", "Свой список"))

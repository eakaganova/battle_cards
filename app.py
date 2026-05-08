import streamlit as st
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# =========================
# DATA
# =========================

PRODUCT_BANK_URLS = {
    "КНЗ: кредит под залог недвижимости": [
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/credit_zalog"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/ipoteka/ipoteka-pod-zalog-nedvizhimosti/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/alternativa"},
        {"name": "МТС Банк", "url": "https://www.mtsbank.ru/chastnim-licam/ipoteka/kredit-pod-zalog/"},
        {"name": "Газпромбанк", "url": "https://www.gazprombank.ru/personal/bail/pod-zalog/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/pod-zalog/"},
    ],

    "КНА: кредит под залог автомобиля": [
        {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/cash-loan/auto/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/credits/cash/pod-zalog-avto-"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/kredit/pod-zalog-avto/"},
    ],

    "Автокредит": [
        {"name": "ПСБ", "url": "https://www.psbank.ru/new-subjects/auto-start"},
        {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/auto-loan/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/apply/auto/onlajn-zayavka-na-avtokredit/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/autocredit/"},
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/avtokredit_ab"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/avtokredity/moskva/"},
    ],

    "Кредит наличными": [
        {"name": "Уралсиб", "url": "https://uralsib.ru/kredity/kredit-na-lyubye-tseli"},
        {"name": "ЛокоБанк", "url": "https://www.lockobank.ru/personal/kredit/nalichnymi/"},
        {"name": "Сбер", "url": "https://www.sberbank.ru/ru/person/credits/money/consumer_unsecured"},
        {"name": "Т-Банк", "url": "https://www.tbank.ru/loans/cash-loan/"},
        {"name": "Совкомбанк", "url": "https://sovcombank.ru/apply/credit/city-moskva/"},
        {"name": "Альфа-Банк", "url": "https://alfabank.ru/get-money/credit/credit-cash/"},
        {"name": "ОТП Банк", "url": "https://www.otpbank.ru/retail/credits/cash/moscow/"},
        {"name": "ВТБ", "url": "https://www.vtb.ru/personal/kredit/moskva/"},
    ],
}

# =========================
# UI
# =========================

st.set_page_config(page_title="Battle Cards")

st.title("Баттл-карты (LLM + парсинг)")

api_key = st.text_input("API Key", type="password")
folder_id = st.text_input("Folder ID")

battle_card_type = st.selectbox(
    "Тип баттл-карты",
    list(PRODUCT_BANK_URLS.keys())
)

banks = PRODUCT_BANK_URLS[battle_card_type]

selected = st.multiselect(
    "Банки",
    [b["name"] for b in banks],
    default=[b["name"] for b in banks]
)

model = f"gpt://{folder_id}/gpt-oss-120b/latest" if folder_id else None


# =========================
# CLIENT
# =========================

def get_client():
    return OpenAI(
        api_key=api_key,
        base_url="https://ai.api.cloud.yandex.net/v1",
        project=folder_id
    )


# =========================
# SCRAPER
# =========================

def scrape(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=25)
    r.encoding = r.apparent_encoding

    soup = BeautifulSoup(r.text, "html.parser")
    return soup.get_text(" ", strip=True)[:6000]


# =========================
# SAFE RESPONSE
# =========================

def extract(resp):
    try:
        return resp.output[0].content[0].text
    except:
        try:
            return resp.output_text
        except:
            return str(resp.output)


# =========================
# PROMPTS (ТВОИ, БЕЗ УПРОЩЕНИЯ)
# =========================

def get_structure(battle_card_type: str) -> str:

    if battle_card_type == "КНА: кредит под залог автомобиля":
        return """
## Основные параметры кредита
| Параметр | Содержание |
|---|---|
| Название банка | |
| URL источника | |
| Название продукта | |
| Тип кредита | |
| Процентная ставка | |
| Полная стоимость кредита / ПСК | |
| Максимальная сумма кредита | |
| Минимальная сумма кредита | |
| Максимальный срок кредитования | |
| Минимальный срок кредитования | |
| Валюта кредита | |
| График платежей | |
| Целевое / нецелевое использование средств | |

## Залоговое обеспечение
| Параметр | Содержание |
|---|---|
| Требуется ли залог автомобиля | |
| Какие транспортные средства принимаются в залог | |
| Легковые автомобили | |
| Коммерческий транспорт | |
| Мототехника | |
| Иностранные / отечественные автомобили | |
| Максимальный возраст автомобиля | |
| Требования к техническому состоянию | |
| Требования к регистрации автомобиля | |
| Требования к собственнику автомобиля | |
| Возможность залога автомобиля третьего лица | |
| Максимальный процент от оценочной стоимости / LTV | |
| Необходимость оценки автомобиля | |
| Способ оценки автомобиля | |
| Ограничения на использование автомобиля во время кредита | |

## ПТС / ЭПТС и обременение
| Параметр | Содержание |
|---|---|
| Требуется ли передача ПТС | |
| Работа с электронным ПТС / ЭПТС | |
| Накладывается ли обременение / запрет регистрационных действий | |
| Возможность пользоваться автомобилем во время кредита | |
| Возможность продажи автомобиля до погашения кредита | |
| Условия снятия обременения после погашения | |

## Требования к заемщику
| Параметр | Содержание |
|---|---|
| Возрастные ограничения | |
| Гражданство / резидентство | |
| Регистрация | |
| Требования к доходу | |
| Условия трудоустройства | |
| Минимальный стаж работы | |
| Требования к кредитной истории | |
| Возможность привлечения созаемщиков | |
| Требования к собственнику залога, если он не заемщик | |

## Оформление и получение денег
| Параметр | Содержание |
|---|---|
| Способы подачи заявки | |
| Возможность онлайн-заявки | |
| Возможность заполнения через Госуслуги | |
| Срок рассмотрения заявки | |
| Необходимые документы заемщика | |
| Документы на автомобиль | |
| Требуется ли подтверждение дохода | |
| Требуется ли осмотр автомобиля | |
| Требуется ли фотографирование автомобиля | |
| Необходимость визита в офис | |
| Возможность встречи с представителем | |
| Способы получения средств | |
| Скорость получения денег после одобрения | |

## Страхование и дополнительные услуги
| Параметр | Содержание |
|---|---|
| Требуется ли каско | |
| Влияние каско на ставку | |
| ОСАГО | |
| Страхование жизни и здоровья | |
| Финансовая защита | |
| Дополнительные услуги и пакеты | |
| Возможность отказаться от дополнительных услуг | |

## Комиссии, расходы и санкции
| Параметр | Содержание |
|---|---|
| Комиссия за выдачу кредита | |
| Комиссия за оценку автомобиля | |
| Комиссия за перевод / снятие денег | |
| Обслуживание счета | |
| Досрочное погашение | |
| Частичное досрочное погашение | |
| Штрафы / пени за просрочку | |
| Иные комиссии и расходы | |

## Гибкость и специальные условия
| Параметр | Содержание |
|---|---|
| Условия для зарплатных клиентов | |
| Условия для действующих клиентов | |
| Программы лояльности | |
| Персональные предложения | |
| Возможность рефинансирования | |
| Акции и временные предложения | |
"""
    return "### структура не задана"


# =========================
# LLM
# =========================

def analyze(text, bank_name, url):

    structure = get_structure(battle_card_type)

    prompt = f"""
Тип баттл-карты: {battle_card_type}
Цель: составить максимально полную таблицу условий продукта для банка {bank_name}.

Источник: {url}

Работай только на основании предоставленного текста.
Не делай предположений.
Если информации нет — пиши: Не указано.
Если есть противоречие — укажи оба значения.

Верни строго Markdown.

СТРУКТУРА:
{structure}

ТЕКСТ:
{text}
"""

    client = get_client()

    resp = client.responses.create(
        model=model,
        input=prompt,
        temperature=0.2,
        max_output_tokens=1200
    )

    return extract(resp)


# =========================
# RUN
# =========================

if st.button("Запуск"):

    results = []

    for bank in banks:
        if bank["name"] not in selected:
            continue

        st.write(f"Парсинг: {bank['name']}")

        text = scrape(bank["url"])

        st.write(text[:200])

        st.write("LLM...")

        table = analyze(text, bank["name"], bank["url"])

        results.append((bank["name"], table))

    st.subheader("Результаты")

    for name, table in results:
        st.markdown(f"## {name}")
        st.markdown(table)

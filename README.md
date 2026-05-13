# Competitive AI Research Platform

Production-oriented Streamlit workspace for competitive analysis with parsing, evidence-first LLM extraction, review, versioning and exports.

## Run

```powershell
pip install -r requirements.txt
python -m playwright install chromium
streamlit run app.py
```

LLM configuration is optional. Without keys the app runs in heuristic fallback mode and marks uncertainty explicitly.

```powershell
$env:OPENAI_API_KEY="..."
$env:OPENAI_MODEL="gpt-4.1-mini"
```

or

```powershell
$env:YANDEX_API_KEY="..."
$env:YANDEX_FOLDER="..."
$env:YANDEX_MODEL="gpt-oss-120b/latest"
$env:LLM_PROVIDER="yandex"
```

For Yandex, keep `YANDEX_MODEL` as a short model path such as `gpt-oss-120b/latest` or `yandexgpt/latest`.
The app builds the full model URI internally as `gpt://<YANDEX_FOLDER>/<YANDEX_MODEL>`.

## Architecture

- `competitive_research/parser.py` handles Playwright/BeautifulSoup extraction, dynamic content, accordions, hidden text, FAQ, tables, document links and manual fallback.
- `competitive_research/pipeline.py` orchestrates the 14-stage pipeline with statuses, logs and graceful degradation.
- `competitive_research/models.py` defines typed JSON-first entities, including every battle-card cell evidence payload.
- `competitive_research/presets.py` keeps the ready banking presets: КНЗ, КНА, cash loan banks, their URLs and comparison schemas.
- `competitive_research/llm.py` isolates provider access and includes an offline fallback.
- `competitive_research/normalization.py` separates raw extraction, semantic normalization and canonical schema alignment.
- `competitive_research/storage.py` saves versioned research runs and computes diffs.
- `competitive_research/exporters.py` exports CSV, Excel, Markdown, DOCX, PDF and Google Sheets CSV payloads.
- `app.py` is the Streamlit enterprise workspace UI.

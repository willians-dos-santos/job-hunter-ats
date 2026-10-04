# Job Hunter ATS Crawler Core

Crawler assíncrono para recolha automatizada de vagas nas APIs públicas de ATS (Greenhouse e Lever), com filtros determinísticos, persistência SQLite para deduplicação e idempotência, e notificações estruturadas via Telegram Bot ou Consola.

Desenvolvido estritamente sob os princípios de **SDD (Spec-Driven Development)** e **TDD (Test-Driven Development)** definidos na constituição do projeto.

---

## 🏗 Arquitetura

```
job-hunter-ats/
├── pyproject.toml         # Configuração uv e dependências
├── config.yaml            # Configuração de alvos, filtros e canais
├── .env.example           # Modelo de variáveis de ambiente
├── src/
│   ├── models.py          # Modelos Pydantic v2 (JobOpening, TargetCompany)
│   ├── storage.py         # Repositório SQLite para deduplicação e idempotência
│   ├── filters.py         # Filtro determinístico por palavras-chave de título e local
│   ├── notifiers.py       # Despachador de alertas (Telegram Bot / Consola)
│   ├── main.py            # Orquestrador assíncrono com semáforo de concorrência
│   └── collectors/        # Adaptadores assíncronos de ATS
│       ├── base.py        # Coletor abstrato base com backoff exponencial para HTTP 429
│       ├── greenhouse.py  # Adaptador para a API pública Greenhouse
│       └── lever.py       # Adaptador para a API pública Lever
└── tests/                 # Suite de testes com fixtures JSON realistas
    ├── fixtures/          # Payloads mockados de Greenhouse e Lever
    ├── test_models.py
    ├── test_greenhouse_collector.py
    ├── test_lever_collector.py
    ├── test_storage.py
    ├── test_filters.py
    ├── test_notifiers.py
    └── test_orchestrator.py
```

---

## 🚀 Como Executar

### 1. Instalar dependências com uv
```bash
uv sync --extra dev
```

### 2. Executar os Testes Unitários
```bash
uv run pytest
```

### 3. Configurar Alvos e Variáveis de Ambiente
Copie o ficheiro `.env.example` para `.env` se pretender alertas no Telegram:
```bash
TELEGRAM_BOT_TOKEN="o_seu_token"
TELEGRAM_CHAT_ID="o_seu_chat_id"
```
Ajuste os alvos e filtros pretendidos em `config.yaml`.

### 4. Executar o Crawler
```bash
uv run python -m src.main
```
Ou com opções:
```bash
uv run python -m src.main --config config.yaml --verbose
```

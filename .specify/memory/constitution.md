# Job Hunter ATS Constitution

## Core Principles

### I. Async & Non-Blocking First
Todas as operações de recolha em endpoints externos (Greenhouse, Lever, Gupy, Solides, etc.) devem ser estritamente assíncronas utilizando `httpx.AsyncClient`. O bloqueio do ciclo de eventos (event loop) por chamadas síncronas de rede ou E/S é inaceitável.

### II. Strict Typing & Data Contracts
Nenhum dado trafega na aplicação sob a forma de dicionários não tipados (`dict`). Toda a entrada, normalização e saída deve ser validada e governada através de modelos de dados do **Pydantic v2**, garantindo validação de esquema em tempo de execução. Todos os modelos e mapeamentos de persistência devem obrigatoriamente espelhar os contratos formalizados no documento [`specs/database-schema.md`](specs/database-schema.md).

### III. Test-First & Mock-Driven (NON-NEGOTIABLE)
Abordagem TDD mandatória para todos os coletores e parsers. Nenhuma lógica de extração deve ser redigida antes da definição de testes unitários com fixtures JSON mockadas que simulem as respostas reais das APIs de ATS. O ciclo Red-Green-Refactor deve ser cumprido.

### IV. Idempotency & Fault Isolation
Cada oportunidade descoberta é identificada por um ID canónico único (`source_job_id` / `id`) e governada pela chave semântica `dedup_key` conforme as regras definidas em [`specs/database-schema.md`](specs/database-schema.md). Notificações duplicadas são inadmissíveis. Falhas temporárias de rede, respostas 404 ou limitações de taxa (HTTP 429) relativas a uma organização nunca devem interromper o rastreio das demais.

### V. Clean Architecture & Repository Separation
A camada de persistência e deduplicação (`storage`) deve permanecer isolada da camada de recolha (`collectors`) e de despacho de alertas (`notifiers`). Cada módulo tem responsabilidade única e deve ser testável de forma independente, aderindo estritamente às tabelas e restrições descritas em [`specs/database-schema.md`](specs/database-schema.md).

## Additional Constraints & Security Standards

- **Runtime & Gestão de Dependências:** Python 3.11+ gerido exclusivamente com `uv`.
- **Esquema de Dados Canónico:** Qualquer alteração na estrutura das tabelas `public.jobs`, `public.search_configs` ou do fallback SQLite (`seen_jobs`) exige revisão prévia e sincronização no ficheiro [`specs/database-schema.md`](specs/database-schema.md).
- **Gestão de Segredos:** Tokens de bots (Telegram, Discord, etc.) e credenciais não devem ser guardados em código ou ficheiros de configuração expostos; leitura obrigatória a partir de variáveis de ambiente (`.env`).
- **Respeito de Taxa (Rate Limits):** Implementação obrigatória de controle de concorrência com recurso de semáforos (`asyncio.Semaphore`) para evitar bloqueios de IP nos serviços de ATS.

## Development Workflow & Quality Gates

- **Validação de Especificação & Esquema:** Nenhuma funcionalidade deve ser codificada sem um documento correspondente na pasta `specs/` e sem a conformidade estrita com o [`specs/database-schema.md`](specs/database-schema.md).
- **Portões de Qualidade (Quality Gates):** Todos os testes com `pytest` devem passar a verde antes da unificação de código. Cobertura estrita da normalização de esquemas com validações de campos ausentes ou nulos.

## Governance

A presente constituição sobrepõe-se a qualquer decisão discricionária de agentes de codificação ou convenções improvisadas. Quaisquer alterações a estes princípios exigem atualização formal deste documento, justificação arquitetural e adaptação correspondente dos testes unitários existentes.

**Version**: 1.1.0 | **Ratified**: 2026-10-04 | **Last Amended**: 2026-10-13
# Job Hunter ATS Constitution

## Core Principles

### I. Async & Non-Blocking First
Todas as operações de recolha em endpoints externos (Greenhouse, Lever, etc.) devem ser estritamente assíncronas utilizando `httpx.AsyncClient`. O bloqueio do ciclo de eventos (event loop) por chamadas síncronas de rede ou E/S é inaceitável.

### II. Strict Typing & Data Contracts
Nenhum dado trafega na aplicação sob a forma de dicionários não tipados (`dict`). Toda a entrada, normalização e saída deve ser validada e governada através de modelos de dados do **Pydantic v2**, garantindo validação de esquema em tempo de execução.

### III. Test-First & Mock-Driven (NON-NEGOTIABLE)
Abordagem TDD mandatória para todos os coletores e parsers. Nenhuma lógica de extração deve ser redigida antes da definição de testes unitários com fixtures JSON mockadas que simulem as respostas reais das APIs de ATS. O ciclo Red-Green-Refactor deve ser cumprido.

### IV. Idempotency & Fault Isolation
Cada oportunidade descoberta é identificada por um ID canónico único (`source_job_id`). Notificações duplicadas são inadmissíveis. Falhas temporárias de rede, respostas 404 ou limitações de taxa (HTTP 429) relativas a uma organização nunca devem interromper o rastreio das demais.

### V. Clean Architecture & Repository Separation
A camada de persistência e deduplicação (`storage`) deve permanecer isolada da camada de recolha (`collectors`) e de despacho de alertas (`notifiers`). Cada módulo tem responsabilidade única e deve ser testável de forma independente.

## Additional Constraints & Security Standards

- **Runtime & Gestão de Dependências:** Python 3.11+ gerido exclusivamente com `uv`.
- **Gestão de Segredos:** Tokens de bots (Telegram, Discord, etc.) e credenciais não devem ser guardados em código ou ficheiros de configuração expostos; leitura obrigatória a partir de variáveis de ambiente (`.env`).
- **Respeito de Taxa (Rate Limits):** Implementação obrigatória de controle de concorrência com recurso de semáforos (`asyncio.Semaphore`) para evitar bloqueios de IP nos serviços de ATS.

## Development Workflow & Quality Gates

- **Validação de Especificação:** Nenhuma funcionalidade deve ser codificada sem um documento correspondente na pasta `specs/`.
- **Portões de Qualidade (Quality Gates):** Todos os testes com `pytest` devem passar a verde antes da unificação de código. Cobertura estrita da normalização de esquemas com validações de campos ausentes ou nulos.

## Governance

A presente constituição sobrepõe-se a qualquer decisão discricionária de agentes de codificação ou convenções improvisadas. Quaisquer alterações a estes princípios exigem atualização formal deste documento, justificação arquitetural e adaptação correspondente dos testes unitários existentes.

**Version**: 1.0.0 | **Ratified**: 2026-10-04 | **Last Amended**: 2026-10-04
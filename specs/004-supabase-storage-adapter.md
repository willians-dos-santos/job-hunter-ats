# Feature Specification: Supabase Storage Adapter

**Feature Branch**: `004-supabase-storage-adapter`

**Created**: 2026-10-05

**Status**: Draft

**Input**: User description: "Substituir a persistência SQLite local por Supabase PostgreSQL via API REST oficial assíncrona, viabilizando a execução efêmera em ambientes remotos sem perda de deduplicação"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deduplicação e Persistência de Vagas no Supabase (Priority: P1)

Como operador do crawler de vagas, pretendo que as oportunidades encontradas sejam verificadas e guardadas numa base de dados na nuvem (Supabase) através da API REST, de forma a garantir que apenas vagas inéditas sejam notificadas e que os dados persistam entre execuções efêmeras.

**Why this priority**: É o requisito nuclear para permitir a execução fora da máquina local (ex.: GitHub Actions, contentores sem volume persistente) sem enviar alertas repetidos.

**Independent Test**: Pode ser testado de forma isolada ao instanciar o `SupabaseStorage` com mocks do cliente HTTP/REST, simulando a consulta de existência (`is_seen`) e a inserção com deduplicação (`save_job`), garantindo que chamadas idempotentes funcionam sem erros.

**Acceptance Scenarios**:

1. **Given** que o ID composto `gupy:12345` não existe na tabela `jobs`, **When** o crawler invoca `is_seen("gupy:12345")`, **Then** o sistema deve retornar `False`.
2. **Given** que a vaga com ID `gupy:12345` é nova, **When** o método `save_job` é executado com os dados da vaga, **Then** o sistema deve realizar o `upsert` com sucesso no Supabase e retornar `True`.
3. **Given** que a vaga com ID `gupy:12345` já existe na tabela `jobs`, **When** o crawler invoca `is_seen("gupy:12345")`, **Then** o sistema deve retornar `True`.

---

### User Story 2 - Resiliência e Fallback de Configuração (Priority: P2)

Como engenheiro de software, pretendo que o sistema valide as credenciais (`SUPABASE_URL` e `SUPABASE_KEY`) ao inicializar e efetue o tratamento adequado de falhas temporárias de rede na API REST sem terminar o processo abruptamente.

**Why this priority**: Evita falhas silenciosas ou falhas críticas em tempo de execução quando variáveis de ambiente obrigatórias não estiverem configuradas no ambiente de execução.

**Independent Test**: Pode ser testado fornecendo credenciais em falta ou simulando exceções de conexão no cliente assíncrono durante operações de I/O.

**Acceptance Scenarios**:

1. **Given** que as variáveis `SUPABASE_URL` ou `SUPABASE_KEY` não estão presentes no ambiente nem no ficheiro `.env`, **When** o adaptador `SupabaseStorage` for inicializado sem parâmetros, **Then** deve lançar uma exceção de configuração explícita e informativa.
2. **Given** que a API REST do Supabase devolve um erro HTTP transitório (ex.: 503 Service Unavailable), **When** o método `save_job` é invocado, **Then** o sistema deve capturar o erro, registar o log apropriado e retornar `False` sem interromper a execução do pipeline.

---

### Edge Cases

- O que acontece se a chave primária `id` colidir com formatos não esperados? O identificador composto deve sempre normalizar a string no formato `{ats}:{external_id}` antes do envio.
- Como o sistema lida com campos opcionais nulos (ex.: `location` ou `published_at` ausentes)? O mapeador de payload deve serializar campos `None` como `null` e formatar instâncias de `datetime` para padrão ISO 8601 em formato de texto.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE fornecer a classe `SupabaseStorage` com interface assíncrona compatível com o orquestrador (`is_seen` e `save_job`).
- **FR-002**: O sistema DEVE utilizar a chave primária determinística composta pelo prefixo da plataforma e o ID externo (`{ats}:{external_id}`).
- **FR-003**: O sistema DEVE realizar operações de inserção via `upsert` com tratamento explícito de conflito no campo `id` (`on_conflict="id"`).
- **FR-004**: O sistema DEVE carregar as variáveis de autenticação `SUPABASE_URL` e `SUPABASE_KEY` a partir do ambiente ou ficheiro `.env`.
- **FR-005**: O sistema DEVE serializar datas no padrão ISO 8601 UTC antes do envio para a API REST.

### Key Entities

- **JobRecord**: Representação serializada da oportunidade para o Supabase contendo `id`, `ats`, `external_id`, `title`, `company`, `location`, `url`, `published_at` e `created_at`.
- **SupabaseStorage**: Adaptador de persistência responsável por estabelecer o cliente assíncrono e coordenar chamadas de deduplicação e escrita contra a tabela `jobs`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% dos testes unitários do adaptador executados com mocks sem qualquer dependência de rede externa ou base de dados em tempo real.
- **SC-002**: Tempo de execução da verificação de duplicatas e escrita não deve bloquear a rotação do event loop assíncrono do `asyncio`.
- **SC-003**: Nenhuma chave de API ou credencial deve ser exposta em logs, ficheiros de teste ou histórico de versões.

## Assumptions

- O projeto no Supabase possui a tabela `jobs` previamente provisionada com a chave primária `id (text)`.
- A chave de autenticação configurada possui privilégios de escrita na tabela (utilização da chave `service_role` ou permissões adequadas via RLS).
- A biblioteca oficial `supabase` (com suporte assíncrono via `AsyncClient`) é compatível com o ecossistema Python do projeto gerido pelo `uv`.
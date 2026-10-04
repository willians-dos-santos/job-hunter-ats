# Feature Specification: Gupy ATS Collector Adapter (Public Portal API)

**Feature Branch**: `002-gupy-collector`

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "Integrar adaptador de coleta para o portal público de carreiras da Gupy (portal.api.gupy.io), sem exigência de API Key privada."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extração Pública de Vagas da Gupy (Priority: P1)

Como utilizador, pretendo coletar vagas disponíveis nos murais públicos de carreiras da Gupy sem necessitar de chaves de API proprietárias.

**Why this priority**: Permite monitorizar empresas brasileiras de forma aberta e idêntica à navegação do candidato.

**Independent Test**: Testes unitários com mocks simulando a estrutura retornada pelo endpoint público (`portal.api.gupy.io`), validando o parser da chave raiz `data`.

**Acceptance Scenarios**:

1. **Given** um slug de empresa válido (ex: `ambev`, `picpay`), **When** o coletor consulta `https://portal.api.gupy.io/api/v1/jobs?subdomain={company}&limit=100`, **Then** a lista contida no array `data` é mapeada para instâncias `JobOpening`.
2. **Given** itens com `isRemoteWork: true`, **When** normalizados, **Then** o campo `location` gerado deve conter `"Remoto"`.
3. **Given** falhas de requisição ou status 404/500, **When** o coletor executa, **Then** a exceção é capturada de forma segura sem travar o crawler.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE utilizar o endpoint público `https://portal.api.gupy.io/api/v1/jobs?subdomain={company}&limit=100`.
- **FR-002**: As requisições DEVEM incluir cabeçalho `User-Agent: Mozilla/5.0` para evitar bloqueios ou respostas 403 do CDN.
- **FR-003**: O mapeamento deve extrair a lista a partir do campo raiz `data`.
  - `job_id`: `f"gupy_{item['id']}"`
  - `title`: `item['name']`
  - `url`: `item.get('careerPageUrl') or item.get('jobUrl') or f"https://{company}.gupy.io/jobs/{item['id']}"`
  - `location`: `"Remoto"` se `item.get('isRemoteWork')` for verdadeiro; caso contrário, formatar `f"{item.get('city', '')} - {item.get('state', '')}"`.
- **FR-004**: O tipo `source` no modelo `JobOpening` (`src/models.py`) DEVE incluir a literal `'Gupy'`.

## Success Criteria *(mandatory)*

- **SC-001**: 100% dos testes unitários da nova rota aprovados via `uv run pytest`.
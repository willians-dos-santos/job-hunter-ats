# Feature Specification: Solides ATS Collector Adapter

**Feature Branch**: `005-solides-collector`  
**Created**: 2026-10-13  
**Status**: Ready for Implementation  
**Input**: Solicitação do usuário: "Implementação da Spec 005 (integração do novo coletor Solides) respeitando a constitution.md e o specs/database-schema.md."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extração Pública de Vagas da Solides com Paginação (Priority: P1)

Como engenheiro de software à procura de vagas no ecossistema brasileiro, pretendo coletar oportunidades abertas no portal público da Solides (`vagas.solides.com.br`) utilizando termos de busca dinâmicos e paginação automática completa até a última página disponível, garantindo a captura exaustiva de vagas abertas.

**Why this priority**: É o valor primário do adaptador: conectar a plataforma Solides ao pipeline de busca automatizada do ATS Crawler sem intervenção manual.

**Independent Test**: Pode ser validado através de testes unitários isolados com respostas mockadas da API REST da Solides (`GET https://vagas.solides.com.br/api/vacancies`), assegurando que a paginação inicia em `page=1` e segue até `totalPages` com `take=20`.

**Acceptance Scenarios**:
1. **Given** um alvo configurado com `source: "solides"` e `query: "Python"`, **When** o coletor consulta `https://vagas.solides.com.br/api/vacancies`, **Then** a requisição inclui `page=1`, `take=20`, `title="Python"` e `locations=""`.
2. **Given** uma resposta da Solides com `totalPages=3`, **When** o coletor executa `fetch_jobs`, **Then** ele percorre sequencialmente as páginas 1, 2 e 3, agregando todas as vagas retornadas.
3. **Given** uma resposta com `totalPages=1` ou array `data` vazio, **When** o coletor executa, **Then** a iteração encerra imediatamente sem chamadas excedentes.

---

### User Story 2 - Normalização Segura e Contratos de Dados (Priority: P1)

Como operador do crawler, pretendo que cada vaga da Solides seja convertida fielmente para o esquema canónico `JobOpening`, com identificadores únicos consistentes, URLs acessíveis e tratamento defensivo para campos opcionais nulos ou formatos heterogéneos.

**Why this priority**: Garante integridade referencial, compatibilidade com os filtros determinísticos e previne falhas de validação de runtime no Pydantic.

**Independent Test**: Testes unitários com payloads contendo IDs numéricos (`int`), IDs alfanuméricos (`str`), valores nulos de cidade/estado e diferentes combinações de modalidade de trabalho.

**Acceptance Scenarios**:
1. **Given** um item com `id=936455` (inteiro), **When** normalizado, **Then** `job_id` deve ser `"solides_936455"`, `source_job_id` deve ser `"936455"` e a URL canónica gerada deve ser `"https://vagas.solides.com.br/vaga/936455"`.
2. **Given** um item com `id="abc-789"` (string), **When** normalizado, **Then** `job_id` deve ser `"solides_abc-789"` e a URL deve ser `"https://vagas.solides.com.br/vaga/abc-789"`.
3. **Given** um item com `jobType="remoto"` ou `homeOffice=true`, **When** a modalidade for avaliada, **Then** o mapeamento resulta em `"remote"`.
4. **Given** um item com `jobType="hibrido"`, **When** a modalidade for avaliada, **Then** o mapeamento resulta em `"hybrid"`. Caso contrário, o resultado deve ser `"on_site"`.
5. **Given** um item com cidade `Serra` e estado com código `ES`, **When** a localização for formatada, **Then** deve gerar `"Serra - ES"`.
6. **Given** um item com cidade e estado nulos, **When** a localização for processada, **Then** o fallback defensivo deve definir `"Remoto"`.
7. **Given** um campo `createdAt` com formato ISO 8601 (ex.: `"2026-10-12"` ou `"2026-10-12T14:30:00Z"`), **When** processado, **Then** `published_at` deve conter uma instância válida de `datetime` ciente de fuso horário UTC.

---

### User Story 3 - Resiliência Operacional, Rate Limiting e Isolamento de Falhas (Priority: P2)

Como mantenedor da infraestrutura, pretendo que chamadas com falha temporária de rede ou restrições de taxa (HTTP 429) utilizem tentativas com recuo exponencial e que respostas de erro não bloqueiem a execução das demais plataformas.

**Why this priority**: Cumpre os princípios I e IV da `constitution.md` (Async First e Idempotency & Fault Isolation).

**Independent Test**: Teste unitário simulando status HTTP 429 com header `Retry-After` e timeouts de rede, verificando retentativas e recuperação graciosa.

**Acceptance Scenarios**:
1. **Given** uma resposta HTTP 429 da Solides, **When** o coletor recebe a limitação, **Then** aguarda o intervalo do `Retry-After` ou aplica recuo exponencial e tenta novamente até o limite de retentativas.
2. **Given** uma falha de conexão persistente na Solides, **When** o coletor atinge o limite de tentativas, **Then** registra a falha no log e retorna lista vazia sem propagar exceção não tratada ao orquestrador.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O coletor `SolidesCollector` DEVE consumir o endpoint canónico `GET https://vagas.solides.com.br/api/vacancies`.
- **FR-002**: O coletor DEVE paginar automaticamente de `page=1` até `totalPages`, consumindo lotes de `take=20`.
- **FR-003**: O parâmetro `title` DEVE ser extraído dinamicamente a partir das configurações de busca (`target.query` ou `target.name`), e `locations` DEVE ser enviado com valor padrão vazio (`""`).
- **FR-004**: O identificador canónico `job_id` DEVE ser gerado estritamente como string com formato `solides_{id}`, e `source_job_id` como string do identificador bruto.
- **FR-005**: O literal `'solides'` DEVE ser incluído nos enums/literais de tipos válidos para o atributo `source` dos modelos `JobOpening` e `TargetCompany` em `src/models.py`.
- **FR-006**: A URL pública canónica DEVE ser gerada como `https://vagas.solides.com.br/vaga/{id}`.
- **FR-007**: O mapeamento de modalidade de trabalho DEVE classificar:
  - `"remote"`: se `jobType == "remoto"` ou `homeOffice is True`.
  - `"hybrid"`: se termo "hibrid" / "híbrid" for detectado em `jobType`.
  - `"on_site"`: nos demais casos.
- **FR-008**: O campo `location` DEVE ser formatado com fallback defensivo para campos nulos: `f"{city.name} - {state.code}"` quando presentes; caso contrários nulos, utilizar `"Remoto"`.
- **FR-009**: O campo `published_at` DEVE realizar parse resiliente a partir de `createdAt`.
- **FR-010**: O coletor `SolidesCollector` DEVE ser registrado no dicionário de coletores do `CrawlerOrchestrator` em `src/orchestrator.py` sob a chave `"solides"`.
- **FR-011**: O coletor DEVE enviar cabeçalhos HTTP com `User-Agent` moderno e `Accept: application/json` e timeout padrão de 15 segundos.

---

### Key Entities

- **SolidesCollector**: Subclasse de `BaseCollector` responsável pela comunicação assíncrona, paginação e parsing de vagas do portal Solides.
- **JobOpening**: Modelo canónico Pydantic v2 enriquecido com a nova fonte `'solides'` e suporte a modalidade.
- **TargetCompany**: Modelo de configuração suportando `'solides'` como plataforma de destino.

---

## Success Criteria *(mandatory)*

- **SC-001**: 100% dos testes unitários em `tests/collectors/test_solides.py` e em toda a suíte aprovados com `pytest`.
- **SC-002**: 0 erros e 0 alertas em `ruff check .`.
- **SC-003**: Deduplicação e integridade garantidas com o esquema de banco de dados documentado em `specs/database-schema.md`.

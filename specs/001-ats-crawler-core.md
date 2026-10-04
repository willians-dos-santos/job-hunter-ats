# Feature Specification: ATS Job Crawler Core

**Feature Branch**: `001-ats-crawler-core`

**Created**: 2026-10-04

**Status**: Draft

**Input**: User description: "Construir um crawler assíncrono para coletar vagas em APIs públicas de ATS (como Greenhouse e Lever), aplicando filtros determinísticos, armazenando os dados em SQLite e enviando notificações automáticas sobre novas oportunidades."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Extração e Normalização de Vagas ATS (Priority: P1)

Como engenheiro de software à procura de colocações remotas ou específicas, pretendo coletar vagas diretamente das APIs públicas da Greenhouse e da Lever num formato de dados uniforme, para que não precise de consultar múltiplos portais manualmente.

**Why this priority**: É o núcleo do sistema — o MVP essencial. Sem uma coleta e normalização rigorosa dos dados brutos, nenhuma das etapas posteriores consegue funcionar de forma confiável.

**Independent Test**: Pode ser testado de forma isolada injetando respostas mockadas em formato JSON dos dois fornecedores de ATS e verificando a conversão exata para o modelo canónico de dados.

**Acceptance Scenarios**:

1. **Given** um slug válido de empresa na Greenhouse, **When** o coletor consulta o endpoint público, **Then** as vagas retornadas são convertidas em objetos `JobOpening` com `job_id`, título, localização e endereço URL canónico devidamente preenchidos.
2. **Given** um slug válido de empresa na Lever, **When** o coletor consulta o endpoint público, **Then** as vagas retornadas são convertidas em objetos `JobOpening` com os mesmos campos padronizados.
3. **Given** uma resposta com falha de rede ou código de estado HTTP 404/500 numa organização, **When** o coletor executa, **Then** o erro é registado sem interromper a execução das restantes recolhas agendadas.

---

### User Story 2 - Filtragem Determinística e Deduplicação (Priority: P2)

Como utilizador, pretendo que o sistema filtre as vagas por palavras-chave de cargo e localização geográfica e evite alertar sobre oportunidades já processadas anteriormente.

**Why this priority**: Evita ruído informativo, garantindo que apenas oportunidades relevantes e inéditas chegam ao utilizador.

**Independent Test**: Pode ser validado através de testes unitários no repositório de persistência SQLite, confirmando que a chamada a `is_new()` devolve `False` imediatamente após uma chamada a `mark_as_seen()`.

**Acceptance Scenarios**:

1. **Given** uma oportunidade que contém "Backend" no título e "Remote" na localização, **When** os critérios configurados exigem estes termos, **Then** a vaga é aprovada pelo filtro de elegibilidade.
2. **Given** uma oportunidade cujo identificador já conste na tabela `seen_jobs`, **When** é reavaliada num ciclo posterior, **Then** a oportunidade é descartada e nenhuma notificação é emitida.

---

### User Story 3 - Despacho de Alertas Estruturados (Priority: P3)

Como utilizador, pretendo receber uma notificação estruturada (via Telegram Bot ou saída em console) contendo os dados essenciais e o endereço direto da vaga para submissão imediata da candidatura.

**Why this priority**: Fecha o ciclo de valor da ferramenta, entregando a informação no canal de comunicação do utilizador com fricção zero.

**Independent Test**: Pode ser testado simulando o envio de mensagens para o Telegram com mocks de rede ou verificando a formatação do texto gerado para a saída padrão (*stdout*).

**Acceptance Scenarios**:

1. **Given** uma nova vaga aprovada pelo filtro, **When** as credenciais do Telegram estão configuradas no ambiente, **Then** uma mensagem formatada em Markdown com o link canónico é expedida para o chat designado.
2. **Given** uma nova vaga aprovada sem credenciais de Telegram disponíveis, **When** o notificador executa, **Then** os dados são emitidos de forma legível no terminal sem interrupção por exceção.

---

### Edge Cases

- O que acontece se uma empresa no Greenhouse não preencher o campo `location` no payload JSON? O sistema deve atribuir um valor predeterminado seguro (`"N/A"`) sem gerar exceções de chave ausente.
- Como o sistema gere restrições de chamadas (HTTP 429 Too Many Requests)? O coletor deve implementar um mecanismo de repetição com recuo exponencial (*exponential backoff*) e respeitar a concorrência delimitada por semáforo.
- O que acontece se o ficheiro da base de dados SQLite for apagado ou corrompido? O módulo de persistência deve recriar automaticamente o esquema inicial de tabelas na inicialização.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema DEVE consumir endpoints REST públicos da Greenhouse (`boards-api.greenhouse.io`) e da Lever (`api.lever.co`) de forma assíncrona.
- **FR-002**: O sistema DEVE normalizar os dados recolhidos para um modelo tipado estritamente através do Pydantic v2.
- **FR-003**: O sistema DEVE carregar a lista de empresas-alvo e termos de filtragem a partir de um ficheiro de configuração estruturado (`config.yaml`).
- **FR-004**: O sistema DEVE persistir e consultar identificadores de oportunidades numa base de dados relacional local SQLite para assegurar idempotência.
- **FR-005**: O sistema DEVE disponibilizar integração com Telegram Bot para envio de mensagens automáticas de alerta.
- **FR-006**: O sistema DEVE suportar limitação de concorrência com recurso a `asyncio.Semaphore` para mitigar bloqueios de IP.

### Key Entities

- **JobOpening**: Representa uma oportunidade de trabalho normalizada. Contém atributos como identificador canónico (`job_id`), plataforma de origem (`source`), empresa (`company`), título do cargo (`title`), localização (`location`), hiperligação canónica (`url`) e data de publicação (`published_at`).
- **TargetCompany**: Representa a configuração de monitorização de uma organização. Contém o slug da entidade e a plataforma de recrutamento associada (`greenhouse` ou `lever`).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: O ciclo de coleta, filtragem e persistência para um lote de 20 organizações monitorizadas deve concluir em menos de 15 segundos numa ligação de rede padrão.
- **SC-002**: A taxa de falsos positivos na deduplicação deve ser estritamente de 0%, garantindo que nenhuma oportunidade repetida seja notificada duas vezes.
- **SC-003**: Cobertura de testes unitários para os parsers de dados da Greenhouse e da Lever superior a 90%, validada via `pytest`.

## Assumptions

- O utilizador possui o interpretador Python 3.11 ou superior instalado no ambiente de execução.
- As APIs públicas da Greenhouse e da Lever mantêm o acesso aberto sem obrigatoriedade de cabeçalhos de autenticação ou chaves privadas.
- O volume inicial de monitorização não excede os limites públicos de taxa de pedidos por IP impostos pelas plataformas de ATS.
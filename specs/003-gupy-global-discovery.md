# Feature Specification: Gupy Global Discovery Collector

**Feature Branch**: `003-gupy-global-discovery`  
**Created**: 2026-10-04  
**Status**: Ready for Implementation  
**Input**: Solicitação do usuário: "Permitir busca automática/aberta no portal da Gupy sem precisar passar nome de empresa fixa."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Global Job Discovery by Search Query (Priority: P1)

Como uma pessoa desenvolvedora em busca de oportunidades, quero consultar o portal da Gupy de forma global utilizando palavras-chave técnicas (como "Python", "Java", "Backend"), para descobrir vagas abertas em várias empresas sem ter que cadastrar empresa por empresa na configuração.

#### Acceptance Scenarios

1. **Dado** um alvo configurado com `source: "gupy_global"` e um termo de busca no campo `query`, **Quando** o coletor for executado, **Então** ele deve fazer a requisição para `https://portal.gupy.io/api/job-search/jobs?jobName={query}&limit=100&offset=0` sem enviar o parâmetro `careerPageName`.
2. **Dado** o payload de resposta contendo vagas de diversas empresas, **Quando** for feita a normalização para o modelo `JobOpening`, **Então** o campo `company` deve ser preenchido dinamicamente com o valor de `careerPageName` de cada item (usando `"Gupy"` como fallback caso venha vazio ou nulo).
3. **Dado** um item de vaga onde o campo `workplaceType` seja igual a `"remote"`, **Quando** o local for processado, **Então** o campo `location` deve ser definido como `"Remoto"`.
4. **Dado** a execução da suíte de testes com mocks das respostas da API, **Quando** o `pytest` for executado, **Então** todas as vagas de empresas variadas devem ser processadas, filtradas e validadas com 100% de sucesso.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O modelo `TargetCompany` em `src/models.py` deve aceitar a fonte `"gupy_global"` e um campo opcional `query: Optional[str] = None`. Caso `query` não seja informado, o valor de `name` deve ser utilizado como termo de busca padrão.
- **FR-002**: O coletor `GupyCollector` em `src/collectors/gupy.py` deve bater no endpoint canônico `https://portal.gupy.io/api/job-search/jobs` passando os parâmetros `jobName={query}`, `limit=100` e `offset=0`.
- **FR-003**: O parâmetro `careerPageName` NÃO deve ser incluído na query string quando a fonte for `gupy_global`.
- **FR-004**: Para cada vaga retornada, o nome da empresa deve ser extraído dinamicamente do campo `careerPageName` retornado no item (`item.get("careerPageName") or "Gupy"`).
- **FR-005**: A regra de normalização de trabalho remoto deve ser mantida: se `item.get("workplaceType") == "remote"`, definir `location = "Remoto"`.
- **FR-006**: Os cabeçalhos de simulação de navegador (`User-Agent` e `Accept: application/json`) devem continuar sendo enviados em todas as requisições HTTP.

---

## Success Criteria *(mandatory)*

- **SC-001**: Suíte de testes unitários (`tests/test_gupy_collector.py`) atualizada com mocks cobrindo busca global e passando com 100% de sucesso no `uv run pytest`.
- **SC-002**: Execução completa via `uv run python -m src.main --config config.yaml` processando alvos globais da Gupy e entregando as novas vagas no Telegram sem falhas ou duplicações.
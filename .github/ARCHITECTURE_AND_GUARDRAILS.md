# Backend Architecture & Guardrails

**Blanco Finanças API – Finance-Grade Backend Rules**

Este documento define **regras não negociáveis** para o backend do Blanco Finanças.
Ele existe para evitar erros **financeiros, contábeis, legais e de segurança** que não são óbvios em revisões superficiais.

Se algo **não estiver explicitamente permitido aqui**, considere **proibido**.

Aplica-se igualmente a:

- Desenvolvedores humanos
- Agentes de IA
- Scripts temporários, protótipos ou atalhos operacionais

---

## 1. Autoridade Arquitetural & Limites

### 1.1 Separação de Responsabilidades (Regras Rígidas)

**API / Controllers (`app/api/`)**

- PODEM:
  - Validar entrada e saída (Pydantic)
  - Resolver autenticação e autorização
  - Chamar casos de uso da camada Application
- NÃO PODEM:
  - Conter regras de negócio
  - Calcular valores financeiros
  - Acessar diretamente o banco de dados
  - Chamar serviços externos

Controllers finos são obrigatórios. Qualquer lógica além de orquestração é defeito.

---

**Application / Use Cases (`app/application/`)**

- SÃO o único local onde:
  - Casos de uso são orquestrados
  - Transações são controladas
  - Repositórios e serviços de domínio são coordenados
- DEVEM:
  - Ser stateless
  - Retornar entidades de domínio ou DTOs internos
- NÃO DEVEM:
  - Conhecer HTTP, FastAPI ou Pydantic
  - Conhecer detalhes de persistência ou bibliotecas externas

Um caso de uso = uma ação de negócio bem definida.

---

**Domain (`app/domain/`)**

- É a autoridade máxima das regras de negócio
- DEVE:
  - Ser Python puro
  - Conter invariantes explícitas
  - Falhar imediatamente quando regras são violadas
- NÃO PODE:
  - Importar FastAPI, SQLAlchemy, Pydantic ou httpx
  - Realizar qualquer tipo de I/O

Se uma regra financeira não está no domínio, ela não existe oficialmente.

---

**Infrastructure (`app/infrastructure/`)**

- IMPLEMENTA detalhes externos:
  - Banco de dados
  - APIs externas (BCB, Pix)
  - PDF, Excel, segurança
- NÃO DEFINE regras de negócio
- É substituível por definição

---

## 2. Correção Financeira (Zona de Tolerância Zero)

### 2.1 Regras Numéricas

- `float` é terminantemente proibido para valores monetários
- Toda quantia financeira deve usar:
  - `decimal.Decimal` em memória
  - `DECIMAL` ou `BIGINT` (centavos) no banco
- Estratégias de arredondamento devem ser:
  - Explícitas
  - Centralizadas
  - Testadas

Cálculos financeiros implícitos são considerados defeitos graves.

---

### 2.2 Origem de Valores Financeiros

- O backend é a **única fonte de verdade**
- Nenhum valor financeiro pode ser:
  - Inferido
  - Aproximado
  - Recalculado sem persistência

Se o valor não puder ser explicado em auditoria, ele não pode existir.

---

## 3. Cálculo de Rendimentos (Poupança)

### 3.1 Fonte Oficial (Obrigatória)

- ÚNICA fonte permitida:
  - **Banco Central do Brasil – API SGS**
- Séries aceitas:
  - SGS 25 (até 03/05/2012)
  - SGS 195 (a partir de 04/05/2012)

Qualquer outra fonte é proibida, mesmo que considerada equivalente.

---

### 3.2 Regras de Implementação

- O cálculo deve:
  - Respeitar a data de aniversário do depósito
  - Ser diário (não mensal simplificado)
  - Ser determinístico
- Toda a lógica deve residir em:
  - `domain/services/PoupancaYieldCalculator`
- O serviço deve possuir:
  - Cobertura total de testes
  - Casos baseados em valores oficiais do BCB

Chamadas ao BCB nunca ocorrem durante o cálculo.

---

### 3.3 Persistência de Dados Externos

- Dados do BCB devem ser:
  - Persistidos localmente
  - Versionados
- Cálculos devem utilizar snapshots armazenados

Recalcular com dados ao vivo é inaceitável.

---

## 4. Fundo Garantidor

- O percentual (1% a 1.3%) deve ser:
  - Configurável
  - Centralizado
  - Totalmente testável
- A lógica deve:
  - Estar isolada no domínio
  - Nunca ser duplicada em serviços ou controllers

Percentual hardcoded é erro crítico.

---

## 5. Contratos, Transações e Pix

### 5.1 Contratos

- PDFs gerados devem ser:
  - Imutáveis após aceite
  - Auditáveis
- Qualquer regeneração deve:
  - Preservar a versão original
  - Ser explicitamente versionada

---

### 5.2 Pix e Conciliação

- O backend é responsável por:
  - Gerar o payload Pix
  - Correlacionar callbacks com transações pendentes
- A conciliação deve ser:
  - Idempotente
  - Tolerante a reenvio
  - Totalmente rastreável

Não assumir ordem correta de eventos.

---

## 6. Autenticação, Autorização e Segurança

### 6.1 Autenticação

- JWT é obrigatório
- Tokens devem:
  - Ter escopo explícito
  - Possuir expiração definida
- Senhas devem:
  - Ser armazenadas apenas como hash (bcrypt)
  - Nunca ser retornadas ou logadas

---

### 6.2 Autorização

- Toda ação deve:
  - Validar ownership
  - Validar role (admin vs client)
- Nunca confiar em:
  - IDs vindos do frontend
  - Rotas ocultas ou UI

A API assume cliente malicioso por padrão.

---

## 7. Banco de Dados & Transações

### 7.1 SQLAlchemy

- Apenas sintaxe 2.0
- Apenas `AsyncSession`
- Transações explícitas

---

### 7.2 Repositórios

- Retornam entidades de domínio
- Mapeiam ORM ↔ domínio
- Não expõem modelos SQLAlchemy

Entidades não podem vazar detalhes de persistência.

---

## 8. Logs, Auditoria e Rastreabilidade

- Ações críticas devem registrar:
  - Quem
  - Quando
  - O quê
- Logs de auditoria devem ser:
  - Imutáveis
  - Consultáveis
- Rendimentos creditados devem armazenar:
  - Série SGS utilizada
  - Intervalo de referência
  - Taxa efetiva aplicada

Sem rastreabilidade, o sistema é inválido.

---

## 9. Testes (Obrigatórios)

- `pytest` e `pytest-asyncio` são obrigatórios
- O domínio deve possuir:
  - Cobertura total
- Testes devem incluir:
  - Casos extremos
  - Datas limite
  - Mudanças de regra (ex: Selic)

Testes apenas de caminho feliz são insuficientes.

---

## 10. Política de Dependências

- Adicionar dependências é proibido por padrão
- Só é permitido se:
  - Aumentar segurança ou precisão
  - Não duplicar funcionalidades existentes
  - Possuir justificativa técnica clara

Conveniência do desenvolvedor não é argumento.

---

## 11. Restrições para IA

IA não pode:

- Inventar fórmulas financeiras
- Criar regras implícitas
- Assumir limites de negócio não documentados

Na dúvida, a IA deve parar e sinalizar a lacuna.

---

## 12. Filosofia de Falha

Em sistemas financeiros:

- Falhar alto é melhor que falhar silencioso
- Estados inconsistentes devem:
  - Lançar erro
  - Bloquear execução
- Fallbacks silenciosos são proibidos

---

## 13. Princípio Final

Qualquer mudança que:

- Reduza a precisão financeira
- Diminua a auditabilidade
- Misture responsabilidades

Está errada por definição e exige justificativa explícita e documentada.


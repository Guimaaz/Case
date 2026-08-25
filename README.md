# Desafio Técnico — Estágio em Engenharia de IA

Triagem de operações financeiras para Prevenção à Lavagem de Dinheiro (PLD),
combinando **regras determinísticas** (o cálculo, em pandas) com um **modelo de
linguagem** (a interpretação e a redação do parecer).

> Todos os dados são fictícios e foram gerados para fins de avaliação.

## Estrutura

```
dados/      bases de entrada dos níveis 1 e 2
nivel_1/    notebook com tratamento, regras e análise com LLM
nivel_2/    ferramentas, agente e confronto regra x modelo
outputs/    resultados das execuções
docs/       decisões, uso de IA e enunciado
```

## Como rodar

```bash
pip install -r requirements.txt
cp .env.example .env      # preencha GROQ_API_KEY e GROQ_MODEL
```

Abra `nivel_1/nivel_1.ipynb` e execute com **Restart Kernel and Run All**.
As saídas já estão salvas no arquivo — não é necessário executar para avaliar.

- **Provedor:** Groq (camada gratuita)
- **Modelo:** `openai/gpt-oss-120b`

## O que foi feito

### Nível 1 — completo

**Qualidade dos dados.** Diagnostiquei quatro problemas na base de 20 operações:
a coluna `data` armazenada como texto, uma operação sem data, uma operação em USD
misturada a 19 em BRL sem sinalização, e uma linha inteiramente duplicada. Cada
tratamento está justificado no notebook; as decisões sem resposta única estão
detalhadas em [`docs/DECISOES.md`](docs/DECISOES.md).

**Regras determinísticas.** Fracionamento (3+ operações no mesmo dia somando mais
de R$ 50.000, nenhuma atingindo R$ 20.000) e valor atípico (operação acima de 5x a
mediana do cliente, apenas para clientes com 4+ operações). Ambas validadas com
caso positivo e casos negativos próximos.

**Resultados.** `CLI-A-1` sinalizado por fracionamento — três operações em 09/03
somando R$ 54.200, todas entre R$ 17.300 e R$ 18.800. `OP-0013` sinalizada por
valor atípico: R$ 64.800 contra mediana de R$ 5.450 do cliente. Esta segunda só
foi detectada porque o valor em dólar foi convertido no tratamento — no valor de
origem, passaria despercebida.

**Análise com LLM.** Parecer estruturado com validação por Pydantic, tratamento de
resposta malformada, e registro de tokens e latência. Comparei duas versões do
prompt: a minimalista falhou na validação (devolveu `"Alto"` em vez de `"alto"`) e
alucinou um indício inexistente; a estruturada validou e custou apenas 5% mais em
tokens.

### Nível 2 — não implementado

Plano detalhado em
[`docs/DECISOES.md`](docs/DECISOES.md#nivel-2-o-que-faria).

### Nível 3 — não implementado

Trilha B (servidor MCP local). Plano em
[`docs/DECISOES.md`](docs/DECISOES.md#nivel-3-trilha-escolhida).

## Separação entre regra e LLM

Toda contagem, soma, mediana e comparação com limiar é feita em pandas. A LLM
recebe um dossiê com os números já calculados e é responsável apenas por
interpretar o padrão, nomear a tipologia e redigir o parecer. Nenhuma decisão
numérica é delegada ao modelo.

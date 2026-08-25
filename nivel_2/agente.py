"""Agente de triagem de PLD com tool calling.

O agente recebe o resumo inicial de um cliente sinalizado e decide quais
ferramentas consultar antes de emitir o parecer. Não há roteiro fixo: as
ferramentas efetivamente chamadas variam conforme o caso, e ficam registradas
no resultado como evidência da decisão.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from groq import Groq
from pydantic import BaseModel, ValidationError

import tools
from pipeline import preparar, top_clientes

load_dotenv("../.env", override=True)

MODELO = os.environ["GROQ_MODEL"]
cliente_llm = Groq(api_key=os.environ["GROQ_API_KEY"])

MAX_RODADAS = 5
CACHE = Path("../.cache")


class Parecer(BaseModel):
    nivel_risco: Literal["baixo", "medio", "alto"]
    tipologia_suspeita: str
    red_flags: list[str]
    justificativa: str


FERRAMENTAS = [
    {
        "type": "function",
        "function": {
            "name": "historico_cliente",
            "description": (
                "Resumo agregado de todas as operações do cliente: volume total, "
                "ticket médio e mediano, maior e menor operação, período, tipos de "
                "operação e regras acionadas. Use para entender o porte e o padrão "
                "geral do cliente, ou para contextualizar se uma operação é grande "
                "em relação ao próprio histórico."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cliente_id": {"type": "string", "description": "ex: CLI-029"}
                },
                "required": ["cliente_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "operacoes_do_dia",
            "description": (
                "Lista as operações de um cliente numa data específica, com valor, "
                "canal, tipo e contraparte de cada uma. Use quando precisar examinar "
                "o detalhe de um dia — tipicamente o dia em que a regra de "
                "fracionamento foi acionada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cliente_id": {"type": "string", "description": "ex: CLI-029"},
                    "data": {"type": "string", "description": "formato AAAA-MM-DD"},
                },
                "required": ["cliente_id", "data"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "perfil_canal",
            "description": (
                "Distribuição das operações do cliente por canal (pix, ted, boleto, "
                "cartao, especie), em quantidade e percentual de volume, com o canal "
                "predominante e se há uso de espécie. Use quando a suspeita envolver "
                "escolha de canal ou movimentação em dinheiro."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cliente_id": {"type": "string", "description": "ex: CLI-029"}
                },
                "required": ["cliente_id"],
            },
        },
    },
]

EXECUTORES = {
    "historico_cliente": tools.historico_cliente,
    "operacoes_do_dia": tools.operacoes_do_dia,
    "perfil_canal": tools.perfil_canal,
}

PROMPT_SISTEMA = """Você é analista sênior de Prevenção à Lavagem de Dinheiro (PLD) de um banco brasileiro.

Você recebe o resultado da triagem automática de um cliente. Todos os números já
foram calculados por regras determinísticas auditadas — não recalcule nada e não
infira valores que não estejam nos dados fornecidos.

Você tem ferramentas para consultar a base. Use apenas as que forem relevantes
para o caso à sua frente: cada consulta tem custo, e chamar tudo por hábito não é
investigar. Se o resumo inicial já bastar para o parecer, não chame nenhuma.

Orientação:
- Suspeita de fracionamento pede o detalhe do dia em que a regra disparou.
- Suspeita de valor atípico pede o histórico, para saber se o valor destoa mesmo.
- Suspeita ligada a canal ou espécie pede o perfil de canais.

Quando tiver informação suficiente, pare de consultar e emita o parecer."""

PROMPT_PARECER = """Com base em tudo que você levantou, emita o parecer final.

Responda APENAS com um objeto JSON, sem texto antes ou depois:

{
  "nivel_risco": "baixo" | "medio" | "alto",
  "tipologia_suspeita": "<tipologia de PLD, ou 'nenhuma identificada'>",
  "red_flags": ["<indício objetivo observado nos dados>"],
  "justificativa": "<2 a 4 frases ligando os indícios à tipologia>"
}

Regras:
- Use exatamente "baixo", "medio" ou "alto", sem acento.
- red_flags devem ser indícios presentes nos dados consultados, não hipóteses.
- Não invente informação que não tenha sido consultada."""


def _chave_cache(resumo):
    bruto = json.dumps(
        {"modelo": MODELO, "resumo": resumo}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(bruto.encode()).hexdigest()[:16]


def _chamar_parecer(mensagens):
    """Pede o parecer final. Tenta em modo JSON; se falhar, tenta sem ele.

    O modo JSON da API rejeita geração vazia, o que acontece quando o modelo
    consome o orçamento de tokens raciocinando. O fallback sem modo JSON ainda
    produz um parecer utilizável, porque o formato também está no prompt e a
    validação final é do Pydantic.
    """
    tentativas = [
        {"max_tokens": 3000, "response_format": {"type": "json_object"}},
        {"max_tokens": 3000},
    ]
    ultimo_erro = None
    for extra in tentativas:
        try:
            return cliente_llm.chat.completions.create(
                model=MODELO, messages=mensagens, temperature=0, **extra
            ), None
        except Exception as e:
            ultimo_erro = f"{type(e).__name__}: {e}"
    return None, ultimo_erro



def analisar_cliente(resumo_inicial: dict, usar_cache: bool = True) -> dict:
    """Roda o agente sobre um cliente e devolve parecer + métricas."""
    CACHE.mkdir(exist_ok=True)
    arquivo_cache = CACHE / f"{_chave_cache(resumo_inicial)}.json"
    if usar_cache and arquivo_cache.exists():
        registro = json.loads(arquivo_cache.read_text(encoding="utf-8"))
        registro["do_cache"] = True
        return registro

    inicio = time.perf_counter()
    mensagens = [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": json.dumps(resumo_inicial, ensure_ascii=False)},
    ]

    ferramentas_chamadas = []
    tokens_prompt = tokens_resposta = 0
    rodadas = 0

    for _ in range(MAX_RODADAS):
        rodadas += 1
        resp = cliente_llm.chat.completions.create(
            model=MODELO,
            messages=mensagens,
            tools=FERRAMENTAS,
            tool_choice="auto",
            temperature=0,
            max_tokens=3000,
        )
        tokens_prompt += resp.usage.prompt_tokens
        tokens_resposta += resp.usage.completion_tokens

        msg = resp.choices[0].message
        mensagens.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            break

        for chamada in msg.tool_calls:
            nome = chamada.function.name
            args = json.loads(chamada.function.arguments)
            ferramentas_chamadas.append({"ferramenta": nome, "argumentos": args})
            try:
                resultado = EXECUTORES[nome](**args)
            except Exception as e:
                resultado = {"erro": f"{type(e).__name__}: {e}"}
            mensagens.append({
                "role": "tool",
                "tool_call_id": chamada.id,
                "content": json.dumps(resultado, ensure_ascii=False),
            })

        # Fase 2 — parecer estruturado
    mensagens.append({"role": "user", "content": PROMPT_PARECER})
    resp, erro_api = _chamar_parecer(mensagens)

    bruto = ""
    if resp is not None:
        tokens_prompt += resp.usage.prompt_tokens
        tokens_resposta += resp.usage.completion_tokens
        bruto = resp.choices[0].message.content or ""

    registro = {
        "cliente_id": resumo_inicial["cliente_id"],
        "modelo": MODELO,
        "ferramentas_chamadas": ferramentas_chamadas,
        "qtd_ferramentas": len(ferramentas_chamadas),
        "rodadas_investigacao": rodadas,
        "latencia_s": round(time.perf_counter() - inicio, 2),
        "tokens_prompt": tokens_prompt,
        "tokens_resposta": tokens_resposta,
        "tokens_total": tokens_prompt + tokens_resposta,
        "resposta_bruta": bruto,
        "parecer": None,
        "erro": erro_api,
        "do_cache": False,
    }

    if erro_api is None:
        try:
            registro["parecer"] = Parecer.model_validate_json(bruto).model_dump()
        except ValidationError as e:
            registro["erro"] = f"ValidationError: {e.error_count()} problema(s)"
        except Exception as e:
            registro["erro"] = f"{type(e).__name__}: {e}"

    arquivo_cache.write_text(
        json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return registro

def montar_resumo(df: pd.DataFrame, cliente_id: str) -> dict:
    """Resumo inicial de um cliente — tudo calculado em pandas."""
    ops = df[df["cliente_id"] == cliente_id]
    sinalizadas = ops[ops["flag_fracionamento"] | ops["flag_valor_atipico"]]
    dias_fracionamento = sorted(
        d.strftime("%Y-%m-%d")
        for d in ops.loc[ops["flag_fracionamento"], "data"].dropna().unique()
    )
    return {
        "cliente_id": cliente_id,
        "total_operacoes": int(len(ops)),
        "volume_total_brl": round(float(ops["valor_brl"].sum()), 2),
        "ticket_mediano_brl": round(float(ops["valor_brl"].median()), 2),
        "regras_acionadas": {
            "fracionamento": bool(ops["flag_fracionamento"].any()),
            "valor_atipico": bool(ops["flag_valor_atipico"].any()),
        },
        "qtd_operacoes_sinalizadas": int(len(sinalizadas)),
        "dias_com_fracionamento": dias_fracionamento,
    }


if __name__ == "__main__":
    df, _, _, _ = preparar("../dados/dados_nivel_2.json")
    tools.usar_base(df)

    top10 = top_clientes(df)
    resultados = []

    for i, cliente_id in enumerate(top10["cliente_id"], start=1):
        print(f"[{i}/10] {cliente_id}...", end=" ", flush=True)
        registro = analisar_cliente(montar_resumo(df, cliente_id))
        resultados.append(registro)
        marca = "cache" if registro["do_cache"] else f"{registro['latencia_s']}s"
        ferr = ", ".join(f["ferramenta"] for f in registro["ferramentas_chamadas"]) or "nenhuma"
        status = registro["erro"] or (registro["parecer"] or {}).get("nivel_risco", "?")

        print(f"{marca} | {status} | ferramentas: {ferr}")

    Path("../outputs").mkdir(exist_ok=True)
    with open("../outputs/pareceres.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    metricas = pd.DataFrame([
        {
            "cliente_id": r["cliente_id"],
            "nivel_risco": (r["parecer"] or {}).get("nivel_risco"),
            "validou": r["erro"] is None,
            "qtd_ferramentas": r["qtd_ferramentas"],
            "ferramentas": ", ".join(f["ferramenta"] for f in r["ferramentas_chamadas"]),
            "rodadas": r["rodadas_investigacao"],
            "latencia_s": r["latencia_s"],
            "tokens_prompt": r["tokens_prompt"],
            "tokens_resposta": r["tokens_resposta"],
            "tokens_total": r["tokens_total"],
        }
        for r in resultados
    ])
    metricas.to_csv("../outputs/metricas_lote.csv", index=False)

    print("\nMetricas do lote")
    print(metricas.to_string(index=False))
    print(f"\nTokens totais:    {metricas['tokens_total'].sum()}")
    print(f"Latencia total:   {metricas['latencia_s'].sum():.1f}s")
    print(f"Latencia media:   {metricas['latencia_s'].mean():.2f}s")
    print(f"Ferramentas/caso: {metricas['qtd_ferramentas'].mean():.1f}")
    print("\n=== Ferramentas por caso (evidencia de decisao) ===")
    print(metricas[["cliente_id", "ferramentas"]].to_string(index=False))

"""Fluxo multiagente de triagem de PLD (Nível 3, trilha A).

Três papéis encadeados sobre um estado compartilhado:

  Triador       decide se o caso merece investigação, com que prioridade e o que
                o Investigador deve olhar. É a condição de parada do fluxo.
  Investigador  consulta as ferramentas do Nível 2 conforme os focos recebidos.
  Redator       produz o parecer final estruturado.

O estado é um dicionário único que atravessa os três papéis, acumulando o que
cada um produziu. Um caso arquivado pelo Triador não chega ao Investigador nem ao
Redator — o custo das duas etapas seguintes é economizado.
"""

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "nivel_2"))

import tools  
from agente import (  
    EXECUTORES,
    FERRAMENTAS,
    MODELO,
    Parecer,
    cliente_llm,
    montar_resumo,
)
from pipeline import preparar, top_clientes  
 

MAX_RODADAS = 4
CACHE = Path(__file__).resolve().parent.parent / ".cache_fluxo"


class Triagem(BaseModel):
    prosseguir: bool
    prioridade: Literal["baixa", "media", "alta"]
    motivo: str
    focos: list[str]


PROMPT_TRIADOR = """Você é o Triador de uma mesa de PLD. Recebe o resultado da triagem automática de um cliente e decide se o caso merece investigação aprofundada por um analista.

Os números já vêm calculados por regras determinísticas — não recalcule nada.

Decida:
- prosseguir: true se o caso justifica investigação, false se pode ser arquivado
- prioridade: "baixa", "media" ou "alta"
- motivo: uma frase explicando a decisão
- focos: o que o investigador deve examinar (ex: "detalhe do dia 2026-03-08",
  "distribuição por canal"). Lista vazia se prosseguir for false.

Seja seletivo: arquivar casos fracos é parte do trabalho, porque tempo de analista
é o recurso escasso.

Responda APENAS com JSON:
{"prosseguir": true, "prioridade": "alta", "motivo": "...", "focos": ["..."]}"""

PROMPT_INVESTIGADOR = """Você é o Investigador de uma mesa de PLD. O Triador encaminhou este caso e indicou o que examinar.

Use as ferramentas disponíveis para levantar apenas o que os focos indicam. Não
chame ferramenta que não sirva aos focos recebidos.

Ao terminar, escreva em texto corrido (sem JSON) o que você encontrou: os fatos
observados, sem julgamento de risco. Quem classifica o risco é o Redator."""

PROMPT_REDATOR = """Você é o Redator de pareceres de PLD. Recebe a triagem inicial e os achados do Investigador, e produz o parecer final.

Responda APENAS com JSON:

{
  "nivel_risco": "baixo" | "medio" | "alto",
  "tipologia_suspeita": "<tipologia de PLD, ou 'nenhuma identificada'>",
  "red_flags": ["<indício objetivo presente nos achados>"],
  "justificativa": "<2 a 4 frases ligando os indícios à tipologia>"
}

Use exatamente "baixo", "medio" ou "alto", sem acento. Não invente informação que
não esteja na triagem ou nos achados."""


def _chamar(mensagens, **extra):
    """Chamada à API com fallback: tenta modo JSON, depois sem ele."""
    variantes = [extra, {k: v for k, v in extra.items() if k != "response_format"}]
    erro = None
    for v in variantes:
        try:
            return cliente_llm.chat.completions.create(
                model=MODELO, messages=mensagens, temperature=0, max_tokens=3000, **v
            ), None
        except Exception as e:
            erro = f"{type(e).__name__}: {e}"
    return None, erro


def triador(estado):
    """Decide se o caso segue. É a condição de parada do fluxo."""
    resp, erro = _chamar(
        [
            {"role": "system", "content": PROMPT_TRIADOR},
            {"role": "user", "content": json.dumps(estado["resumo"], ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    if erro:
        estado["erro"] = erro
        return estado

    estado["tokens"] += resp.usage.total_tokens
    try:
        estado["triagem"] = Triagem.model_validate_json(
            resp.choices[0].message.content or ""
        ).model_dump()
    except ValidationError as e:
        estado["erro"] = f"Triador ValidationError: {e.error_count()}"
    return estado


def investigador(estado):
    """Consulta as ferramentas conforme os focos definidos pelo Triador."""
    contexto = {
        "resumo": estado["resumo"],
        "focos_do_triador": estado["triagem"]["focos"],
        "prioridade": estado["triagem"]["prioridade"],
    }
    mensagens = [
        {"role": "system", "content": PROMPT_INVESTIGADOR},
        {"role": "user", "content": json.dumps(contexto, ensure_ascii=False)},
    ]

    for _ in range(MAX_RODADAS):
        resp, erro = _chamar(mensagens, tools=FERRAMENTAS, tool_choice="auto")
        if erro:
            estado["erro"] = erro
            return estado
        estado["tokens"] += resp.usage.total_tokens

        msg = resp.choices[0].message
        mensagens.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            estado["investigacao"]["achados"] = msg.content or ""
            break

        for chamada in msg.tool_calls:
            nome = chamada.function.name
            args = json.loads(chamada.function.arguments)
            estado["investigacao"]["ferramentas"].append(nome)
            try:
                resultado = EXECUTORES[nome](**args)
            except Exception as e:
                resultado = {"erro": f"{type(e).__name__}: {e}"}
            mensagens.append({
                "role": "tool",
                "tool_call_id": chamada.id,
                "content": json.dumps(resultado, ensure_ascii=False),
            })

    return estado


def redator(estado):
    """Produz o parecer final a partir da triagem e dos achados."""
    contexto = {
        "resumo": estado["resumo"],
        "triagem": estado["triagem"],
        "achados_do_investigador": estado["investigacao"]["achados"],
    }
    resp, erro = _chamar(
        [
            {"role": "system", "content": PROMPT_REDATOR},
            {"role": "user", "content": json.dumps(contexto, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    if erro:
        estado["erro"] = erro
        return estado

    estado["tokens"] += resp.usage.total_tokens
    try:
        estado["parecer"] = Parecer.model_validate_json(
            resp.choices[0].message.content or ""
        ).model_dump()
    except ValidationError as e:
        estado["erro"] = f"Redator ValidationError: {e.error_count()}"
    return estado


def executar_fluxo(df, cliente_id, usar_cache=True):
    """Roda os três papéis sobre um estado compartilhado."""
    CACHE.mkdir(exist_ok=True)
    chave = hashlib.sha256(f"{MODELO}|{cliente_id}".encode()).hexdigest()[:16]
    arquivo = CACHE / f"{chave}.json"
    if usar_cache and arquivo.exists():
        estado = json.loads(arquivo.read_text(encoding="utf-8"))
        estado["do_cache"] = True
        return estado

    inicio = time.perf_counter()
    estado = {
        "cliente_id": cliente_id,
        "modelo": MODELO,
        "resumo": montar_resumo(df, cliente_id),
        "triagem": None,
        "investigacao": {"ferramentas": [], "achados": ""},
        "parecer": None,
        "encerrado_em": None,
        "tokens": 0,
        "erro": None,
        "do_cache": False,
    }

    estado = triador(estado)

    if estado["erro"]:
        estado["encerrado_em"] = "erro"
    elif not estado["triagem"]["prosseguir"]:
        estado["encerrado_em"] = "triador"

    else:
        estado = investigador(estado)
        if not estado["erro"]:
            estado = redator(estado)
        estado["encerrado_em"] = "redator"

    estado["latencia_s"] = round(time.perf_counter() - inicio, 2)
    if estado["erro"] is None:
        arquivo.write_text(
            json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return estado



if __name__ == "__main__":
    df, _, _, _ = preparar("../dados/dados_nivel_2.json")
    tools.usar_base(df)

    resultados = []
    for i, cliente_id in enumerate(top_clientes(df)["cliente_id"], start=1):
        print(f"[{i}/10] {cliente_id}...", end=" ", flush=True)
        estado = executar_fluxo(df, cliente_id)
        resultados.append(estado)

        marca = "cache" if estado["do_cache"] else f"{estado['latencia_s']}s"
        if estado["erro"]:
            print(f"{marca} | ERRO: {estado['erro'][:60]}")
        elif estado["encerrado_em"] == "triador":
            print(f"{marca} | ARQUIVADO pelo triador: {estado['triagem']['motivo'][:50]}")
        else:
            print(
                f"{marca} | {estado['parecer']['nivel_risco']} "
                f"| prioridade {estado['triagem']['prioridade']} "
                f"| ferramentas: {', '.join(estado['investigacao']['ferramentas']) or 'nenhuma'}"
            )

    saida = Path("../outputs")
    saida.mkdir(exist_ok=True)
    with open(saida / "fluxo_multiagente.json", "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    resumo = pd.DataFrame([
        {
            "cliente_id": e["cliente_id"],
            "prosseguiu": (e["triagem"] or {}).get("prosseguir"),
            "prioridade": (e["triagem"] or {}).get("prioridade"),
            "encerrado_em": e["encerrado_em"],
            "ferramentas": ", ".join(e["investigacao"]["ferramentas"]),
            "nivel_risco": (e["parecer"] or {}).get("nivel_risco"),
            "tokens": e["tokens"],
            "latencia_s": e["latencia_s"],
        }
        for e in resultados
    ])
    resumo.to_csv(saida / "fluxo_multiagente.csv", index=False)

    print("\n=== Resumo do fluxo ===")
    print(resumo.to_string(index=False))
    arquivados = (resumo["encerrado_em"] == "triador").sum()
    print(f"\nArquivados pelo triador: {arquivados}/{len(resumo)}")
    print(f"Tokens totais: {resumo['tokens'].sum()}")

"""Ferramentas de consulta à base tratada, para uso pelo agente.

Cada função é uma consulta pura: recebe identificadores e devolve um dicionário
serializável em JSON. Nenhuma delas decide nada — a decisão de qual chamar é do
agente.

A base fica em estado de módulo porque o agente invoca estas funções passando
apenas os argumentos que o modelo produz (cliente_id, data). O DataFrame não
trafega pela interface de tool calling.
"""

import pandas as pd

_BASE = None


def usar_base(df):
    """Define a base sobre a qual as ferramentas operam."""
    global _BASE
    _BASE = df


def _ops(cliente_id):
    if _BASE is None:
        raise RuntimeError("Base nao carregada. Chame usar_base(df) antes.")
    return _BASE[_BASE["cliente_id"] == cliente_id]


def historico_cliente(cliente_id: str) -> dict:
    """Resumo agregado de todas as operações do cliente."""
    ops = _ops(cliente_id)
    if ops.empty:
        return {"erro": f"cliente {cliente_id} nao encontrado"}

    datas = ops["data"].dropna()
    return {
        "cliente_id": cliente_id,
        "total_operacoes": int(len(ops)),
        "volume_total_brl": round(float(ops["valor_brl"].sum()), 2),
        "ticket_medio_brl": round(float(ops["valor_brl"].mean()), 2),
        "ticket_mediano_brl": round(float(ops["valor_brl"].median()), 2),
        "maior_operacao_brl": round(float(ops["valor_brl"].max()), 2),
        "menor_operacao_brl": round(float(ops["valor_brl"].min()), 2),
        "periodo_inicio": datas.min().strftime("%d/%m/%Y") if not datas.empty else None,
        "periodo_fim": datas.max().strftime("%d/%m/%Y") if not datas.empty else None,
        "operacoes_sem_data": int(ops["data"].isna().sum()),
        "tipos": ops["tipo"].value_counts().to_dict(),
        "contrapartes_distintas": int(ops["contraparte"].nunique()),
        "regras_acionadas": {
            "fracionamento": bool(ops["flag_fracionamento"].any()),
            "valor_atipico": bool(ops["flag_valor_atipico"].any()),
        },
    }


def operacoes_do_dia(cliente_id: str, data: str) -> dict:
    """Recorte das operações de um cliente numa data específica (AAAA-MM-DD)."""
    alvo = pd.to_datetime(data, errors="coerce")
    if pd.isna(alvo):
        return {"erro": f"data invalida: {data}. Use o formato AAAA-MM-DD."}

    dia = _ops(cliente_id)
    dia = dia[dia["data"] == alvo]

    return {
        "cliente_id": cliente_id,
        "data": data,
        "qtd_operacoes": int(len(dia)),
        "soma_brl": round(float(dia["valor_brl"].sum()), 2),
        "maior_operacao_brl": (
            round(float(dia["valor_brl"].max()), 2) if len(dia) else 0.0
        ),
        "operacoes": [
            {
                "id": r["id"],
                "valor_brl": round(float(r["valor_brl"]), 2),
                "canal": r["canal"],
                "tipo": r["tipo"],
                "contraparte": r["contraparte"],
            }
            for _, r in dia.iterrows()
        ],
    }


def perfil_canal(cliente_id: str) -> dict:
    """Distribuição das operações do cliente por canal, em volume e quantidade."""
    ops = _ops(cliente_id)
    if ops.empty:
        return {"erro": f"cliente {cliente_id} nao encontrado"}

    por_canal = ops.groupby("canal")["valor_brl"].agg(["count", "sum"])
    total = float(ops["valor_brl"].sum())

    return {
        "cliente_id": cliente_id,
        "canais": {
            canal: {
                "operacoes": int(linha["count"]),
                "volume_brl": round(float(linha["sum"]), 2),
                "pct_volume": round(100 * float(linha["sum"]) / total, 1),
            }
            for canal, linha in por_canal.iterrows()
        },
        "canal_predominante": str(por_canal["sum"].idxmax()),
        "usa_especie": bool((ops["canal"] == "especie").any()),
    }


if __name__ == "__main__":
    import json

    from pipeline import preparar

    df, _, _, _ = preparar("../dados/dados_nivel_2.json")
    usar_base(df)

    print("historico_cliente('CLI-029')")
    print(json.dumps(historico_cliente("CLI-029"), indent=2, ensure_ascii=False))

    print("\nperfil_canal('CLI-029')")
    print(json.dumps(perfil_canal("CLI-029"), indent=2, ensure_ascii=False))

    print("\noperacoes_do_dia('CLI-029', dia com fracionamento)")
    dia = df[(df["cliente_id"] == "CLI-029") & df["flag_fracionamento"]]["data"].iloc[0]
    print(json.dumps(
        operacoes_do_dia("CLI-029", dia.strftime("%Y-%m-%d")),
        indent=2,
        ensure_ascii=False,
    ))

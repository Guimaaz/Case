"""Confronto entre o risco atribuído pelo agente e o apontado pelas regras.

Critério de correspondência: o nível esperado deriva de quantas regras
determinísticas o cliente acionou — duas regras -> alto, uma -> medio,
nenhuma -> baixo. É um critério deliberadamente simples, espelhando a
simplicidade das próprias regras; o valor da análise está nas divergências.
"""

import json

import pandas as pd

from pipeline import preparar

ESPERADO_POR_REGRAS = {0: "baixo", 1: "medio", 2: "alto"}
ORDEM = {"baixo": 0, "medio": 1, "alto": 2}


def risco_esperado(ops: pd.DataFrame) -> tuple[str, int]:
    """Nível esperado a partir de quantas regras o cliente acionou."""
    regras = int(ops["flag_fracionamento"].any()) + int(ops["flag_valor_atipico"].any())
    return ESPERADO_POR_REGRAS[regras], regras


def montar_confronto(df: pd.DataFrame, pareceres: list[dict]) -> pd.DataFrame:
    linhas = []
    for r in pareceres:
        cid = r["cliente_id"]
        ops = df[df["cliente_id"] == cid]
        esperado, qtd_regras = risco_esperado(ops)
        atribuido = (r["parecer"] or {}).get("nivel_risco")

        if atribuido is None:
            direcao = "sem parecer"
        elif esperado == atribuido:
            direcao = "igual"
        elif ORDEM[atribuido] > ORDEM[esperado]:
            direcao = "agente escalou"
        else:
            direcao = "agente atenuou"

        linhas.append({
            "cliente_id": cid,
            "regras_acionadas": qtd_regras,
            "fracionamento": bool(ops["flag_fracionamento"].any()),
            "valor_atipico": bool(ops["flag_valor_atipico"].any()),
            "risco_esperado": esperado,
            "risco_agente": atribuido,
            "concorda": esperado == atribuido,
            "direcao": direcao,
            "tipologia": (r["parecer"] or {}).get("tipologia_suspeita"),
            "qtd_red_flags": len((r["parecer"] or {}).get("red_flags", [])),
            "ferramentas": ", ".join(f["ferramenta"] for f in r["ferramentas_chamadas"]),
            "justificativa": (r["parecer"] or {}).get("justificativa"),
        })
    return pd.DataFrame(linhas)


if __name__ == "__main__":
    df, _, _, _ = preparar("../dados/dados_nivel_2.json")
    with open("../outputs/pareceres.json", encoding="utf-8") as f:
        pareceres = json.load(f)

    conf = montar_confronto(df, pareceres)
    conf.to_csv("../outputs/confronto.csv", index=False)

    print("Confronto regra x agente")
    print(conf[[
        "cliente_id", "regras_acionadas", "risco_esperado",
        "risco_agente", "concorda", "direcao",
    ]].to_string(index=False))

    taxa = 100 * conf["concorda"].mean()
    print(f"\nTaxa de concordancia: {taxa:.0f}% ({conf['concorda'].sum()}/{len(conf)})")
    print("\nDirecao das divergencias:")
    print(conf["direcao"].value_counts().to_string())

    divergentes = conf[~conf["concorda"]]
    if len(divergentes):
        print("\nDivergencias em detalhe")
        for _, r in divergentes.iterrows():
            print(f"\n--- {r['cliente_id']} ---")
            print(f"regras acionadas: {r['regras_acionadas']} -> esperado '{r['risco_esperado']}'")
            print(f"agente: '{r['risco_agente']}' ({r['direcao']})")
            print(f"tipologia: {r['tipologia']}")
            print(f"ferramentas consultadas: {r['ferramentas'] or 'nenhuma'}")
            print(f"justificativa: {r['justificativa']}")

    print("\nSalvo em outputs/confronto.csv")

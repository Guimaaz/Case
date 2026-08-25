"""Tratamento e regras determinísticas de triagem de PLD.

Mesma lógica do notebook do Nível 1, extraída em funções puras para ser
reaproveitada sobre qualquer base com a mesma estrutura de campos.
"""

import json

import pandas as pd

LIMITE_SOMA_DIARIA = 50_000.00
LIMITE_OPERACAO_ISOLADA = 20_000.00
MIN_OPERACOES_DIA = 3
MULTIPLICADOR_MEDIANA = 5
MIN_OPERACOES_CLIENTE = 4

def carregar(caminho):
    """Lê o JSON e devolve (DataFrame de operações, taxa de câmbio)."""
    with open(caminho, encoding="utf-8") as f:
        bruto = json.load(f)
    return pd.DataFrame(bruto["operacoes"]), bruto["taxa_cambio_usd_brl"]

def limpar(df):
    """Remove linhas idênticas e converte a coluna de data para datetime."""
    df = df.drop_duplicates().copy()
    df["data"] = pd.to_datetime(df["data"], errors="coerce")
    return df.reset_index(drop=True)


def normalizar_brl(df, taxa_usd_brl):
    """Cria valor_brl com tudo em reais, preservando a coluna valor original."""
    df = df.copy()
    df["valor_brl"] = df["valor"].astype(float)
    df.loc[df["moeda"] == "USD", "valor_brl"] = df["valor"] * taxa_usd_brl
    return df

def regra_fracionamento(df):
    """Sinaliza grupos (cliente, data) com 3+ operações, soma > 50k e nenhuma >= 20k."""
    resumo = (
        df.groupby(["cliente_id", "data"])["valor_brl"]
          .agg(qtd_operacoes="count", soma_dia="sum", maior_operacao="max")
          .reset_index()
    )
    resumo["flag_fracionamento"] = (
        (resumo["qtd_operacoes"] >= MIN_OPERACOES_DIA)
        & (resumo["soma_dia"] > LIMITE_SOMA_DIARIA)
        & (resumo["maior_operacao"] < LIMITE_OPERACAO_ISOLADA)
    )
    df = df.merge(
        resumo[["cliente_id", "data", "flag_fracionamento"]],
        on=["cliente_id", "data"],
        how="left",
    )
    df["flag_fracionamento"] = (
        df["flag_fracionamento"].astype("boolean").fillna(False).astype(bool)
    )
    return df, resumo

def regra_valor_atipico(df):
    """Sinaliza operações acima de 5x a mediana do cliente (clientes com 4+ operações)."""
    perfil = (
        df.groupby("cliente_id")["valor_brl"]
          .agg(qtd_operacoes_cliente="count", mediana_cliente="median")
          .reset_index()
    )
    df = df.merge(perfil, on="cliente_id", how="left")
    df["flag_valor_atipico"] = (
        (df["qtd_operacoes_cliente"] >= MIN_OPERACOES_CLIENTE)
        & (df["valor_brl"] > MULTIPLICADOR_MEDIANA * df["mediana_cliente"])
    )
    return df, perfil

def preparar(caminho):
    """Pipeline completo: carrega, limpa, normaliza e aplica as duas regras."""
    df, taxa = carregar(caminho)
    df = limpar(df)
    df = normalizar_brl(df, taxa)
    df, resumo_diario = regra_fracionamento(df)
    df, perfil_cliente = regra_valor_atipico(df)
    return df, taxa, resumo_diario, perfil_cliente

def top_clientes(df, n=10):
    """Clientes mais sinalizados; desempate por volume total."""
    df = df.copy()
    df["sinalizacoes"] = (
        df["flag_fracionamento"].astype(int) + df["flag_valor_atipico"].astype(int)
    )
    ranking = (
        df.groupby("cliente_id")
          .agg(
              sinalizacoes=("sinalizacoes", "sum"),
              volume_total_brl=("valor_brl", "sum"),
              qtd_operacoes=("id", "count"),
              fracionamento=("flag_fracionamento", "any"),
              valor_atipico=("flag_valor_atipico", "any"),
          )
          .reset_index()
          .sort_values(["sinalizacoes", "volume_total_brl"], ascending=[False, False])
          .head(n)
          .reset_index(drop=True)
    )
    ranking["volume_total_brl"] = ranking["volume_total_brl"].round(2)
    return ranking

if __name__ == "__main__":
    CAMINHO = "../dados/dados_nivel_2.json"

    df, taxa, resumo_diario, perfil_cliente = preparar(CAMINHO)

    print(f"Operações após limpeza: {len(df)}")
    print(f"Clientes: {df['cliente_id'].nunique()}")
    print(f"Operações sem data: {df['data'].isna().sum()}")
    print(f"Convertidas de USD: {(df['moeda'] == 'USD').sum()}")
    print(f"Sinalizadas por fracionamento: {df['flag_fracionamento'].sum()}")
    print(f"Sinalizadas por valor atípico: {df['flag_valor_atipico'].sum()}")

    top10 = top_clientes(df)
    print("\n=== Top 10 clientes mais sinalizados ===")
    print(top10.to_string(index=False))

    top10.to_csv("../outputs/top10_clientes.csv", index=False)
    print("\nSalvo em outputs/top10_clientes.csv")

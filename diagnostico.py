"""Checagem rápida de todas as fontes externas.

    python diagnostico.py

Use quando o boletim sair estranho: mostra, fonte por fonte, o que respondeu
e o que caiu — inclusive se o provedor de IA está bloqueado pela rede.
"""

import logging
import sys

logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(message)s")

from src import config
from src.coletores import bcb, mercado, noticias


def fmt(x, sufixo="%"):
    return f"{x:+7.2f}{sufixo}" if x is not None else "    n/d"


def main():
    falhas = 0

    print("=" * 72)
    print("1. BANCO CENTRAL (API SGS)")
    print("=" * 72)
    macro = bcb.coletar()
    for chave in config.SERIES_BCB:
        d = macro.get(chave)
        if d:
            # Taxa varia em pontos percentuais; cotação, em porcentagem.
            delta = (fmt(d["var_dia_abs"], " p.p.") if d["tipo"] == "taxa"
                     else fmt(d["var_dia_pct"]))
            print(f"  ok    {d['nome_pt']:24} {d['valor']:>11.4f} {d['unidade']:7}"
                  f" dia={delta:>12}  ({d['data']})")
        else:
            print(f"  FALHA {chave}")
            falhas += 1

    print()
    print("=" * 72)
    print("2. COMMODITIES (Yahoo Finance)")
    print("=" * 72)
    cot = mercado.coletar()
    for ticker in config.COMMODITIES:
        d = cot.get(ticker)
        if d:
            print(f"  ok    {d['nome_pt']:18} {d['valor']:>10.2f} {d['unidade_pt']:12}"
                  f" dia={fmt(d['var_dia_pct'])} sem={fmt(d['var_semana_pct'])}"
                  f" mes={fmt(d['var_mes_pct'])}")
        else:
            print(f"  FALHA {ticker}")
            falhas += 1

    print()
    print("=" * 72)
    print("3. NOTÍCIAS (RSS)")
    print("=" * 72)
    news = noticias.coletar()
    for n in news[:10]:
        marca = "novo" if n["recente"] else "    "
        print(f"  {marca}  [{n['fonte']:18}] {n['titulo'][:58]}")
    if not news:
        print("  FALHA nenhuma notícia relevante")
        falhas += 1

    print()
    print("=" * 72)
    print("4. PROVEDOR DE IA")
    print("=" * 72)
    from src import ia

    provedor = ia.provedor_configurado()
    print(f"  configurado: {provedor}")
    estado, detalhe = ia.testar_conexao()
    print(f"  {'ok   ' if estado else 'FALHA'} {detalhe}")
    if not estado:
        print("  -> o boletim ainda será gerado, em modo degradado (sem narrativa).")

    print()
    print("=" * 72)
    print(f"RESUMO: macro {len(macro)}/{len(config.SERIES_BCB)} | "
          f"commodities {len(cot)}/{len(config.COMMODITIES)} | "
          f"notícias {len(news)} | falhas críticas: {falhas}")
    print("=" * 72)

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())

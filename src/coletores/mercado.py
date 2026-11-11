"""Cotações de commodities pelo endpoint chart do Yahoo Finance.

Usamos `requests` direto em vez da biblioteca `yfinance` por dois motivos:
o yfinance fala por `curl_cffi`, que ignora o repositório de certificados do
sistema e por isso quebra atrás de proxy com inspeção TLS; e o endpoint é um
JSON simples, que não justifica a dependência.

  https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=3mo&interval=1d
"""

import logging
from datetime import datetime, timezone

from .. import config, rede

log = logging.getLogger(__name__)

HOSTS = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{t}",
    "https://query2.finance.yahoo.com/v8/finance/chart/{t}",
)

# Quantos pregões atrás usamos como base de cada comparação.
PASSO_SEMANA = 5
PASSO_MES = 22


def _variacao(atual, base):
    if base in (None, 0):
        return None
    return (atual / base - 1) * 100


def _base(valores, passo):
    return valores[-(passo + 1)] if len(valores) > passo else None


def _extrair(payload):
    """Puxa (datas, fechamentos) do JSON do Yahoo, descartando buracos.

    Pregões sem negócio vêm como `null` no array de fechamento; se não forem
    removidos em par com os timestamps, as séries saem desalinhadas.
    """
    resultado = payload["chart"]["result"][0]
    timestamps = resultado.get("timestamp") or []
    fechamentos = resultado["indicators"]["quote"][0].get("close") or []

    pontos = [
        (datetime.fromtimestamp(ts, tz=timezone.utc).date(), float(c))
        for ts, c in zip(timestamps, fechamentos)
        if c is not None
    ]
    return pontos, resultado.get("meta", {})


def coletar_ticker(ticker, meta_cfg):
    """Coleta um ativo. Tenta query1 e, se falhar, query2."""
    ultimo_erro = None

    for molde in HOSTS:
        try:
            payload = rede.buscar_json(
                molde.format(t=ticker),
                params={"range": "3mo", "interval": "1d"},
            )
            pontos, meta_yahoo = _extrair(payload)
            if len(pontos) < 2:
                raise ValueError("menos de dois pregões na série")

            datas = [p[0] for p in pontos]
            valores = [p[1] for p in pontos]
            atual, anterior = valores[-1], valores[-2]

            return {
                "ticker": ticker,
                "nome_pt": meta_cfg["nome_pt"],
                "nome_en": meta_cfg["nome_en"],
                "unidade_pt": meta_cfg["unidade_pt"],
                "unidade_en": meta_cfg["unidade_en"],
                "grupo": meta_cfg["grupo"],
                "moeda": meta_yahoo.get("currency", ""),
                "valor": atual,
                "data": datas[-1],
                "anterior": anterior,
                "var_dia_pct": _variacao(atual, anterior),
                "var_semana_pct": _variacao(atual, _base(valores, PASSO_SEMANA)),
                "var_mes_pct": _variacao(atual, _base(valores, PASSO_MES)),
                "serie": pontos[-60:],
            }
        except Exception as e:
            ultimo_erro = e
            log.debug("%s falhou em %s: %s", ticker, molde.split("/")[2], e)

    raise ultimo_erro


def coletar():
    """Coleta todas as commodities. Um ativo fora do ar não derruba o boletim."""
    resultado, falhas = {}, []

    for ticker, meta_cfg in config.COMMODITIES.items():
        try:
            resultado[ticker] = coletar_ticker(ticker, meta_cfg)
            d = resultado[ticker]
            log.info("mercado %s (%s) = %.2f (%+.2f%%)", ticker, d["nome_pt"],
                     d["valor"], d["var_dia_pct"] or 0)
        except Exception as e:
            falhas.append(ticker)
            log.error("mercado %s falhou: %s: %s", ticker, type(e).__name__, e)

    if falhas:
        log.warning("cotações indisponíveis: %s", ", ".join(falhas))

    return resultado

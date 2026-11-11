"""Indicadores macro via API SGS do Banco Central (pública, sem chave).

    https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
    Resposta: [{"data": "10/11/2026", "valor": "5.5840"}, ...]

Consultamos por intervalo de datas em vez de `/ultimos/N`: esse segundo
endpoint responde 400 acima de ~20 pontos em séries diárias como a do dólar,
embora a própria mensagem de erro anuncie aceitar até 99.
"""

import logging
from datetime import date, datetime, timedelta

from .. import config, rede

log = logging.getLogger(__name__)

URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"


def _parse(registros):
    """Converte a resposta crua em [(date, float)], ordenada e sem datas futuras.

    A série da meta Selic traz a vigência adiante — a meta vale até a próxima
    reunião do Copom —, então descartar o futuro é o que dá o valor de hoje.
    """
    hoje = date.today()
    pontos = []
    for r in registros:
        try:
            d = datetime.strptime(r["data"], "%d/%m/%Y").date()
            v = float(str(r["valor"]).replace(",", "."))
        except (KeyError, ValueError, TypeError):
            continue
        if d <= hoje:
            pontos.append((d, v))
    return sorted(pontos)


def _variacao_relativa(atual, base):
    """Variação percentual. Indefinida se a base for zero ou negativa."""
    if base is None or base <= 0:
        return None
    return (atual / base - 1) * 100


def coletar_serie(chave, meta):
    """Coleta uma série do BCB e devolve o indicador já com as variações."""
    mensal = meta["periodicidade"] == "mensal"
    dias = config.JANELA_BCB_MENSAL if mensal else config.JANELA_BCB_DIARIA
    fim = date.today()
    inicio = fim - timedelta(days=dias)

    registros = rede.buscar_json(
        URL.format(codigo=meta["codigo"]),
        params={
            "formato": "json",
            "dataInicial": inicio.strftime("%d/%m/%Y"),
            "dataFinal": fim.strftime("%d/%m/%Y"),
        },
    )
    pontos = _parse(registros)
    if not pontos:
        raise ValueError(f"série {chave} voltou vazia")

    datas = [p[0] for p in pontos]
    valores = [p[1] for p in pontos]

    atual = valores[-1]
    anterior = valores[-2] if len(valores) >= 2 else None
    passo_mes = 1 if mensal else 22
    base_mes = valores[-(passo_mes + 1)] if len(valores) > passo_mes else None

    eh_taxa = meta.get("tipo") == "taxa"
    indicador = {
        "chave": chave,
        "nome_pt": meta["nome_pt"],
        "nome_en": meta["nome_en"],
        "unidade": meta["unidade"],
        "casas": meta["casas"],
        "periodicidade": meta["periodicidade"],
        "tipo": meta.get("tipo", "nivel"),
        "valor": atual,
        "data": datas[-1],
        "anterior": anterior,
        "var_dia_abs": (atual - anterior) if anterior is not None else None,
        "var_mes_abs": (atual - base_mes) if base_mes is not None else None,
    }

    # Para uma taxa, "subiu 0,25 p.p." é a leitura correta; variação relativa
    # sobre percentual (ainda mais negativo) não tem significado econômico.
    if eh_taxa:
        indicador["var_dia_pct"] = None
        indicador["var_mes_pct"] = None
    else:
        indicador["var_dia_pct"] = _variacao_relativa(atual, anterior)
        indicador["var_mes_pct"] = _variacao_relativa(atual, base_mes)

    indicador["serie"] = pontos[-60:]
    return indicador


def coletar():
    """Coleta todos os indicadores macro. Falha em um não derruba os outros."""
    resultado, falhas = {}, []

    for chave, meta in config.SERIES_BCB.items():
        try:
            d = coletar_serie(chave, meta)
            resultado[chave] = d
            log.info("BCB %s = %.4f (%s)", chave, d["valor"], d["data"])
        except Exception as e:
            falhas.append(chave)
            log.error("BCB %s falhou: %s: %s", chave, type(e).__name__, e)

    if falhas:
        log.warning("indicadores macro indisponíveis: %s", ", ".join(falhas))

    return resultado

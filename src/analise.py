"""Monta o contexto do dia a partir dos dados crus.

Nada aqui chama rede nem IA: entra dado coletado, sai o pacote que alimenta
tanto o prompt quanto o site. Manter esta camada pura é o que permite
reproduzir um boletim antigo sem refazer as chamadas externas.
"""

import logging
from datetime import date

log = logging.getLogger(__name__)

# Variação diária a partir da qual o movimento merece ser chamado de destaque.
LIMIAR_DESTAQUE = 1.0
MAX_DESTAQUES = 5


def _ordenar_por_movimento(ativos):
    """Maiores variações do dia primeiro, medidas em valor absoluto."""
    com_variacao = [a for a in ativos if a.get("var_dia_pct") is not None]
    return sorted(com_variacao, key=lambda a: abs(a["var_dia_pct"]), reverse=True)


def destaques_do_dia(commodities):
    """Os ativos que mais se moveram, preferindo os que passaram do limiar.

    Se nenhum passou, devolvemos os três maiores mesmo assim: num dia calmo
    o boletim ainda precisa ter o que mostrar.
    """
    ordenados = _ordenar_por_movimento(list(commodities.values()))
    relevantes = [a for a in ordenados if abs(a["var_dia_pct"]) >= LIMIAR_DESTAQUE]
    return (relevantes or ordenados[:3])[:MAX_DESTAQUES]


def _data_referencia(macro, commodities):
    """A data mais recente entre as fontes — é a que o boletim carimba."""
    datas = [d["data"] for d in commodities.values() if d.get("data")]
    datas += [
        d["data"] for d in macro.values()
        if d.get("data") and d.get("periodicidade") == "diaria"
    ]
    return max(datas) if datas else date.today()


def resumir(macro, commodities, noticias):
    """Consolida tudo no contexto usado pela IA e pelo site."""
    ativos = list(commodities.values())
    com_variacao = [a for a in ativos if a.get("var_dia_pct") is not None]

    altas = [a for a in com_variacao if a["var_dia_pct"] > 0]
    baixas = [a for a in com_variacao if a["var_dia_pct"] < 0]
    estaveis = [a for a in com_variacao if a["var_dia_pct"] == 0]

    contexto = {
        "data_ref": _data_referencia(macro, commodities),
        "gerado_em": date.today(),
        "macro": macro,
        "commodities": commodities,
        "noticias": noticias,
        "destaques": destaques_do_dia(commodities),
        "placar": {
            "altas": len(altas),
            "baixas": len(baixas),
            "estaveis": len(estaveis),
            "total": len(ativos),
        },
        "cobertura": {
            "macro": f"{len(macro)}",
            "commodities": f"{len(commodities)}",
            "noticias": f"{len(noticias)}",
        },
    }

    maiores = _ordenar_por_movimento(ativos)
    contexto["maior_alta"] = next((a for a in maiores if a["var_dia_pct"] > 0), None)
    contexto["maior_baixa"] = next((a for a in maiores if a["var_dia_pct"] < 0), None)

    log.info(
        "contexto %s: %d altas, %d baixas, %d destaques",
        contexto["data_ref"], len(altas), len(baixas), len(contexto["destaques"]),
    )
    return contexto

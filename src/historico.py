"""Série temporal acumulada em CSV.

Cada execução acrescenta uma linha por ativo. Com o tempo isso vira um
dataset próprio — o mesmo robô que publica o boletim vai construindo a base
histórica que permite analisar os meses seguintes.

A escrita é idempotente por (data, chave): rodar duas vezes no mesmo dia
atualiza as linhas daquele dia em vez de duplicá-las, o que importa porque o
workflow pode ser disparado manualmente além do agendamento.
"""

import csv
import logging

from . import config

log = logging.getLogger(__name__)

COLUNAS = [
    "data",
    "categoria",
    "chave",
    "nome",
    "valor",
    "unidade",
    "var_dia_pct",
    "var_semana_pct",
    "var_mes_pct",
]


def _num(v, casas=4):
    return "" if v is None else f"{v:.{casas}f}"


def _linhas_do_contexto(contexto):
    data = contexto["data_ref"].isoformat()
    linhas = []

    for d in contexto["macro"].values():
        linhas.append({
            "data": data,
            "categoria": "macro",
            "chave": d["chave"],
            "nome": d["nome_pt"],
            "valor": _num(d["valor"], d["casas"]),
            "unidade": d["unidade"],
            "var_dia_pct": _num(d.get("var_dia_pct"), 4),
            "var_semana_pct": "",
            "var_mes_pct": _num(d.get("var_mes_pct"), 4),
        })

    for d in contexto["commodities"].values():
        linhas.append({
            "data": data,
            "categoria": d["grupo"],
            "chave": d["ticker"],
            "nome": d["nome_pt"],
            "valor": _num(d["valor"], 4),
            "unidade": d["unidade_pt"],
            "var_dia_pct": _num(d.get("var_dia_pct"), 4),
            "var_semana_pct": _num(d.get("var_semana_pct"), 4),
            "var_mes_pct": _num(d.get("var_mes_pct"), 4),
        })

    return linhas


def _ler():
    if not config.ARQ_HISTORICO.exists():
        return []
    with config.ARQ_HISTORICO.open("r", encoding="utf-8", newline="") as f:
        return [linha for linha in csv.DictReader(f) if linha.get("data")]


def registrar(contexto):
    """Grava o dia no histórico e devolve quantas linhas o arquivo tem agora."""
    config.DIR_DADOS.mkdir(parents=True, exist_ok=True)

    novas = _linhas_do_contexto(contexto)
    chaves_novas = {(l["data"], l["chave"]) for l in novas}

    mantidas = [
        l for l in _ler() if (l.get("data"), l.get("chave")) not in chaves_novas
    ]
    todas = mantidas + novas
    todas.sort(key=lambda l: (l["data"], l["categoria"], l["chave"]))

    with config.ARQ_HISTORICO.open("w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS)
        escritor.writeheader()
        # restringe cada linha às colunas conhecidas, caso o arquivo
        # tenha sido editado à mão com campos extras
        escritor.writerows({c: l.get(c, "") for c in COLUNAS} for l in todas)

    dias = len({l["data"] for l in todas})
    log.info("histórico: %d linhas em %d dias (%s)", len(todas), dias,
             config.ARQ_HISTORICO.name)
    return len(todas), dias


def serie(chave, limite=60):
    """Série [(data, valor)] de um ativo, do histórico acumulado."""
    pontos = []
    for linha in _ler():
        if linha.get("chave") != chave or not linha.get("valor"):
            continue
        try:
            pontos.append((linha["data"], float(linha["valor"])))
        except ValueError:
            continue
    return sorted(pontos)[-limite:]


def dias_registrados():
    return len({l["data"] for l in _ler()})

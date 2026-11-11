"""Ponto de entrada: coleta, analisa, narra e publica.

    python -m src.main [--sem-ia] [--verboso]

Degradação em vez de falha é a regra do pipeline: uma fonte fora do ar reduz
o boletim, não o cancela. Só a ausência total de dados de mercado interrompe
a execução, porque aí não haveria boletim nenhum para publicar.
"""

import argparse
import logging
import os
import sys

from . import analise, historico, ia, site
from .coletores import bcb, mercado, noticias


def configurar_log(verboso):
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def executar(sem_ia=False):
    log = logging.getLogger("boletim")

    if sem_ia:
        os.environ["PROVEDOR_IA"] = "nenhum"

    log.info("--- coleta ---")
    dados_macro = bcb.coletar()
    dados_mercado = mercado.coletar()
    dados_noticias = noticias.coletar()

    if not dados_mercado and not dados_macro:
        log.error("nenhuma fonte de mercado respondeu — nada a publicar")
        return 1

    log.info("--- análise ---")
    contexto = analise.resumir(dados_macro, dados_mercado, dados_noticias)

    log.info("--- histórico ---")
    _, dias = historico.registrar(contexto)

    log.info("--- narrativa (%s) ---", ia.provedor_configurado())
    narrativas = {idioma: ia.gerar(contexto, idioma) for idioma in ("pt", "en")}

    log.info("--- publicação ---")
    caminhos = site.publicar(contexto, narrativas, dias_historico=dias)

    log.info("pronto: %s", " | ".join(c.name for c in caminhos))
    log.info("manchete: %s", narrativas["pt"].get("manchete", ""))
    return 0


def main():
    p = argparse.ArgumentParser(description="Gera o boletim diário.")
    p.add_argument("--sem-ia", action="store_true",
                   help="pula a IA e usa a narrativa determinística")
    p.add_argument("--verboso", action="store_true", help="log em nível DEBUG")
    args = p.parse_args()

    configurar_log(args.verboso)
    try:
        return executar(sem_ia=args.sem_ia)
    except Exception:
        logging.getLogger("boletim").exception("falha não tratada")
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Manchetes do setor via RSS.

Os feeds são baixados pela nossa sessão `requests` e só depois entregues ao
feedparser. Se deixássemos o feedparser buscar sozinho, ele usaria urllib,
que não passa pelo truststore — e quebraria atrás de proxy corporativo.

Só sobrevivem ao filtro as manchetes que citam algo que acompanhamos; sem
isso o boletim encheria de notícia de celebridade vinda do feed geral.
"""

import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import feedparser

from .. import config, rede

log = logging.getLogger(__name__)

JANELA_HORAS = 48


def _sem_acento(texto):
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_CHAVES = sorted({_sem_acento(p) for p in config.PALAVRAS_CHAVE})

# Palavra inteira, com plural em -s opcional. O \b é o que impede "milho" de
# casar dentro de "milhões" — sem ele, notícia de loteria entra no boletim.
# O -s? aceita "safras"/"portos" sem abrir margem para "milhões".
_PADRAO = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _CHAVES) + r")s?\b"
)


def _relevante(titulo, resumo):
    """Conjunto de temas citados no texto; vazio significa não publicável."""
    return set(_PADRAO.findall(_sem_acento(f"{titulo} {resumo}")))


def _data_entrada(entrada):
    for campo in ("published_parsed", "updated_parsed"):
        t = entrada.get(campo)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _limpar(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


def _chave_dedup(titulo):
    return re.sub(r"[^a-z0-9]+", "", _sem_acento(titulo))[:70]


def coletar_feed(feed_cfg):
    """Baixa e analisa um feed, devolvendo só as entradas relevantes."""
    resposta = rede.buscar(feed_cfg["url"])
    analisado = feedparser.parse(resposta.content)

    corte = datetime.now(timezone.utc) - timedelta(hours=JANELA_HORAS)
    itens = []

    for entrada in analisado.entries:
        titulo = _limpar(entrada.get("title", ""))
        if not titulo:
            continue

        resumo = _limpar(entrada.get("summary", ""))[:300]
        temas = _relevante(titulo, resumo)
        if not temas:
            continue

        publicado = _data_entrada(entrada)
        itens.append({
            "titulo": titulo,
            "resumo": resumo,
            "link": entrada.get("link", ""),
            "fonte": feed_cfg["nome"],
            "peso": feed_cfg["peso"],
            "publicado": publicado,
            "recente": publicado is not None and publicado >= corte,
            "temas": sorted(temas),
        })

    return itens


def coletar():
    """Junta todos os feeds, remove repetidas e ordena por relevância."""
    todas, falhas = [], []

    for feed_cfg in config.FEEDS:
        try:
            itens = coletar_feed(feed_cfg)
            todas.extend(itens)
            log.info("feed %s: %d relevantes", feed_cfg["nome"], len(itens))
        except Exception as e:
            falhas.append(feed_cfg["nome"])
            log.error("feed %s falhou: %s: %s", feed_cfg["nome"], type(e).__name__, e)

    if falhas:
        log.warning("feeds indisponíveis: %s", ", ".join(falhas))

    vistas, unicas = set(), []
    for item in todas:
        chave = _chave_dedup(item["titulo"])
        if chave and chave not in vistas:
            vistas.add(chave)
            unicas.append(item)

    # Recentes primeiro; depois feed mais especializado; depois mais nova.
    unicas.sort(
        key=lambda n: (
            n["recente"],
            n["peso"],
            n["publicado"] or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    log.info("notícias: %d coletadas, %d após deduplicação", len(todas), len(unicas))
    return unicas[: config.MAX_NOTICIAS]

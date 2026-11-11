"""Camada de rede: uma sessão HTTP que sobrevive a proxy corporativo.

Em rede com inspeção TLS (o caso de muitas empresas), o Python rejeita o
certificado do proxy porque ele não está no bundle do `certifi`. O
`truststore` resolve isso mandando o Python usar o repositório de
certificados do próprio sistema operacional — onde o CA corporativo já
está instalado.

No GitHub Actions não há proxy nenhum e o truststore simplesmente não
atrapalha, então o mesmo código serve nos dois ambientes.
"""

import logging
import time

log = logging.getLogger(__name__)

try:
    import truststore

    truststore.inject_into_ssl()
    _TRUSTSTORE = True
except Exception:  # pragma: no cover - ambiente sem truststore
    _TRUSTSTORE = False

import requests

from . import config

_sessao = None


def sessao() -> requests.Session:
    """Devolve a sessão HTTP compartilhada (criada na primeira chamada)."""
    global _sessao
    if _sessao is None:
        s = requests.Session()
        s.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "*/*",
            # Proxies corporativos cacheiam agressivamente e chegam a
            # responder 304 para estas APIs. Num boletim diário isso
            # significaria publicar a cotação de ontem como se fosse de hoje.
            "Cache-Control": "no-cache, no-store, max-age=0",
            "Pragma": "no-cache",
        })
        _sessao = s
        log.debug("sessão criada (truststore=%s)", _TRUSTSTORE)
    return _sessao


def buscar(url, params=None, headers=None, timeout=None):
    """GET com retentativa e backoff. Devolve a Response ou levanta a exceção.

    Erros de rede e respostas 5xx/429 são retentados; 4xx não, porque
    repetir um pedido malformado não muda o resultado.
    """
    timeout = timeout or config.TIMEOUT
    ultimo_erro = None

    for tentativa in range(1, config.TENTATIVAS + 1):
        try:
            r = sessao().get(url, params=params, headers=headers, timeout=timeout)
            # 304 vem de cache intermediário e traz corpo vazio; raise_for_status
            # não o considera erro, mas para nós é uma resposta inútil.
            if r.status_code in (304, 429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            resposta = getattr(e, "response", None)
            if resposta is not None and resposta.status_code not in (304, 429, 500, 502, 503, 504):
                raise
            ultimo_erro = e
        except requests.RequestException as e:
            ultimo_erro = e

        if tentativa < config.TENTATIVAS:
            espera = 2 ** tentativa
            log.warning("falha em %s (tentativa %d) — nova tentativa em %ds: %s",
                        url, tentativa, espera, ultimo_erro)
            time.sleep(espera)

    raise ultimo_erro


def buscar_json(url, params=None, headers=None, timeout=None):
    """Igual a `buscar`, já desserializando o corpo como JSON."""
    return buscar(url, params=params, headers=headers, timeout=timeout).json()

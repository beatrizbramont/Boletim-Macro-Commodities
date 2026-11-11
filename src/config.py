"""Configuração central do boletim: o que coletar e como rotular.

Tudo que é "dado de catálogo" (tickers, códigos de série, feeds) mora aqui,
para que os coletores fiquem só com a lógica de busca.
"""

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DADOS = RAIZ / "dados"
DIR_SITE = RAIZ / "docs"
ARQ_HISTORICO = DIR_DADOS / "historico.csv"

# Pasta de rascunho para execuções locais (veja `modo_previa`). Fica fora do
# versionamento, então testar na própria máquina nunca suja o repositório.
DIR_PREVIA = RAIZ / ".previa"


def modo_previa():
    """Redireciona a escrita para `.previa/`, preservando docs/ e dados/.

    O site e o histórico são versionados porque o GitHub Pages os serve e o
    histórico é o dataset do projeto. Isso significa que rodar localmente e
    deixar o robô rodar no CI produz dois commits mexendo nos mesmos
    arquivos — e todo `git pull` vira conflito. Em modo prévia a execução
    local escreve noutro lugar, e o conflito deixa de existir.
    """
    global DIR_DADOS, DIR_SITE, ARQ_HISTORICO

    DIR_SITE = DIR_PREVIA / "docs"
    DIR_DADOS = DIR_PREVIA / "dados"
    ARQ_HISTORICO = DIR_DADOS / "historico.csv"

    DIR_SITE.mkdir(parents=True, exist_ok=True)
    DIR_DADOS.mkdir(parents=True, exist_ok=True)

    # O histórico versionado é a base real; copiamos para a prévia na
    # primeira vez, senão o boletim de teste sairia sem passado nenhum.
    original = RAIZ / "dados" / "historico.csv"
    if original.exists() and not ARQ_HISTORICO.exists():
        ARQ_HISTORICO.write_text(original.read_text(encoding="utf-8"),
                                 encoding="utf-8")

    return DIR_SITE

IDIOMAS = ("pt", "en")

# --------------------------------------------------------------------------
# Banco Central — API SGS (pública, sem chave)
# https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados
#
# Consultamos por intervalo de datas, e não por /ultimos/N: o endpoint
# /ultimos/N responde 400 acima de ~20 pontos em algumas séries diárias.

# --------------------------------------------------------------------------

SERIES_BCB = {
    "usd_brl": {
        "codigo": 1,
        "nome_pt": "Dólar (PTAX venda)",
        "nome_en": "US Dollar (PTAX ask)",
        "unidade": "R$",
        "casas": 4,
        "periodicidade": "diaria",
        "tipo": "nivel",
    },
    "eur_brl": {
        "codigo": 21619,
        "nome_pt": "Euro (venda)",
        "nome_en": "Euro (ask)",
        "unidade": "R$",
        "casas": 4,
        "periodicidade": "diaria",
        "tipo": "nivel",
    },
    "selic": {
        "codigo": 432,
        "nome_pt": "Selic (meta)",
        "nome_en": "Selic rate (target)",
        "unidade": "% a.a.",
        "casas": 2,
        "periodicidade": "diaria",
        "tipo": "taxa",
    },
    "ipca": {
        "codigo": 433,
        "nome_pt": "IPCA (mês)",
        "nome_en": "IPCA (monthly)",
        "unidade": "%",
        "casas": 2,
        "periodicidade": "mensal",
        "tipo": "taxa",
    },
}

# Janela de consulta ao BCB, em dias corridos.
JANELA_BCB_DIARIA = 120
JANELA_BCB_MENSAL = 540

# --------------------------------------------------------------------------
# Commodities — endpoint chart do Yahoo Finance (público, sem chave)
# Grãos cotados em cents/bushel; moles em cents/libra-peso.
# --------------------------------------------------------------------------

COMMODITIES = {
    "ZS=F": {
        "nome_pt": "Soja",
        "nome_en": "Soybeans",
        "unidade_pt": "¢/bushel",
        "unidade_en": "¢/bushel",
        "grupo": "agro",
    },
    "ZC=F": {
        "nome_pt": "Milho",
        "nome_en": "Corn",
        "unidade_pt": "¢/bushel",
        "unidade_en": "¢/bushel",
        "grupo": "agro",
    },
    "ZW=F": {
        "nome_pt": "Trigo",
        "nome_en": "Wheat",
        "unidade_pt": "¢/bushel",
        "unidade_en": "¢/bushel",
        "grupo": "agro",
    },
    "KC=F": {
        "nome_pt": "Café (Arábica)",
        "nome_en": "Coffee (Arabica)",
        "unidade_pt": "¢/libra",
        "unidade_en": "¢/lb",
        "grupo": "agro",
    },
    "SB=F": {
        "nome_pt": "Açúcar (nº 11)",
        "nome_en": "Sugar (No. 11)",
        "unidade_pt": "¢/libra",
        "unidade_en": "¢/lb",
        "grupo": "agro",
    },
    "CT=F": {
        "nome_pt": "Algodão",
        "nome_en": "Cotton",
        "unidade_pt": "¢/libra",
        "unidade_en": "¢/lb",
        "grupo": "agro",
    },
    "LE=F": {
        "nome_pt": "Boi gordo (CME)",
        "nome_en": "Live Cattle (CME)",
        "unidade_pt": "¢/libra",
        "unidade_en": "¢/lb",
        "grupo": "agro",
    },
    "CL=F": {
        "nome_pt": "Petróleo WTI",
        "nome_en": "WTI Crude Oil",
        "unidade_pt": "US$/barril",
        "unidade_en": "US$/barrel",
        "grupo": "energia",
    },
    "^BVSP": {
        "nome_pt": "Ibovespa",
        "nome_en": "Ibovespa",
        "unidade_pt": "pontos",
        "unidade_en": "points",
        "grupo": "indice",
    },
}

# --------------------------------------------------------------------------
# Notícias — apenas feeds RSS verificados como ativos.
# Agrolink e Notícias Agrícolas foram removidos: devolvem 404.
# Reuters foi removida: descontinuou o RSS público.
# --------------------------------------------------------------------------

FEEDS = [
    {"nome": "g1 Agronegócios", "url": "https://g1.globo.com/rss/g1/economia/agronegocios/", "peso": 3},
    {"nome": "Canal Rural", "url": "https://www.canalrural.com.br/feed/", "peso": 3},
    {"nome": "InfoMoney", "url": "https://www.infomoney.com.br/feed/", "peso": 2},
    {"nome": "g1 Economia", "url": "https://g1.globo.com/rss/g1/economia/", "peso": 2},
    {"nome": "Investing Brasil", "url": "https://br.investing.com/rss/news_11.rss", "peso": 1},
]

# Só entram no boletim as notícias que falam de algo que acompanhamos.
#
# O casamento é por palavra inteira (com plural em -s opcional), nunca por
# substring: sem isso "milho" casa dentro de "milhões" e uma manchete da
# Mega-Sena entra no boletim de commodities. Por isso também não há termos
# curtos e ambíguos aqui — "real" casaria em "realmente"/"realizar", e
# "agro" sozinho não pega "agrícola", que é a forma que de fato aparece.
PALAVRAS_CHAVE = [
    # grãos e lavouras
    "soja", "milho", "trigo", "cafe", "acucar", "algodao", "arroz", "farelo",
    "grao", "graos", "safra", "safrinha", "colheita", "plantio", "lavoura",
    # proteína animal
    "boi", "bois", "pecuaria", "carne", "frango", "suino", "bovino",
    # setor
    "commodities", "commodity", "agronegocio", "agricola", "agropecuaria",
    # comércio exterior
    "exportacao", "exportacoes", "importacao", "importacoes", "embarque",
    # "tarifa" ficou de fora de propósito: pega pedágio, energia e telefonia
    # muito mais do que tarifa de importação.
    "balanca comercial", "comex", "frete", "porto", "portos",
    # macro e câmbio
    "dolar", "cambio", "euro", "selic", "juros", "copom", "ipca", "inflacao",
    "petroleo", "diesel", "ibovespa", "pib",
]

MAX_NOTICIAS = 12          # máximo que vai para o prompt da IA
MAX_NOTICIAS_SITE = 8      # máximo exibido no site

# --------------------------------------------------------------------------
# Rede
# --------------------------------------------------------------------------

TIMEOUT = 25
TENTATIVAS = 3
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

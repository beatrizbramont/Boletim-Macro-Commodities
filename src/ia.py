"""Geração da narrativa do boletim.

Três provedores, escolhidos por variável de ambiente:

  gemini      Google AI Studio, free tier. Padrão. É o que roda no CI.
  cloudflare  Workers AI, free tier. Alternativa quando a rede local
              bloqueia o domínio do Google.
  nenhum      Sem IA: monta o texto a partir dos próprios números.

O modo "nenhum" não é só um plano B de emergência — é o que permite
desenvolver o pipeline inteiro dentro de uma rede que bloqueia domínios de
IA, e garante que uma indisponibilidade da API nunca deixe o boletim sem sair.

Regra de ouro do prompt: a IA interpreta, não calcula. Todos os números vêm
prontos no briefing e ela é instruída a jamais inventar um valor — num
boletim financeiro, um número alucinado é pior do que nenhum texto.
"""

import json
import logging
import os
import re
import time

import requests

from . import rede

log = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

URL_GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
URL_CLOUDFLARE = "https://api.cloudflare.com/client/v4/accounts/{conta}/ai/run/{modelo}"

# Quantos modelos da fila tentar antes de desistir e cair na narrativa
# determinística. Três cobre o caso de o preferido estar lotado sem fazer o
# workflow demorar demais quando a API inteira está instável.
MAX_MODELOS = 3

# Modelos sob carga demoram para o primeiro byte; 90s se mostrou curto.
TIMEOUT_GERACAO = 120

ESQUEMA = {
    "type": "object",
    "properties": {
        "manchete": {"type": "string"},
        "resumo": {"type": "string"},
        "analise": {"type": "array", "items": {"type": "string"}},
        "destaques": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["manchete", "resumo", "analise", "destaques"],
}

INSTRUCOES = {
    "pt": """Você é analista de mercado de uma trading de commodities e escreve o boletim matinal.

Escreva em português do Brasil, tom profissional e direto, sem jargão vazio e sem saudação.

REGRAS INVIOLÁVEIS:
- Use SOMENTE os números do briefing. Nunca invente, estime ou arredonde para um valor diferente.
- Não faça previsão de preço nem recomendação de compra ou venda.
- Se um dado não estiver no briefing, não o mencione.
- Ao citar um número, use exatamente o valor e a unidade fornecidos.

Devolva JSON com:
- "manchete": 1 frase (máx. 90 caracteres) com o fato mais relevante do dia.
- "resumo": 2 a 3 frases situando o dia.
- "analise": 3 a 4 parágrafos. Conecte as variações de preço ao câmbio, ao macro e às manchetes. Explique possíveis causas com cautela ("pode refletir", "em linha com"), nunca como certeza.
- "destaques": 3 a 5 itens curtos, cada um com um número concreto.""",
    "en": """You are a market analyst at a commodities trading firm writing the morning briefing.

Write in English, professional and direct, no empty jargon, no greeting.

NON-NEGOTIABLE RULES:
- Use ONLY the numbers in the briefing. Never invent, estimate, or round to a different value.
- No price forecasts and no buy/sell recommendations.
- If a figure is not in the briefing, do not mention it.
- When citing a number, use exactly the value and unit provided.

Return JSON with:
- "manchete": 1 sentence (max 90 characters) with the day's most relevant fact.
- "resumo": 2-3 sentences framing the day.
- "analise": 3-4 paragraphs. Connect price moves to FX, macro, and the headlines. Suggest causes cautiously ("may reflect", "in line with"), never as certainty.
- "destaques": 3-5 short bullets, each containing a concrete number.""",
}


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

def provedor_configurado():
    """Qual provedor usar, já considerando se há credencial de fato."""
    escolhido = (os.getenv("PROVEDOR_IA") or "gemini").strip().lower()

    if escolhido == "gemini" and not os.getenv("GEMINI_API_KEY"):
        log.warning("PROVEDOR_IA=gemini mas GEMINI_API_KEY está vazia — caindo para 'nenhum'")
        return "nenhum"
    if escolhido == "cloudflare" and not (
        os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN")
    ):
        log.warning("PROVEDOR_IA=cloudflare sem credenciais — caindo para 'nenhum'")
        return "nenhum"

    return escolhido


def testar_conexao():
    """(ok, mensagem) — usado pelo diagnostico.py."""
    provedor = provedor_configurado()
    if provedor == "nenhum":
        return True, "modo sem IA (narrativa determinística)"

    try:
        resposta = _chamar(provedor, "Responda apenas: ok", max_tokens=16, json_estrito=False)
        return True, f"{provedor} respondeu: {resposta[:60].strip()!r}"
    except Exception as e:
        msg = str(e)
        if "SSLError" in type(e).__name__ or "certificate" in msg.lower():
            return False, f"{provedor} inacessível — rede bloqueia o domínio (proxy/TLS)"
        return False, f"{provedor} falhou: {type(e).__name__}: {msg[:110]}"


# ---------------------------------------------------------------------------
# Chamadas aos provedores
# ---------------------------------------------------------------------------

def _erro_da_api(resposta):
    """Mensagem de erro do Google, não o texto genérico do status HTTP.

    `raise_for_status()` diz apenas "400 Client Error" e descarta o corpo —
    mas é no corpo que vem o motivo ("API key not valid", "Unknown name
    thinkingConfig", etc.). Sem isso, diagnosticar exige adivinhação.
    """
    try:
        erro = resposta.json().get("error", {})
        detalhe = erro.get("message") or str(erro)
    except ValueError:
        detalhe = resposta.text
    # Largo o bastante para não cortar a sugestão de substituto: foi assim
    # que a mensagem "use models/gemini-..." chegou truncada no log.
    return f"HTTP {resposta.status_code}: {detalhe[:600]}"


def _post_gemini(modelo, payload):
    return rede.sessao().post(
        URL_GEMINI.format(modelo=modelo),
        headers={
            "x-goog-api-key": os.environ["GEMINI_API_KEY"],
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=TIMEOUT_GERACAO,
    )


# Modelos descobertos nesta execução, em ordem de preferência — evita
# repetir a busca a cada idioma.
_modelos_viaveis = None

# Status que valem nova tentativa no mesmo modelo: são congestionamento ou
# instabilidade passageira do lado do Google, não erro do nosso pedido.
TRANSITORIOS = (429, 500, 502, 503, 504)

# Termos que marcam variantes que não queremos escolher sozinhos: são
# instáveis, caras ou servem a outro propósito.
_INDESEJADOS = ("embedding", "aqa", "vision", "image", "audio", "tts",
                "exp", "preview", "learnlm", "gemma")


def _pontuar(nome):
    """Quanto maior, melhor candidato para escrever o boletim.

    Preferimos a família flash (rápida e com cota generosa no free tier) e,
    dentro dela, a maior versão disponível.
    """
    base = nome.removeprefix("models/")
    if any(t in base for t in _INDESEJADOS):
        return -1

    pontos = 0
    if "flash" in base:
        pontos += 100          # flash é o alvo
        if "lite" in base:
            pontos -= 30       # lite só se não houver flash cheio
    elif "pro" in base:
        pontos += 50           # pro serve, mas gasta mais cota

    # "gemini-3-flash" > "gemini-2.5-flash": a maior versão vence.
    versao = re.search(r"gemini-(\d+)(?:\.(\d+))?", base)
    if versao:
        pontos += int(versao.group(1)) * 10 + int(versao.group(2) or 0)
    if base.endswith("-latest"):
        pontos += 5            # alias estável, sobrevive a trocas de versão
    return pontos


def _descobrir_modelos():
    """Pergunta ao Google quais modelos a chave pode usar, em ordem de preferência.

    Devolvemos a lista inteira, e não só o primeiro colocado: o melhor modelo
    é também o mais concorrido, e quando ele responde 503 por excesso de
    demanda o segundo da fila costuma atender na hora.

    O Google também aposenta modelos para chaves novas sem aviso — foi assim
    que o gemini-2.5-flash parou de responder. Descobrir em tempo de execução
    custa uma requisição e evita quebrar na próxima descontinuação.
    """
    global _modelos_viaveis
    if _modelos_viaveis:
        return _modelos_viaveis

    resposta = rede.sessao().get(
        "https://generativelanguage.googleapis.com/v1beta/models",
        headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
        params={"pageSize": 200},
        timeout=45,
    )
    if not resposta.ok:
        raise RuntimeError(f"não foi possível listar modelos — {_erro_da_api(resposta)}")

    candidatos = [
        m["name"]
        for m in resposta.json().get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    viaveis = sorted(
        (c for c in candidatos if _pontuar(c) > 0), key=_pontuar, reverse=True
    )
    if not viaveis:
        raise RuntimeError(f"nenhum modelo utilizável entre {len(candidatos)} "
                           f"retornados pela API")

    _modelos_viaveis = [m.removeprefix("models/") for m in viaveis]
    log.info("modelos disponíveis (%d): %s", len(_modelos_viaveis),
             ", ".join(_modelos_viaveis[:4]))
    return _modelos_viaveis


def _ler_resposta(resposta, modelo):
    """Extrai o texto de uma resposta bem-sucedida do Gemini."""
    corpo = resposta.json()
    candidatos = corpo.get("candidates") or []
    if not candidatos:
        motivo = corpo.get("promptFeedback", {}).get("blockReason", "sem motivo")
        raise RuntimeError(f"{modelo} não retornou candidatos (bloqueio: {motivo})")

    partes = candidatos[0].get("content", {}).get("parts") or []
    texto = "".join(p.get("text", "") for p in partes)
    if not texto.strip():
        motivo = candidatos[0].get("finishReason", "desconhecido")
        raise RuntimeError(f"{modelo} retornou texto vazio (finishReason={motivo})")
    return texto


def _tentar_modelo(modelo, payload, tentativas=3):
    """Chama um modelo, insistindo enquanto o erro for passageiro.

    Devolve (texto, None) em caso de sucesso e (None, motivo) quando vale a
    pena passar para o próximo modelo da fila.
    """
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = _post_gemini(modelo, payload)
        except requests.exceptions.RequestException as e:
            # Timeout e queda de conexão contam como instabilidade: o modelo
            # mais concorrido costuma estourar o tempo justamente sob carga.
            if tentativa < tentativas:
                espera = 4 * tentativa
                log.warning("%s: %s — nova tentativa em %ds",
                            modelo, type(e).__name__, espera)
                time.sleep(espera)
                continue
            return None, f"{type(e).__name__} após {tentativas} tentativas"

        if resposta.ok:
            return _ler_resposta(resposta, modelo), None

        # Nem todo modelo aceita thinkingConfig; quando não aceita, responde
        # 400 reclamando do campo. Repetir sem ele é melhor que desistir.
        if resposta.status_code == 400 and "thinking" in resposta.text.lower():
            log.warning("%s não aceita thinkingConfig — repetindo sem o campo", modelo)
            payload["generationConfig"].pop("thinkingConfig", None)
            continue

        if resposta.status_code in TRANSITORIOS and tentativa < tentativas:
            espera = 4 * tentativa
            log.warning("%s sobrecarregado (HTTP %d) — nova tentativa em %ds",
                        modelo, resposta.status_code, espera)
            time.sleep(espera)
            continue

        return None, _erro_da_api(resposta)

    return None, "tentativas esgotadas"


def _chamar_gemini(prompt, max_tokens, json_estrito):
    """Gera texto, descendo a fila de modelos enquanto for preciso.

    Um modelo pode estar aposentado (404) ou simplesmente lotado (503). Em
    qualquer dos casos, insistir um pouco e então passar ao próximo da lista
    é mais barato do que publicar o boletim sem análise.
    """
    fixo = os.getenv("GEMINI_MODELO")
    modelos = [fixo] if fixo else _descobrir_modelos()

    config_geracao = {
        "temperature": 0.4,
        "maxOutputTokens": max_tokens,
        # O flash "pensa" por padrão e esse raciocínio consome o teto de
        # saída — sem zerar o orçamento, respostas longas voltam truncadas.
        "thinkingConfig": {"thinkingBudget": 0},
    }
    if json_estrito:
        config_geracao["responseMimeType"] = "application/json"
        config_geracao["responseSchema"] = ESQUEMA

    problemas = []
    for modelo in modelos[:MAX_MODELOS]:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": dict(config_geracao),
        }
        texto, motivo = _tentar_modelo(modelo, payload)
        if texto:
            if problemas:
                log.info("%s respondeu após %d modelo(s) indisponível(is)",
                         modelo, len(problemas))
            return texto
        log.warning("descartando %s: %s", modelo, motivo)
        problemas.append(f"{modelo}: {motivo}")

    raise RuntimeError("nenhum modelo respondeu — " + " | ".join(problemas))


def _chamar_cloudflare(prompt, max_tokens, json_estrito):
    # `json_estrito` é aceito para manter a assinatura dos provedores igual,
    # mas o Workers AI não tem equivalente ao responseSchema do Gemini: o
    # formato é pedido no próprio prompt e `_extrair_json` tolera a resposta
    # vir embrulhada em texto ou cercada por crases.
    del json_estrito

    modelo = os.getenv("CLOUDFLARE_MODELO") or "@cf/meta/llama-3.1-8b-instruct"
    url = URL_CLOUDFLARE.format(
        conta=os.environ["CLOUDFLARE_ACCOUNT_ID"], modelo=modelo
    )
    resposta = rede.sessao().post(
        url,
        headers={"Authorization": f"Bearer {os.environ['CLOUDFLARE_API_TOKEN']}"},
        json={
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.4,
        },
        timeout=90,
    )
    if not resposta.ok:
        raise RuntimeError(f"Cloudflare ({modelo}) recusou — {_erro_da_api(resposta)}")
    corpo = resposta.json()
    if not corpo.get("success", True):
        raise RuntimeError(f"Cloudflare recusou: {corpo.get('errors')}")
    resultado = corpo.get("result", {})
    texto = resultado.get("response") or ""
    if not texto.strip():
        raise RuntimeError("Cloudflare retornou texto vazio")
    return texto


def _chamar(provedor, prompt, max_tokens=2048, json_estrito=False):
    if provedor == "gemini":
        return _chamar_gemini(prompt, max_tokens, json_estrito)
    if provedor == "cloudflare":
        return _chamar_cloudflare(prompt, max_tokens, json_estrito)
    raise ValueError(f"provedor desconhecido: {provedor}")


# ---------------------------------------------------------------------------
# Briefing e parsing
# ---------------------------------------------------------------------------

def _pct(x):
    return f"{x:+.2f}%" if x is not None else "n/d"


def montar_briefing(contexto, idioma):
    """Transforma os dados coletados no texto que vai dentro do prompt."""
    pt = idioma == "pt"
    nome = "nome_pt" if pt else "nome_en"
    unidade = "unidade_pt" if pt else "unidade_en"
    linhas = []

    linhas.append(f"DATA: {contexto['data_ref']}")

    linhas.append("\n[CÂMBIO E MACRO]" if pt else "\n[FX AND MACRO]")
    for d in contexto["macro"].values():
        linhas.append(
            f"- {d[nome]}: {d['valor']:.{d['casas']}f} {d['unidade']}"
            f" | dia {_pct(d['var_dia_pct'])} | mês {_pct(d['var_mes_pct'])}"
            f" | ref {d['data']}"
        )

    linhas.append("\n[COMMODITIES]")
    for d in contexto["commodities"].values():
        linhas.append(
            f"- {d[nome]}: {d['valor']:.2f} {d[unidade]}"
            f" | dia {_pct(d['var_dia_pct'])}"
            f" | semana {_pct(d['var_semana_pct'])}"
            f" | mês {_pct(d['var_mes_pct'])}"
        )

    if contexto.get("destaques"):
        linhas.append("\n[MAIORES VARIAÇÕES DO DIA]" if pt else "\n[LARGEST DAILY MOVES]")
        for d in contexto["destaques"]:
            linhas.append(f"- {d[nome]}: {_pct(d['var_dia_pct'])}")

    if contexto.get("noticias"):
        linhas.append("\n[MANCHETES DO SETOR]" if pt else "\n[SECTOR HEADLINES]")
        for n in contexto["noticias"][:10]:
            linhas.append(f"- ({n['fonte']}) {n['titulo']}")

    return "\n".join(linhas)


def _extrair_json(texto):
    """Lê o JSON da resposta, tolerando cerca de crase e texto ao redor."""
    texto = texto.strip()
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto, flags=re.MULTILINE).strip()
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio != -1 and fim > inicio:
        return json.loads(texto[inicio : fim + 1])
    raise ValueError("resposta da IA não continha JSON")


def _normalizar(bruto):
    """Garante o formato esperado, venha a IA bem ou mal comportada."""
    def lista(v):
        if isinstance(v, list):
            return [str(i).strip() for i in v if str(i).strip()]
        if isinstance(v, str) and v.strip():
            return [p.strip() for p in v.split("\n\n") if p.strip()]
        return []

    return {
        "manchete": str(bruto.get("manchete", "")).strip(),
        "resumo": str(bruto.get("resumo", "")).strip(),
        "analise": lista(bruto.get("analise")),
        "destaques": lista(bruto.get("destaques")),
    }


# ---------------------------------------------------------------------------
# Narrativa sem IA
# ---------------------------------------------------------------------------

def _narrativa_deterministica(contexto, idioma):
    """Boletim montado só com os números — nenhuma chamada de rede."""
    pt = idioma == "pt"
    nome = "nome_pt" if pt else "nome_en"
    unidade = "unidade_pt" if pt else "unidade_en"

    destaques_dia = contexto.get("destaques") or []
    # O placar vem de analise.py e cobre TODOS os ativos. Contar sobre os
    # destaques daria o número de maiores movimentos, não o de altas do dia —
    # e a frase ficaria factualmente errada, contradizendo o placar que a
    # barra lateral exibe na mesma página.
    placar = contexto.get("placar") or {}
    n_altas = placar.get("altas", 0)
    n_baixas = placar.get("baixas", 0)
    n_total = placar.get("total", 0)
    dolar = contexto["macro"].get("usd_brl")

    if destaques_dia:
        lider = destaques_dia[0]
        direcao = (
            ("avança" if pt else "advances")
            if (lider.get("var_dia_pct") or 0) > 0
            else ("recua" if pt else "retreats")
        )
        manchete = f"{lider[nome]} {direcao} {abs(lider['var_dia_pct']):.2f}%"
    else:
        manchete = "Boletim do dia" if pt else "Daily briefing"

    if pt:
        resumo = (
            f"Dos {n_total} ativos acompanhados, {n_altas} fecharam em alta "
            f"e {n_baixas} em baixa. "
        )
        if dolar:
            resumo += (
                f"O dólar PTAX encerrou a R$ {dolar['valor']:.4f} "
                f"({_pct(dolar['var_dia_pct'])} no dia)."
            )
    else:
        resumo = (
            f"Of the {n_total} tracked assets, {n_altas} closed higher "
            f"and {n_baixas} lower. "
        )
        if dolar:
            resumo += (
                f"The PTAX dollar settled at R$ {dolar['valor']:.4f} "
                f"({_pct(dolar['var_dia_pct'])} on the day)."
            )

    paragrafos = []
    if contexto["commodities"]:
        corpo = ", ".join(
            f"{d[nome]} {d['valor']:.2f} {d[unidade]} ({_pct(d['var_dia_pct'])})"
            for d in list(contexto["commodities"].values())[:6]
        )
        paragrafos.append(("Fechamento: " if pt else "Close: ") + corpo + ".")
    if contexto["macro"]:
        corpo = ", ".join(
            f"{d[nome]} {d['valor']:.{d['casas']}f} {d['unidade']}"
            for d in contexto["macro"].values()
        )
        paragrafos.append(("Macro: " if pt else "Macro: ") + corpo + ".")
    paragrafos.append(
        "Narrativa automática gerada sem modelo de linguagem — os números são os mesmos."
        if pt
        else "Automated narrative generated without a language model — the figures are unchanged."
    )

    destaques = [
        f"{d[nome]}: {_pct(d['var_dia_pct'])}" for d in destaques_dia[:5]
    ]

    return {
        "manchete": manchete,
        "resumo": resumo,
        "analise": paragrafos,
        "destaques": destaques,
        "gerado_por": "deterministico",
    }


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def gerar(contexto, idioma):
    """Gera a narrativa no idioma pedido. Nunca levanta exceção."""
    provedor = provedor_configurado()

    if provedor == "nenhum":
        log.info("narrativa [%s] em modo determinístico", idioma)
        return _narrativa_deterministica(contexto, idioma)

    prompt = f"{INSTRUCOES[idioma]}\n\n--- BRIEFING ---\n{montar_briefing(contexto, idioma)}"

    try:
        texto = _chamar(provedor, prompt, max_tokens=2048, json_estrito=True)
        narrativa = _normalizar(_extrair_json(texto))
        if not narrativa["analise"]:
            raise ValueError("IA devolveu análise vazia")
        narrativa["gerado_por"] = provedor
        log.info("narrativa [%s] gerada por %s", idioma, provedor)
        return narrativa
    except Exception as e:
        log.error("IA falhou em [%s] (%s: %s) — usando narrativa determinística",
                  idioma, type(e).__name__, str(e)[:160])
        fallback = _narrativa_deterministica(contexto, idioma)
        fallback["gerado_por"] = "deterministico (falha na IA)"
        return fallback

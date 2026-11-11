# 📊 Boletim Macro & Commodities

Um robô que, todo dia útil às 8h, coleta dados de câmbio, juros e commodities,
cruza com as manchetes do setor, pede a um modelo de linguagem que escreva a
análise e publica um boletim bilíngue — sem ninguém apertar nada.

**→ [Ver o boletim de hoje](https://beatrizbramont.github.io/Boletim-Macro-Commodities/)**
· [English version](https://beatrizbramont.github.io/Boletim-Macro-Commodities/en/)

Roda inteiramente em infraestrutura gratuita: GitHub Actions para a execução,
GitHub Pages para a publicação, e o free tier do Google AI Studio para a
narrativa. Custo mensal: R$ 0,00.

---

## Como funciona

```
  COLETA                      ANÁLISE              NARRATIVA         PUBLICAÇÃO
  ─────────────────────       ───────────          ─────────         ──────────
  Banco Central (API SGS) ┐
   PTAX, Selic, IPCA      │
                          │   variações
  Yahoo Finance           ├──  diárias,    ──►   Gemini     ──►   GitHub Pages
   9 ativos               │    semanais,          (free tier)       pt + en
                          │    mensais,                             │
  RSS do setor            ┘    destaques                            └─► histórico
   5 feeds                                                              em CSV
                               ▲
                               └──── GitHub Actions, cron diário
```

Das quatro fontes, **só o Gemini exige credencial**. Banco Central, Yahoo
Finance e os feeds RSS são todos públicos e abertos.

### O que é coletado

| Categoria | Itens | Fonte |
|---|---|---|
| Câmbio e macro | Dólar PTAX, Euro, Selic, IPCA | Banco Central — API SGS |
| Grãos | Soja, milho, trigo | Yahoo Finance (CME) |
| Softs | Café arábica, açúcar nº 11, algodão | Yahoo Finance (ICE) |
| Proteína e energia | Boi gordo, petróleo WTI | Yahoo Finance |
| Índice | Ibovespa | Yahoo Finance |
| Notícias | g1 Agro, Canal Rural, InfoMoney, g1 Economia, Investing | RSS |

---

## Decisões de implementação

As partes do projeto que não são óbvias, e por quê.

**Chamada HTTP direta ao Yahoo, em vez da biblioteca `yfinance`.**
O `yfinance` fala por `curl_cffi`, que ignora o repositório de certificados do
sistema operacional e por isso falha em qualquer rede com inspeção TLS — o caso
de praticamente toda rede corporativa. O endpoint `chart` do Yahoo devolve um
JSON simples; `requests` resolve, sem a dependência.

**Taxas variam em pontos percentuais, não em porcentagem.**
O IPCA de agosto/2026 foi **−0,32%** (deflação). Calcular variação relativa
contra uma base negativa produz números sem significado — a primeira versão
informava que o IPCA havia variado **−356%**. Séries marcadas como `taxa` no
`config.py` passaram a ser comparadas em p.p.

**O filtro de notícias casa palavra inteira, nunca substring.**
Sem a fronteira de palavra, `"milho"` casa dentro de `"milhões"` — e uma
manchete da **Mega-Sena** apareceu no boletim de commodities. O filtro virou
regex com `\b`, e termos ambíguos como `"real"` e `"tarifa"` (que pegam
"realmente" e pedágio) ficaram de fora de propósito.

**Consulta ao BCB por intervalo de datas, não por `/ultimos/N`.**
O endpoint `/ultimos/N` responde HTTP 400 acima de ~20 pontos em séries
diárias, embora a própria mensagem de erro anuncie aceitar até 99.

**O modelo de IA é descoberto em tempo de execução, não fixado no código.**
A primeira versão trazia `gemini-2.5-flash` escrito no código, e a primeira
execução real falhou com *"this model is no longer available to new users"* —
o Google aposenta modelos para chaves novas sem aviso. Agora o projeto
consulta a API, descarta variantes experimentais e de embedding, e fica com a
família `flash` de maior versão. Uma requisição a mais por execução em troca
de não quebrar na próxima descontinuação.

**A IA interpreta; ela nunca calcula.**
Todos os números chegam prontos ao prompt, e o modelo é instruído a jamais
inventar ou estimar um valor. Num boletim financeiro, um número alucinado é
pior do que texto nenhum.

**O boletim sai mesmo sem IA.**
Se a API falhar, estiver sem cota ou bloqueada pela rede, uma narrativa
determinística é montada a partir dos próprios dados. Degradar é sempre
preferível a não publicar — e é isso que permite desenvolver o projeto dentro
de uma rede que bloqueia domínios de IA.

**Gravação idempotente por (data, ativo).**
Rodar duas vezes no mesmo dia atualiza as linhas daquele dia em vez de
duplicá-las, o que importa porque o workflow também pode ser disparado à mão.

**`Cache-Control: no-cache` em todas as requisições.**
Proxies corporativos chegam a responder HTTP 304 para essas APIs. Num boletim
diário, isso publicaria a cotação de ontem como se fosse de hoje.

---

## Rodando localmente

```bash
git clone https://github.com/beatrizbramont/Boletim-Macro-Commodities.git
cd Boletim-Macro-Commodities

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS

pip install -r requirements.txt
```

Antes de qualquer coisa, confira se as fontes respondem na sua rede:

```bash
python diagnostico.py
```

Ele testa fonte por fonte e diz, em uma linha cada, o que respondeu e o que
caiu — inclusive se o provedor de IA está bloqueado por proxy.

Gerando o boletim:

```bash
python -m src.main --previa --sem-ia   # recomendado para testar
python -m src.main --sem-ia            # sem IA, escrevendo em docs/
python -m src.main                     # completo, exige GEMINI_API_KEY no .env
```

**Use `--previa` ao testar na sua máquina.** O site e o histórico são
versionados — o Pages serve um e o outro é o dataset do projeto —, então uma
execução local e outra do robô no CI produzem dois commits mexendo nos mesmos
arquivos, e todo `git pull` vira conflito. Com `--previa` a saída vai para
`.previa/`, que não é versionada, e `docs/` fica reservado ao robô.

O resultado fica em `docs/index.html` (ou `.previa/docs/index.html`). Abra no
navegador — são arquivos estáticos, sem servidor.

> Se o conflito acontecer mesmo assim, lembre que os arquivos de `docs/` e
> `dados/` são gerados: aceite a versão do servidor e siga.
>
> ```bash
> git checkout --theirs dados docs && git add dados docs && git commit
> ```

### Configurando a IA

Copie `.env.example` para `.env` e preencha a chave:

```ini
PROVEDOR_IA=gemini
GEMINI_API_KEY=sua-chave-aqui
```

A chave gratuita sai de [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

Em rede que bloqueia o domínio do Google, há duas saídas: usar
`PROVEDOR_IA=cloudflare` com o free tier do
[Workers AI](https://dash.cloudflare.com), ou simplesmente desenvolver com
`--sem-ia` e deixar a narrativa para o GitHub Actions, que roda fora da rede
corporativa.

---

## Publicando no GitHub

1. Suba o repositório.
2. **Settings → Secrets and variables → Actions → New repository secret**
   · nome `GEMINI_API_KEY`, valor a sua chave.
3. **Settings → Pages** · Source: `Deploy from a branch`, branch `master`,
   pasta `/docs`.
4. **Actions → Boletim diário → Run workflow** para a primeira execução.

A partir daí roda sozinho de segunda a sexta. O workflow commita o site e o
histórico de volta ao repositório.

---

## Estrutura

```
src/
  config.py            tickers, séries, feeds — todo o catálogo num lugar só
  rede.py              sessão HTTP com truststore, retentativa e no-cache
  coletores/
    bcb.py             câmbio, Selic e IPCA via API SGS
    mercado.py         commodities via endpoint chart do Yahoo
    noticias.py        RSS com filtro por palavra inteira
  analise.py           variações e destaques (camada pura, sem rede)
  historico.py         série temporal acumulada em CSV
  ia.py                Gemini, Cloudflare e a narrativa determinística
  site.py              renderização do HTML bilíngue
  main.py              orquestração
diagnostico.py         checagem de todas as fontes externas
dados/historico.csv    dataset que cresce a cada execução
docs/                  o site publicado
```

### O dataset

Cada execução acrescenta uma linha por ativo em `dados/historico.csv`. O mesmo
robô que publica o boletim vai construindo, sozinho, a base histórica para
analisar os meses seguintes.

---

## Visualização

A identidade é editorial: superfície de papel (creme `#faf8f3`), hairlines,
fio duplo no cabeçalho e no rodapé, escala tipográfica generosa. A intenção é
ler como relatório impresso, e não como painel de corretora — e o efeito vem
de espaçamento e fios, sem nenhum tipo serifado ou decorativo.

As cores de alta e baixa foram validadas por script para daltonismo e
contraste contra a superfície creme (ΔE 12,4, contraste ≥ 3:1 nos dois planos).
A cor nunca carrega significado sozinha: toda variação vem acompanhada de seta
e número, e a tabela inteira é a versão acessível dos sparklines.

---

## Aviso

Conteúdo informativo, gerado automaticamente a partir de fontes públicas.
Não constitui recomendação de investimento. As cotações de commodities são de
contratos futuros internacionais (CME/ICE) e não refletem o mercado físico
brasileiro.

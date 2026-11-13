"""Formatação numérica, compartilhada entre a narrativa e o site.

Existe como módulo próprio porque `site.py` e `ia.py` precisam da mesma
convenção e antes cada um formatava por conta própria: a mesma página
mostrava o dólar como `5,6518` na barra lateral e `5.6518` no título, e o
Ibovespa saía como `172304.64`, sem separador de milhar nenhum.

A formatação também vale para os números que entram no prompt. O modelo
repete o que recebe — alimentá-lo com `172304.64` garante que ele devolva
`172304.64`, por mais instruções que o prompt traga.
"""


def numero(valor, casas, idioma):
    """Separador de milhar; vírgula decimal em pt, ponto em en."""
    if valor is None:
        return "—"
    texto = f"{valor:,.{casas}f}"
    if idioma == "pt":
        # \x00 serve de pivô: trocar "," por "." e depois "." por "," em duas
        # passadas diretas sobrescreveria o resultado da primeira.
        texto = texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return texto


def pct(valor, idioma, casas=2):
    """Percentual com sinal explícito, na convenção decimal do idioma."""
    if valor is None:
        return "n/d" if idioma == "pt" else "n/a"
    sinal = "+" if valor >= 0 else "-"
    return f"{sinal}{numero(abs(valor), casas, idioma)}%"

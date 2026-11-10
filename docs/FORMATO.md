# Formato de Entrada e Saída — `orcamento-composicoes`

## 1. Regras Gerais de JSON

- Codificação UTF-8 estrita, **sem BOM** (`\xef\xbb\xbf`).
- Tamanho máximo de entrada: **8 MiB** (`8.388.608` bytes), profundidade máxima `16` e até `250.000` nós JSON.
- Chaves duplicadas em qualquer objeto são recusadas com `JSON_DUPLICATE_KEY`.
- Números JSON em ponto flutuante ou notação exponencial são recusados com `JSON_FLOAT`. Valores inteiros (como `preco_unitario_centavos`) usam inteiros JSON; coeficientes e percentuais usam textos decimais ASCII estritos (`"85.5"`, `"0.08"`) ou inteiros.

## 2. Esquema de Entrada (`schema_version: 1`)

```json
{
  "schema_version": 1,
  "orcamento": {
    "id": "orc-reforma-galpao-2026",
    "titulo": "Adequação Estrutural e Elétrica de Galpão Logístico",
    "moeda": "BRL",
    "encargos_sociais_percentual": "85.5",
    "bdi_padrao_percentual": "24.8",
    "bdi_equipamentos_percentual": "14.2"
  },
  "insumos": [...],
  "composicoes": [...],
  "itens_orcamento": [...]
}
```

### 2.1. `insumos` (1 a 2.000 itens)
- `id`: identificador ASCII `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`, único no catálogo.
- `descricao`: texto de 1 a 160 caracteres, sem espaços nas bordas nem caracteres de controle.
- `unidade`: texto de 1 a 16 caracteres (ex.: `"sc"`, `"m3"`, `"h"`, `"un"`).
- `natureza`: `"material"` | `"mao_de_obra"` | `"equipamento"` | `"servico_terceiro"`.
- `preco_unitario_centavos`: inteiro positivo (`1..1.000.000.000.000`).
- `aplicar_encargos`: booleano. Só pode ser `true` quando `natureza == "mao_de_obra"` (caso contrário, `ENCARGOS_NATUREZA_INVALIDA`).

### 2.2. `composicoes` (1 a 1.000 itens)
- `id`: identificador único, sem colidir com `insumos`.
- `descricao`, `unidade`.
- `componentes` (1 a 200 componentes):
  - `tipo`: `"insumo"` ou `"composicao"`.
  - `referencia_id`: ID existente de insumo ou de outra composição.
  - `coeficiente`: racional estritamente positivo (`> 0`).
  - `perda_percentual`: racional não negativo (`0..500`).
  - Fator efetivo: $\text{coeficiente} \times (1 + \text{perda\_percentual} / 100)$.

### 2.3. `itens_orcamento` (1 a 1.000 itens)
- `id`: identificador único do item da planilha.
- `etapa`: nome da etapa/grupo orçamentário.
- `composicao_id`: referência a uma composição declarada.
- `quantidade`: racional estritamente positivo.
- `bdi_modo`:
  - `"padrao"`: aplica `bdi_padrao_percentual` sobre todo o custo direto do item.
  - `"diferenciado_equipamentos"`: aplica `bdi_equipamentos_percentual` sobre a parcela de natureza `"equipamento"` e `bdi_padrao_percentual` sobre as demais naturezas.
  - `"isento"`: BDI igual a zero.

## 3. Representação Racional Exata na Saída

Todos os valores calculados em `orcamento-analitico.json` são acompanhados do objeto racional:

```json
{
  "numerador": "12345",
  "denominador": "8",
  "decimal_4": "1543.1250",
  "centavos_arredondados": 1543
}
```

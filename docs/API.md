# API Python — `orcamento_composicoes`

## Funções Principais

```python
from orcamento_composicoes import OrcamentoError, calcular_orcamento, loads

with open("meu-orcamento.json", "rb") as fp:
    documento = loads(fp.read())

relatorio = calcular_orcamento(documento)
print(relatorio["resumo_geral"]["preco_total_orcamento"])
```

- `loads(data: bytes | str) -> Any`: decodifica JSON UTF-8 sem BOM, recusando floats, constantes não finitas e chaves repetidas.
- `calcular_orcamento(documento: Any) -> dict[str, Any]`: valida o documento de entrada sem mutá-lo, resolve o DAG de composições em ordem topológica, calcula os itens de orçamento com BDI e produz a explosão global de insumos com classificação ABC.
- `OrcamentoError(code, message, path)`: exceção tipada com código de erro determinístico (`VERSAO_INVALIDA`, `CAMPO_OBRIGATORIO`, `CAMPO_DESCONHECIDO`, `ID_DUPLICADO`, `ID_CONFLITANTE`, `ENCARGOS_NATUREZA_INVALIDA`, `CICLO_COMPOSICAO`, `DESTINO_EXISTENTE`, etc.).

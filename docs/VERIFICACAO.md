# Verificação e Distribuição — `orcamento-composicoes`

## 1. Suíte de Testes Unitários

```sh
python3 -m unittest discover -s tests -v
```

Executa 59 testes cobrindo o codec JSON estrito, aritmética racional (`Fraction`), detecção de ciclos em composições aninhadas, BDI padrão/diferenciado/isento, conservação exata entre planilha de itens e explosão de insumos, proteção contra injeção de fórmulas em CSV e garantias de não sobrescrita da CLI.

## 2. Verificação de Wheel e Source Distribution

```sh
python3 -m build
python3 scripts/check_distribution.py --dist dist
python3 scripts/check_distribution.py --install dist/orcamento_composicoes-1.0.0-py3-none-any.whl
python3 scripts/check_distribution.py --install dist/orcamento_composicoes-1.0.0.tar.gz
```

O script `check_distribution.py` confere:
- Integridade CRC e lista fechada de arquivos no wheel e no sdist;
- Hashes SHA-256 e tamanhos no arquivo `RECORD` do wheel;
- Ausência de dependências externas (`Requires-Dist`);
- Instalação em `venv` temporário fora da árvore de código e execução real da CLI instalada.

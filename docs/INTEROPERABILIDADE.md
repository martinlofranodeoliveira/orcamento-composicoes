# Interoperabilidade e Oráculo Independente — `orcamento-composicoes`

O script `tools/verify_independent.py` audita os pacotes ZIP produzidos por `orcamento-composicoes` **sem importar o pacote de produção**.

## O que é verificado independentemente

1. **Integridade do arquivo ZIP e `SHA256SUMS`**: confere o CRC de todos os membros, a presença exata dos 8 arquivos esperados e os 7 hashes SHA-256 listados no manifesto.
2. **Reconstrução algébrica recursiva do DAG**: lê apenas `entrada.json` e resolve recursivamente todas as composições e subcomposições usando `fractions.Fraction`, confrontando custo direto, BDI e preço total com `orcamento-analitico.json`.
3. **Teorema da conservação direta**: verifica que a soma exata dos custos diretos dos itens da planilha é idêntica à soma dos custos diretos de todos os insumos elementares explodidos, e que a soma das participações na curva ABC é exatamente `1/1`.
4. **Tabelas CSV em SQLite (`sqlite3`)**: carrega `itens-orcamento.csv` e `insumos-abc.csv` em banco SQLite em memória e confronta a contagem de linhas, chaves primárias e centavos com o JSON analítico.
5. **Isolamento de rede (`--require-network-isolation`)**: quando executado sob `unshare --user --map-root-user --net`, verifica `/proc/net/route` para comprovar ausência de rotas externas.

```sh
unshare --user --map-root-user --net -- python3 tools/verify_independent.py --require-network-isolation
```

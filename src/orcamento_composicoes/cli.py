"""Interface de linha de comando para orcamento-composicoes."""
from __future__ import annotations

import argparse
from importlib import resources
import os
from pathlib import Path
import stat
import sys

from .core import calcular_orcamento
from .errors import OrcamentoError
from .jsoncodec import MAX_BYTES, loads
from .reports import write_bundle_zip


def _read_regular_file(path: str | Path) -> bytes:
    target = Path(path)
    try:
        st_link = os.lstat(target)
    except OSError as exc:
        raise OrcamentoError("ARQUIVO_INVALIDO", f"Não foi possível acessar o arquivo: {target}", str(target)) from exc
    if stat.S_ISLNK(st_link.st_mode) or not stat.S_ISREG(st_link.st_mode):
        raise OrcamentoError(
            "ARQUIVO_INVALIDO",
            "A entrada deve ser um arquivo regular local (links simbólicos não são aceitos).",
            str(target),
        )
    if st_link.st_size > MAX_BYTES:
        raise OrcamentoError("JSON_LIMIT", "Arquivo de entrada excede o limite de 8 MiB.", str(target))
    fd = os.open(target, os.O_RDONLY)
    try:
        st_open = os.fstat(fd)
        if (st_open.st_ino != st_link.st_ino) or (st_open.st_dev != st_link.st_dev):
            raise OrcamentoError("ARQUIVO_INVALIDO", "O arquivo mudou durante a abertura.", str(target))
        with os.fdopen(fd, "rb") as fp:
            data = fp.read(MAX_BYTES + 1)
    except Exception:
        raise
    if len(data) > MAX_BYTES:
        raise OrcamentoError("JSON_LIMIT", "Arquivo de entrada excede o limite de 8 MiB.", str(target))
    return data


def _load_example_bytes() -> bytes:
    ref = resources.files("orcamento_composicoes").joinpath("data/exemplo.json")
    return ref.read_bytes()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="orcamento-composicoes",
        description="Orçamento analítico por composições de custos unitários (CPU), BDI e explosão ABC de insumos.",
    )
    sub = parser.add_subparsers(dest="comando", required=True)

    p_ex = sub.add_parser("exemplo", help="Gera o pacote ZIP completo do cenário autoral de demonstração.")
    p_ex.add_argument("--saida", required=True, help="Caminho de saída para o novo arquivo ZIP.")

    p_calc = sub.add_parser("calcular", help="Calcula um orçamento analítico a partir de um arquivo JSON.")
    p_calc.add_argument("entrada", help="Caminho do arquivo JSON de entrada.")
    p_calc.add_argument("--saida", required=True, help="Caminho de saída para o novo arquivo ZIP.")

    try:
        args = parser.parse_args(argv)
        if args.comando == "exemplo":
            raw_bytes = _load_example_bytes()
        else:
            raw_bytes = _read_regular_file(args.entrada)

        doc = loads(raw_bytes)
        report = calcular_orcamento(doc)
        write_bundle_zip(args.saida, raw_bytes, report)
        res = report["resumo_geral"]
        print(
            f"orcamento-composicoes: pacote gerado em {args.saida} "
            f"(direto={res['custo_total_direto']['centavos_arredondados']} centavos, "
            f"bdi={res['valor_total_bdi']['centavos_arredondados']} centavos, "
            f"total={res['preco_total_orcamento']['centavos_arredondados']} centavos)."
        )
        return 0
    except OrcamentoError as exc:
        print(f"erro [{exc.code}]: {exc.message} (caminho: {exc.path})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

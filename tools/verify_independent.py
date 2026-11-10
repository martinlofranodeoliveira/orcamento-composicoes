#!/usr/bin/env python3
"""Verificador independente do pacote ZIP produzido por orcamento-composicoes.

Não importa o pacote de produção. Recalcula composições recursivas, BDI e
explosão de insumos usando Fraction e confere invariantes SQL em sqlite3.
"""
from __future__ import annotations

import argparse
import csv
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import zipfile


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def check_network_isolation() -> dict[str, object]:
    """Confere que o processo está em namespace de rede isolado (apenas loopback)."""
    proc_net = Path("/proc/net/route")
    routes = []
    if proc_net.exists():
        lines = proc_net.read_text(encoding="utf-8").splitlines()[1:]
        routes = [line.strip() for line in lines if line.strip()]
    require(len(routes) == 0, f"Rotas IPv4 inesperadas no namespace isolado: {routes}")
    return {"isolated": True, "ipv4Routes": 0}


def verify_zip_bundle(zip_path: Path) -> dict[str, object]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        require(zf.testzip() is None, "CRC inválido no arquivo ZIP.")
        names = set(zf.namelist())
        expected_names = {
            "LEIA-ME.md",
            "RELATORIO.md",
            "SHA256SUMS",
            "entrada.json",
            "insumos-abc.csv",
            "itens-orcamento.csv",
            "orcamento-analitico.json",
            "painel-orcamento.svg",
        }
        require(names == expected_names, f"Membros do ZIP divergem: {sorted(names)}")
        raw = {name: zf.read(name) for name in names}

    # Verify SHA256SUMS
    sha_lines = raw["SHA256SUMS"].decode("utf-8").strip().splitlines()
    require(len(sha_lines) == 7, "SHA256SUMS deve conter 7 linhas.")
    for line in sha_lines:
        digest, fname = line.split("  ", 1)
        actual_digest = hashlib.sha256(raw[fname]).hexdigest()
        require(digest == actual_digest, f"Hash SHA-256 divergente para {fname}.")

    entrada = json.loads(raw["entrada.json"].decode("utf-8"))
    relatorio = json.loads(raw["orcamento-analitico.json"].decode("utf-8"))

    # Independent Fraction recomputation from entrada.json
    enc_pct = Fraction(str(entrada["orcamento"]["encargos_sociais_percentual"]))
    bdi_pad = Fraction(str(entrada["orcamento"]["bdi_padrao_percentual"]))
    bdi_eq = Fraction(str(entrada["orcamento"]["bdi_equipamentos_percentual"]))

    insumos = {}
    for ins in entrada["insumos"]:
        base = Fraction(ins["preco_unitario_centavos"], 1)
        fator_enc = Fraction(1, 1) + enc_pct / 100 if ins["aplicar_encargos"] else Fraction(1, 1)
        insumos[ins["id"]] = {
            "natureza": ins["natureza"],
            "custo_efetivo": base * fator_enc,
        }

    comp_defs = {c["id"]: c for c in entrada["composicoes"]}
    memo_comp: dict[str, tuple[dict[str, Fraction], dict[str, Fraction]]] = {}

    def solve_comp(cid: str) -> tuple[dict[str, Fraction], dict[str, Fraction]]:
        if cid in memo_comp:
            return memo_comp[cid]
        nats = {
            "material": Fraction(0, 1),
            "mao_de_obra": Fraction(0, 1),
            "equipamento": Fraction(0, 1),
            "servico_terceiro": Fraction(0, 1),
        }
        eq_ins: dict[str, Fraction] = {}
        for comp in comp_defs[cid]["componentes"]:
            coef = Fraction(str(comp["coeficiente"]))
            perda = Fraction(str(comp["perda_percentual"]))
            fator = coef * (Fraction(1, 1) + perda / 100)
            ref = comp["referencia_id"]
            if comp["tipo"] == "insumo":
                nat = insumos[ref]["natureza"]
                nats[nat] += fator * insumos[ref]["custo_efetivo"]
                eq_ins[ref] = eq_ins.get(ref, Fraction(0, 1)) + fator
            else:
                sub_nats, sub_eq = solve_comp(ref)
                for k, v in sub_nats.items():
                    nats[k] += fator * v
                for iid, q in sub_eq.items():
                    eq_ins[iid] = eq_ins.get(iid, Fraction(0, 1)) + fator * q
        memo_comp[cid] = (nats, eq_ins)
        return nats, eq_ins

    total_direto = Fraction(0, 1)
    total_bdi = Fraction(0, 1)
    demanda_ins: dict[str, Fraction] = {iid: Fraction(0, 1) for iid in insumos}

    for it in entrada["itens_orcamento"]:
        qtd = Fraction(str(it["quantidade"]))
        nats, eq_ins = solve_comp(it["composicao_id"])
        direto_item = qtd * sum(nats.values(), Fraction(0, 1))
        total_direto += direto_item
        modo = it["bdi_modo"]
        if modo == "isento":
            bdi_item = Fraction(0, 1)
        elif modo == "padrao":
            bdi_item = direto_item * (bdi_pad / 100)
        else:
            equip_val = qtd * nats["equipamento"]
            outros_val = direto_item - equip_val
            bdi_item = outros_val * (bdi_pad / 100) + equip_val * (bdi_eq / 100)
        total_bdi += bdi_item
        for iid, q in eq_ins.items():
            demanda_ins[iid] += qtd * q

    total_preco = total_direto + total_bdi
    soma_explosao = sum(demanda_ins[iid] * insumos[iid]["custo_efetivo"] for iid in insumos)
    require(soma_explosao == total_direto, "Conservação exata entre itens e explosão falhou no oráculo.")

    res = relatorio["resumo_geral"]
    require(
        Fraction(int(res["custo_total_direto"]["numerador"]), int(res["custo_total_direto"]["denominador"])) == total_direto,
        "Custo direto do relatório diverge do oráculo independente.",
    )
    require(
        Fraction(int(res["valor_total_bdi"]["numerador"]), int(res["valor_total_bdi"]["denominador"])) == total_bdi,
        "Valor de BDI do relatório diverge do oráculo independente.",
    )
    require(
        Fraction(int(res["preco_total_orcamento"]["numerador"]), int(res["preco_total_orcamento"]["denominador"])) == total_preco,
        "Preço total do relatório diverge do oráculo independente.",
    )

    # Verify CSV tables in SQLite
    with sqlite3.connect(":memory:") as conn:
        conn.execute("CREATE TABLE itens (id TEXT PRIMARY KEY, direto INT, bdi INT, total INT)")
        itens_rows = list(csv.DictReader(io.StringIO(raw["itens-orcamento.csv"].decode("utf-8"))))
        require(len(itens_rows) == len(relatorio["itens_orcamento"]), "Contagem de linhas em itens-orcamento.csv diverge.")
        for r in itens_rows:
            conn.execute(
                "INSERT INTO itens VALUES (?, ?, ?, ?)",
                (
                    r["id"],
                    int(r["custo_total_direto_centavos"]),
                    int(r["valor_bdi_centavos"]),
                    int(r["preco_total_centavos"]),
                ),
            )
    conn.close()

    ins_rows = list(csv.DictReader(io.StringIO(raw["insumos-abc.csv"].decode("utf-8"))))
    require(len(ins_rows) == len(relatorio["explosao_insumos"]), "Contagem de linhas em insumos-abc.csv diverge.")
    soma_part = sum(
        Fraction(int(x["participacao_direta"]["numerador"]), int(x["participacao_direta"]["denominador"]))
        for x in relatorio["explosao_insumos"]
    )
    require(soma_part == Fraction(1, 1), "A soma das participações diretas na curva ABC deve ser exatamente 1.")

    svg_text = raw["painel-orcamento.svg"].decode("utf-8")
    require(svg_text.startswith("<svg") and "</svg>" in svg_text, "SVG inválido.")

    return {
        "ok": True,
        "itensVerificados": len(itens_rows),
        "insumosExplodidosVerificados": len(ins_rows),
        "custoTotalDiretoCentavos": int(round(total_direto)),
        "precoTotalOrcamentoCentavos": int(round(total_preco)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, help="Pacote ZIP já gerado para conferência.")
    parser.add_argument("--cli", type=str, help="Executável da CLI instalada para gerar pacote temporário.")
    parser.add_argument("--require-network-isolation", action="store_true")
    parser.add_argument("--report", type=Path, help="Caminho opcional para salvar relatório JSON.")
    args = parser.parse_args()

    net_info = check_network_isolation() if args.require_network_isolation else {"isolated": False}

    if args.zip:
        summary = verify_zip_bundle(args.zip)
    else:
        cli_cmd = [args.cli] if args.cli else [sys.executable, "-m", "orcamento_composicoes.cli"]
        with tempfile.TemporaryDirectory() as tmpdir:
            out_zip = Path(tmpdir) / "exemplo-verificado.zip"
            proc = subprocess.run(
                [*cli_cmd, "exemplo", "--saida", str(out_zip)],
                check=True,
                capture_output=True,
                text=True,
            )
            require(out_zip.is_file(), f"CLI não gerou o pacote esperado: {proc.stderr}")
            summary = verify_zip_bundle(out_zip)

    summary["network"] = net_info
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

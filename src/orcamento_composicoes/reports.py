"""Geração de relatórios CSV, Markdown, SVG e pacote ZIP com manifesto SHA-256."""
from __future__ import annotations

import csv
import hashlib
from html import escape
import io
import os
from pathlib import Path
import tempfile
from typing import Any
import zipfile

from .errors import OrcamentoError
from .jsoncodec import dumps_output

FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_csv_cell(value: Any) -> str:
    text = str(value)
    if text.startswith(FORMULA_LEADERS):
        return "'" + text
    return text


def render_itens_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "id",
            "etapa",
            "composicao_id",
            "descricao",
            "unidade",
            "quantidade_decimal",
            "bdi_modo",
            "custo_unitario_direto_centavos",
            "custo_total_direto_centavos",
            "valor_bdi_centavos",
            "preco_total_centavos",
            "preco_total_numerador",
            "preco_total_denominador",
            "participacao_percentual",
        ]
    )
    for item in report["itens_orcamento"]:
        writer.writerow(
            [
                safe_csv_cell(item["id"]),
                safe_csv_cell(item["etapa"]),
                safe_csv_cell(item["composicao_id"]),
                safe_csv_cell(item["descricao"]),
                safe_csv_cell(item["unidade"]),
                item["quantidade"]["decimal_4"],
                item["bdi_modo"],
                item["custo_unitario_direto"]["centavos_arredondados"],
                item["custo_total_direto"]["centavos_arredondados"],
                item["valor_bdi"]["centavos_arredondados"],
                item["preco_total"]["centavos_arredondados"],
                item["preco_total"]["numerador"],
                item["preco_total"]["denominador"],
                item["participacao_orcamento_percentual"],
            ]
        )
    return buf.getvalue()


def render_insumos_abc_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "ordem_abc",
            "classe_abc",
            "id",
            "descricao",
            "unidade",
            "natureza",
            "preco_base_centavos",
            "aplicar_encargos",
            "custo_unitario_efetivo_centavos",
            "quantidade_total_decimal",
            "custo_total_direto_centavos",
            "custo_total_direto_numerador",
            "custo_total_direto_denominador",
            "participacao_percentual",
            "participacao_acumulada_percentual",
        ]
    )
    for ins in report["explosao_insumos"]:
        writer.writerow(
            [
                ins["ordem_abc"],
                ins["classe_abc"],
                safe_csv_cell(ins["id"]),
                safe_csv_cell(ins["descricao"]),
                safe_csv_cell(ins["unidade"]),
                ins["natureza"],
                ins["preco_unitario_base_centavos"],
                "true" if ins["aplicar_encargos"] else "false",
                ins["custo_unitario_efetivo"]["centavos_arredondados"],
                ins["quantidade_total"]["decimal_4"],
                ins["custo_total_direto"]["centavos_arredondados"],
                ins["custo_total_direto"]["numerador"],
                ins["custo_total_direto"]["denominador"],
                ins["participacao_direta"]["percentual_4"],
                ins["participacao_acumulada"]["percentual_4"],
            ]
        )
    return buf.getvalue()


def _fmt_brl(centavos: int) -> str:
    reais, cents = divmod(abs(centavos), 100)
    reais_str = f"{reais:,}".replace(",", ".")
    prefix = "-" if centavos < 0 else ""
    return f"R$ {prefix}{reais_str},{cents:02d}"


def render_markdown(report: dict[str, Any]) -> str:
    orc = report["orcamento"]
    res = report["resumo_geral"]
    lines = [
        f"# Relatório Analítico de Orçamento — {orc['titulo']}",
        "",
        f"- **ID do orçamento:** `{orc['id']}`",
        f"- **Moeda:** `{orc['moeda']}`",
        f"- **Encargos sociais sobre mão de obra:** `{orc['encargos_sociais_percentual']}%`",
        f"- **BDI padrão:** `{orc['bdi_padrao_percentual']}%`",
        f"- **BDI diferenciado (equipamentos):** `{orc['bdi_equipamentos_percentual']}%`",
        f"- **Conservação exata (Itens vs. Explosão de Insumos):** `{'SIM' if res['conservacao_exata_direto'] else 'NÃO'}`",
        "",
        "## Quadro Resumo Financeiro",
        "",
        "| Indicador | Centavos Arredondados | Valor em R$ | Racional Exato (num/den) |",
        "| --- | ---: | ---: | --- |",
        f"| Custo Total Direto | {res['custo_total_direto']['centavos_arredondados']} | {_fmt_brl(res['custo_total_direto']['centavos_arredondados'])} | `{res['custo_total_direto']['numerador']}/{res['custo_total_direto']['denominador']}` |",
        f"| Valor Total de BDI | {res['valor_total_bdi']['centavos_arredondados']} | {_fmt_brl(res['valor_total_bdi']['centavos_arredondados'])} | `{res['valor_total_bdi']['numerador']}/{res['valor_total_bdi']['denominador']}` |",
        f"| **Preço Total do Orçamento** | **{res['preco_total_orcamento']['centavos_arredondados']}** | **{_fmt_brl(res['preco_total_orcamento']['centavos_arredondados'])}** | `{res['preco_total_orcamento']['numerador']}/{res['preco_total_orcamento']['denominador']}` |",
        "",
        "## Planilha de Itens do Orçamento",
        "",
        "| ID | Etapa | Composição | Qtd | Modo BDI | Custo Direto | BDI | Preço Total | % |",
        "| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: |",
    ]
    for it in report["itens_orcamento"]:
        lines.append(
            f"| `{it['id']}` | {it['etapa']} | `{it['composicao_id']}` ({it['descricao']}) | "
            f"{it['quantidade']['decimal_4']} {it['unidade']} | `{it['bdi_modo']}` | "
            f"{_fmt_brl(it['custo_total_direto']['centavos_arredondados'])} | "
            f"{_fmt_brl(it['valor_bdi']['centavos_arredondados'])} | "
            f"{_fmt_brl(it['preco_total']['centavos_arredondados'])} | "
            f"{it['participacao_orcamento_percentual']}% |"
        )

    lines.extend(
        [
            "",
            "## Explosão Global de Insumos e Curva ABC",
            "",
            "| Ordem | Classe | ID | Insumo | Natureza | Qtd Total | Custo Direto | % Individual | % Acumulado |",
            "| ---: | :---: | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for ins in report["explosao_insumos"]:
        lines.append(
            f"| {ins['ordem_abc']} | **{ins['classe_abc']}** | `{ins['id']}` | {ins['descricao']} | "
            f"`{ins['natureza']}` | {ins['quantidade_total']['decimal_4']} {ins['unidade']} | "
            f"{_fmt_brl(ins['custo_total_direto']['centavos_arredondados'])} | "
            f"{ins['participacao_direta']['percentual_4']}% | "
            f"{ins['participacao_acumulada']['percentual_4']}% |"
        )

    lines.extend(
        [
            "",
            "---",
            "Gerado localmente por `orcamento-composicoes` (LOFRANO TECNOLOGIA · Licença MIT).",
            "",
        ]
    )
    return "\n".join(lines)


def render_svg(report: dict[str, Any]) -> str:
    orc = report["orcamento"]
    res = report["resumo_geral"]
    direto_c = res["custo_total_direto"]["centavos_arredondados"]
    bdi_c = res["valor_total_bdi"]["centavos_arredondados"]
    total_c = res["preco_total_orcamento"]["centavos_arredondados"]

    nat_labels = [
        ("material", "Materiais", "#38bdf8"),
        ("mao_de_obra", "Mão de Obra (+Encargos)", "#f472b6"),
        ("equipamento", "Equipamentos", "#facc15"),
        ("servico_terceiro", "Serviços de Terceiros", "#a78bfa"),
    ]

    svg_parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 760" width="1200" height="760">',
        '  <rect width="1200" height="760" fill="#0b1120"/>',
        '  <rect x="28" y="28" width="1144" height="704" rx="16" fill="#111827" stroke="#1e293b" stroke-width="2"/>',
        f'  <text x="60" y="78" fill="#f8fafc" font-family="sans-serif" font-size="24" font-weight="700">{escape(orc["titulo"])}</text>',
        f'  <text x="60" y="106" fill="#94a3b8" font-family="sans-serif" font-size="14">LOFRANO TECNOLOGIA · Orçamento Analítico por Composições (CPU) · ID: {escape(orc["id"])}</text>',
        '  <rect x="60" y="130" width="340" height="104" rx="12" fill="#1e293b"/>',
        '  <text x="84" y="162" fill="#94a3b8" font-family="sans-serif" font-size="13">CUSTO TOTAL DIRETO</text>',
        f'  <text x="84" y="200" fill="#38bdf8" font-family="sans-serif" font-size="26" font-weight="700">{escape(_fmt_brl(direto_c))}</text>',
        f'  <text x="84" y="220" fill="#64748b" font-family="monospace" font-size="11">Exato: {res["custo_total_direto"]["numerador"]}/{res["custo_total_direto"]["denominador"]}</text>',
        '  <rect x="430" y="130" width="340" height="104" rx="12" fill="#1e293b"/>',
        f'  <text x="454" y="162" fill="#94a3b8" font-family="sans-serif" font-size="13">TOTAL BDI (Padrão {orc["bdi_padrao_percentual"]}% / Equip. {orc["bdi_equipamentos_percentual"]}%)</text>',
        f'  <text x="454" y="200" fill="#f472b6" font-family="sans-serif" font-size="26" font-weight="700">{escape(_fmt_brl(bdi_c))}</text>',
        f'  <text x="454" y="220" fill="#64748b" font-family="monospace" font-size="11">Exato: {res["valor_total_bdi"]["numerador"]}/{res["valor_total_bdi"]["denominador"]}</text>',
        '  <rect x="800" y="130" width="340" height="104" rx="12" fill="#1e293b"/>',
        '  <text x="824" y="162" fill="#94a3b8" font-family="sans-serif" font-size="13">PREÇO TOTAL DO ORÇAMENTO</text>',
        f'  <text x="824" y="200" fill="#34d399" font-family="sans-serif" font-size="26" font-weight="700">{escape(_fmt_brl(total_c))}</text>',
        f'  <text x="824" y="220" fill="#64748b" font-family="monospace" font-size="11">Conservação Direta: {"VERIFICADA" if res["conservacao_exata_direto"] else "FALHA"}</text>',
        '  <text x="60" y="276" fill="#e2e8f0" font-family="sans-serif" font-size="16" font-weight="700">Composição do Custo Direto por Natureza</text>',
    ]

    bar_y = 300
    max_nat = max(
        (res["por_natureza_direto"][k]["centavos_arredondados"] for k, _, _ in nat_labels),
        default=1,
    ) or 1
    for key, label, color in nat_labels:
        val_c = res["por_natureza_direto"][key]["centavos_arredondados"]
        width = max(6, int((val_c / max_nat) * 320)) if val_c > 0 else 0
        pct = (val_c * 100.0 / direto_c) if direto_c > 0 else 0.0
        svg_parts.append(
            f'  <text x="60" y="{bar_y + 18}" fill="#cbd5e1" font-family="sans-serif" font-size="13">{escape(label)}</text>'
        )
        svg_parts.append(
            f'  <rect x="240" y="{bar_y}" width="320" height="24" rx="5" fill="#1e293b"/>'
        )
        if width > 0:
            svg_parts.append(
                f'  <rect x="240" y="{bar_y}" width="{width}" height="24" rx="5" fill="{color}"/>'
            )
        svg_parts.append(
            f'  <text x="572" y="{bar_y + 17}" fill="#f8fafc" font-family="monospace" font-size="12">{escape(_fmt_brl(val_c))} ({pct:.1f}%)</text>'
        )
        bar_y += 42

    svg_parts.append(
        '  <text x="60" y="495" fill="#e2e8f0" font-family="sans-serif" font-size="16" font-weight="700">Top Insumos Explodidos (Curva ABC de Custos Diretos)</text>'
    )
    row_y = 524
    for ins in report["explosao_insumos"][:6]:
        badge_color = "#f43f5e" if ins["classe_abc"] == "A" else ("#f59e0b" if ins["classe_abc"] == "B" else "#64748b")
        svg_parts.append(
            f'  <rect x="60" y="{row_y - 16}" width="28" height="22" rx="4" fill="{badge_color}"/>'
        )
        svg_parts.append(
            f'  <text x="74" y="{row_y}" text-anchor="middle" fill="#ffffff" font-family="sans-serif" font-size="12" font-weight="700">{ins["classe_abc"]}</text>'
        )
        svg_parts.append(
            f'  <text x="100" y="{row_y}" fill="#e2e8f0" font-family="sans-serif" font-size="13">{escape(ins["id"])} — {escape(ins["descricao"][:46])}</text>'
        )
        svg_parts.append(
            f'  <text x="640" y="{row_y}" fill="#94a3b8" font-family="monospace" font-size="12">Qtd: {ins["quantidade_total"]["decimal_4"]} {escape(ins["unidade"])}</text>'
        )
        svg_parts.append(
            f'  <text x="860" y="{row_y}" fill="#38bdf8" font-family="monospace" font-size="12">{escape(_fmt_brl(ins["custo_total_direto"]["centavos_arredondados"]))}</text>'
        )
        svg_parts.append(
            f'  <text x="1030" y="{row_y}" fill="#cbd5e1" font-family="monospace" font-size="12">Acum: {ins["participacao_acumulada"]["percentual_4"]}%</text>'
        )
        row_y += 32

    svg_parts.append("</svg>\n")
    return "\n".join(svg_parts)


def render_leia_me(report: dict[str, Any]) -> str:
    orc = report["orcamento"]
    return "\n".join(
        [
            f"# Pacote de Orçamento Analítico — {orc['titulo']}",
            "",
            "Este arquivo ZIP foi produzido localmente por `orcamento-composicoes`.",
            "",
            "## Conteúdo do pacote",
            "",
            "- `entrada.json`: documento original submetido à análise.",
            "- `orcamento-analitico.json`: memória completa com frações exatas (`numerador`/`denominador`), composições, itens e explosão ABC.",
            "- `itens-orcamento.csv`: planilha de itens com custos diretos, BDI e preços totais.",
            "- `insumos-abc.csv`: explosão global consolidada de insumos em ordem de Pareto (classes A, B e C).",
            "- `RELATORIO.md`: síntese executiva e memória de cálculo em Markdown.",
            "- `painel-orcamento.svg`: gráfico vetorial de composição por natureza e curva ABC.",
            "- `SHA256SUMS`: hashes SHA-256 de todos os membros do pacote.",
            "",
        ]
    )


def write_bundle_zip(
    output_path: str | Path,
    raw_input_bytes: bytes,
    report: dict[str, Any],
) -> dict[str, str]:
    target = Path(output_path)
    if target.exists() or target.is_symlink():
        raise OrcamentoError(
            "DESTINO_EXISTENTE",
            f"O caminho de saída já existe e não será sobrescrito: {target}",
            str(target),
        )
    parent = target.parent.resolve()
    if not parent.is_dir():
        raise OrcamentoError(
            "DIRETORIO_INEXISTENTE",
            f"O diretório pai não existe: {parent}",
            str(target),
        )

    members: dict[str, bytes] = {
        "entrada.json": raw_input_bytes,
        "orcamento-analitico.json": dumps_output(report).encode("utf-8"),
        "itens-orcamento.csv": render_itens_csv(report).encode("utf-8"),
        "insumos-abc.csv": render_insumos_abc_csv(report).encode("utf-8"),
        "RELATORIO.md": render_markdown(report).encode("utf-8"),
        "painel-orcamento.svg": render_svg(report).encode("utf-8"),
        "LEIA-ME.md": render_leia_me(report).encode("utf-8"),
    }

    hashes: dict[str, str] = {}
    sha_lines: list[str] = []
    for name in sorted(members):
        digest = hashlib.sha256(members[name]).hexdigest()
        hashes[name] = digest
        sha_lines.append(f"{digest}  {name}")
    members["SHA256SUMS"] = ("\n".join(sha_lines) + "\n").encode("utf-8")

    fixed_dt = (2026, 1, 1, 0, 0, 0)
    fd, tmp_name = tempfile.mkstemp(prefix=".orcamento-", suffix=".zip.tmp", dir=str(parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fp:
            with zipfile.ZipFile(fp, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                for name in sorted(members):
                    info = zipfile.ZipInfo(filename=name, date_time=fixed_dt)
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o644 << 16
                    zf.writestr(info, members[name])
            fp.flush()
            os.fsync(fp.fileno())
        try:
            os.link(tmp_path, target)
        except FileExistsError:
            raise OrcamentoError(
                "DESTINO_EXISTENTE",
                f"O caminho de saída já existe e não será sobrescrito: {target}",
                str(target),
            ) from None
    finally:
        tmp_path.unlink(missing_ok=True)

    return hashes

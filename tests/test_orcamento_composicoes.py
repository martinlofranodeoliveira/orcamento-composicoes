"""Suíte de testes completa para orcamento-composicoes."""
from __future__ import annotations

import copy
from fractions import Fraction
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from orcamento_composicoes import (
    OrcamentoError,
    calcular_orcamento,
    dumps,
    dumps_output,
    format_decimal,
    loads,
    rational_dict,
    round_half_even_int,
)
from orcamento_composicoes.cli import main as cli_main
from orcamento_composicoes.reports import (
    render_insumos_abc_csv,
    render_itens_csv,
    render_markdown,
    render_svg,
    safe_csv_cell,
    write_bundle_zip,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "src" / "orcamento_composicoes" / "data" / "exemplo.json"


def base_doc() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


class TestJsonCodec(unittest.TestCase):
    def test_01_loads_valid_example(self) -> None:
        raw = EXAMPLE_PATH.read_bytes()
        doc = loads(raw)
        self.assertEqual(doc["schema_version"], 1)

    def test_02_rejects_utf8_bom_bytes(self) -> None:
        with self.assertRaises(OrcamentoError) as ctx:
            loads(b"\xef\xbb\xbf{}")
        self.assertEqual(ctx.exception.code, "JSON_BOM")

    def test_03_rejects_utf8_bom_str(self) -> None:
        with self.assertRaises(OrcamentoError) as ctx:
            loads("\ufeff{}")
        self.assertEqual(ctx.exception.code, "JSON_BOM")

    def test_04_rejects_invalid_utf8(self) -> None:
        with self.assertRaises(OrcamentoError) as ctx:
            loads(b"\xff\xfe{}")
        self.assertEqual(ctx.exception.code, "JSON_UTF8")

    def test_05_rejects_float_number(self) -> None:
        with self.assertRaises(OrcamentoError) as ctx:
            loads('{"a": 1.5}')
        self.assertEqual(ctx.exception.code, "JSON_FLOAT")

    def test_06_rejects_exponent_number(self) -> None:
        with self.assertRaises(OrcamentoError) as ctx:
            loads('{"a": 1e3}')
        self.assertEqual(ctx.exception.code, "JSON_FLOAT")

    def test_07_rejects_nan_and_infinity(self) -> None:
        for token in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(token=token):
                with self.assertRaises(OrcamentoError) as ctx:
                    loads(f'{{"a": {token}}}')
                self.assertEqual(ctx.exception.code, "JSON_INVALID")

    def test_08_rejects_duplicate_keys(self) -> None:
        with self.assertRaises(OrcamentoError) as ctx:
            loads('{"a": 1, "a": 2}')
        self.assertEqual(ctx.exception.code, "JSON_DUPLICATE_KEY")

    def test_09_rejects_excessive_depth(self) -> None:
        nested = "[" * 20 + "]" * 20
        with self.assertRaises(OrcamentoError) as ctx:
            loads(nested)
        self.assertEqual(ctx.exception.code, "JSON_LIMIT")

    def test_10_rejects_excessive_integer_digits(self) -> None:
        huge = "9" * 45
        with self.assertRaises(OrcamentoError) as ctx:
            loads(f'{{"a": {huge}}}')
        self.assertEqual(ctx.exception.code, "JSON_LIMIT")

    def test_11_rejects_non_bytes_or_str(self) -> None:
        with self.assertRaises(OrcamentoError) as ctx:
            loads(123)  # type: ignore[arg-type]
        self.assertEqual(ctx.exception.code, "JSON_INVALID")

    def test_12_dumps_roundtrip(self) -> None:
        doc = {"a": 1, "b": ["x", True, None]}
        encoded = dumps(doc)
        self.assertEqual(loads(encoded), doc)


class TestRationalHelpers(unittest.TestCase):
    def test_13_round_half_even(self) -> None:
        self.assertEqual(round_half_even_int(Fraction(5, 2)), 2)
        self.assertEqual(round_half_even_int(Fraction(7, 2)), 4)

    def test_14_format_decimal(self) -> None:
        self.assertEqual(format_decimal(Fraction(1, 8), 4), "0.1250")
        self.assertEqual(format_decimal(Fraction(3, 2), 0), "2")

    def test_15_rational_dict_structure(self) -> None:
        d = rational_dict(Fraction(250, 3))
        self.assertEqual(d["numerador"], "250")
        self.assertEqual(d["denominador"], "3")
        self.assertEqual(d["decimal_4"], "83.3333")
        self.assertEqual(d["centavos_arredondados"], 83)


class TestCoreValidation(unittest.TestCase):
    def test_16_rejects_wrong_schema_version(self) -> None:
        doc = base_doc()
        doc["schema_version"] = 2
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "VERSAO_INVALIDA")

    def test_17_rejects_bool_as_schema_version(self) -> None:
        doc = base_doc()
        doc["schema_version"] = True
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "VERSAO_INVALIDA")

    def test_18_rejects_unknown_top_level_field(self) -> None:
        doc = base_doc()
        doc["extra"] = 1
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "CAMPO_DESCONHECIDO")

    def test_19_rejects_missing_top_level_field(self) -> None:
        doc = base_doc()
        del doc["insumos"]
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "CAMPO_OBRIGATORIO")

    def test_20_rejects_non_brl_currency(self) -> None:
        doc = base_doc()
        doc["orcamento"]["moeda"] = "USD"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "MOEDA_INVALIDA")

    def test_21_rejects_equipment_bdi_greater_than_standard_bdi(self) -> None:
        doc = base_doc()
        doc["orcamento"]["bdi_padrao_percentual"] = "20"
        doc["orcamento"]["bdi_equipamentos_percentual"] = "25"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "BDI_INVALIDO")

    def test_22_rejects_duplicate_insumo_id(self) -> None:
        doc = base_doc()
        doc["insumos"].append(copy.deepcopy(doc["insumos"][0]))
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "ID_DUPLICADO")

    def test_23_rejects_encargos_on_material(self) -> None:
        doc = base_doc()
        doc["insumos"][0]["aplicar_encargos"] = True
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "ENCARGOS_NATUREZA_INVALIDA")

    def test_24_rejects_invalid_insumo_natureza(self) -> None:
        doc = base_doc()
        doc["insumos"][0]["natureza"] = "imposto"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "NATUREZA_INVALIDA")

    def test_25_rejects_zero_or_negative_insumo_price(self) -> None:
        doc = base_doc()
        doc["insumos"][0]["preco_unitario_centavos"] = 0
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "INTEIRO_INVALIDO")

    def test_26_rejects_collision_between_composicao_and_insumo_id(self) -> None:
        doc = base_doc()
        doc["composicoes"][0]["id"] = doc["insumos"][0]["id"]
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "ID_CONFLITANTE")

    def test_27_rejects_duplicate_component_in_same_composition(self) -> None:
        doc = base_doc()
        comp = doc["composicoes"][0]
        comp["componentes"].append(copy.deepcopy(comp["componentes"][0]))
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "COMPONENTE_DUPLICADO")

    def test_28_rejects_missing_insumo_reference(self) -> None:
        doc = base_doc()
        doc["composicoes"][0]["componentes"][0]["referencia_id"] = "ins-inexistente"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "INSUMO_NAO_ENCONTRADO")

    def test_29_rejects_missing_subcomposition_reference(self) -> None:
        doc = base_doc()
        doc["composicoes"][2]["componentes"][0]["referencia_id"] = "comp-inexistente"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "COMPOSICAO_NAO_ENCONTRADA")

    def test_30_detects_direct_self_loop_in_composition(self) -> None:
        doc = base_doc()
        cid = doc["composicoes"][0]["id"]
        doc["composicoes"][0]["componentes"].append(
            {
                "tipo": "composicao",
                "referencia_id": cid,
                "coeficiente": "1",
                "perda_percentual": "0",
            }
        )
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "CICLO_COMPOSICAO")
        self.assertIn(f"{cid} -> {cid}", ctx.exception.message)

    def test_31_detects_multi_hop_cycle_in_compositions(self) -> None:
        doc = base_doc()
        doc["composicoes"][0]["componentes"].append(
            {
                "tipo": "composicao",
                "referencia_id": "comp-base-equipamento-armada",
                "coeficiente": "0.1",
                "perda_percentual": "0",
            }
        )
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "CICLO_COMPOSICAO")

    def test_32_rejects_invalid_bdi_mode(self) -> None:
        doc = base_doc()
        doc["itens_orcamento"][0]["bdi_modo"] = "especial"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "BDI_MODO_INVALIDO")

    def test_33_rejects_zero_quantity_in_budget_item(self) -> None:
        doc = base_doc()
        doc["itens_orcamento"][0]["quantidade"] = "0"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "RACIONAL_INVALIDO")

    def test_34_rejects_leading_trailing_whitespace_in_label(self) -> None:
        doc = base_doc()
        doc["orcamento"]["titulo"] = "  Título com espaços "
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "TEXTO_INVALIDO")

    def test_35_rejects_control_characters_in_label(self) -> None:
        doc = base_doc()
        doc["insumos"][0]["descricao"] = "Cimento\x00CP2"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "TEXTO_INVALIDO")


class TestCoreCalculationAndInvariants(unittest.TestCase):
    def test_36_example_conservation_and_totals(self) -> None:
        doc = base_doc()
        rep = calcular_orcamento(doc)
        res = rep["resumo_geral"]
        self.assertTrue(res["conservacao_exata_direto"])
        self.assertEqual(res["custo_total_direto"], res["custo_explosao_insumos"])
        self.assertEqual(res["quantidade_insumos_catalogo"], 12)
        self.assertEqual(res["quantidade_insumos_utilizados"], 11)

    def test_37_input_document_is_not_mutated(self) -> None:
        doc = base_doc()
        snapshot = copy.deepcopy(doc)
        calcular_orcamento(doc)
        self.assertEqual(doc, snapshot)

    def test_38_single_labor_with_social_charges_and_standard_bdi(self) -> None:
        doc = {
            "schema_version": 1,
            "orcamento": {
                "id": "orc-simples",
                "titulo": "Teste Simples",
                "moeda": "BRL",
                "encargos_sociais_percentual": "80",
                "bdi_padrao_percentual": "25",
                "bdi_equipamentos_percentual": "10",
            },
            "insumos": [
                {
                    "id": "mo-1",
                    "descricao": "Oficial",
                    "unidade": "h",
                    "natureza": "mao_de_obra",
                    "preco_unitario_centavos": 2000,
                    "aplicar_encargos": True,
                }
            ],
            "composicoes": [
                {
                    "id": "comp-1",
                    "descricao": "Serviço A",
                    "unidade": "un",
                    "componentes": [
                        {
                            "tipo": "insumo",
                            "referencia_id": "mo-1",
                            "coeficiente": "2.5",
                            "perda_percentual": "0",
                        }
                    ],
                }
            ],
            "itens_orcamento": [
                {
                    "id": "item-1",
                    "etapa": "Etapa Única",
                    "composicao_id": "comp-1",
                    "quantidade": "4",
                    "bdi_modo": "padrao",
                }
            ],
        }
        rep = calcular_orcamento(doc)
        # 2000 * 1.80 = 3600 centavos/h; * 2.5 h/un = 9000 centavos/un; * 4 un = 36000 centavos direto
        # BDI 25% = 9000 centavos; total = 45000 centavos
        res = rep["resumo_geral"]
        self.assertEqual(res["custo_total_direto"]["centavos_arredondados"], 36000)
        self.assertEqual(res["valor_total_bdi"]["centavos_arredondados"], 9000)
        self.assertEqual(res["preco_total_orcamento"]["centavos_arredondados"], 45000)

    def test_39_differentiated_equipment_bdi_calculation(self) -> None:
        doc = {
            "schema_version": 1,
            "orcamento": {
                "id": "orc-bdi-dif",
                "titulo": "Teste BDI Diferenciado",
                "moeda": "BRL",
                "encargos_sociais_percentual": "0",
                "bdi_padrao_percentual": "30",
                "bdi_equipamentos_percentual": "10",
            },
            "insumos": [
                {
                    "id": "mat-1",
                    "descricao": "Cabo",
                    "unidade": "m",
                    "natureza": "material",
                    "preco_unitario_centavos": 10000,
                    "aplicar_encargos": False,
                },
                {
                    "id": "eq-1",
                    "descricao": "Transformador",
                    "unidade": "un",
                    "natureza": "equipamento",
                    "preco_unitario_centavos": 50000,
                    "aplicar_encargos": False,
                },
            ],
            "composicoes": [
                {
                    "id": "comp-inst",
                    "descricao": "Subestação",
                    "unidade": "un",
                    "componentes": [
                        {"tipo": "insumo", "referencia_id": "mat-1", "coeficiente": "1", "perda_percentual": "0"},
                        {"tipo": "insumo", "referencia_id": "eq-1", "coeficiente": "1", "perda_percentual": "0"},
                    ],
                }
            ],
            "itens_orcamento": [
                {
                    "id": "it-1",
                    "etapa": "Elétrica",
                    "composicao_id": "comp-inst",
                    "quantidade": "1",
                    "bdi_modo": "diferenciado_equipamentos",
                }
            ],
        }
        rep = calcular_orcamento(doc)
        # Material 10000 * 30% = 3000; Equipamento 50000 * 10% = 5000 -> BDI = 8000; Total = 68000
        self.assertEqual(rep["resumo_geral"]["valor_total_bdi"]["centavos_arredondados"], 8000)
        self.assertEqual(rep["resumo_geral"]["preco_total_orcamento"]["centavos_arredondados"], 68000)

    def test_40_exempt_bdi_mode(self) -> None:
        doc = base_doc()
        for it in doc["itens_orcamento"]:
            it["bdi_modo"] = "isento"
        rep = calcular_orcamento(doc)
        self.assertEqual(rep["resumo_geral"]["valor_total_bdi"]["centavos_arredondados"], 0)
        self.assertEqual(
            rep["resumo_geral"]["custo_total_direto"]["numerador"],
            rep["resumo_geral"]["preco_total_orcamento"]["numerador"],
        )

    def test_41_pareto_shares_sum_to_exactly_one(self) -> None:
        rep = calcular_orcamento(base_doc())
        total_share = sum(
            Fraction(int(x["participacao_direta"]["numerador"]), int(x["participacao_direta"]["denominador"]))
            for x in rep["explosao_insumos"]
        )
        self.assertEqual(total_share, Fraction(1, 1))
        last = rep["explosao_insumos"][-1]["participacao_acumulada"]
        self.assertEqual((last["numerador"], last["denominador"]), ("1", "1"))


class TestReportsAndCli(unittest.TestCase):
    def test_42_csv_formula_escaping(self) -> None:
        for leader in ("=SUM(A1)", "+10", "-5", "@cmd", "\tcol"):
            self.assertEqual(safe_csv_cell(leader), "'" + leader)
        self.assertEqual(safe_csv_cell("Texto normal"), "Texto normal")

    def test_43_render_reports_and_svg(self) -> None:
        rep = calcular_orcamento(base_doc())
        itens_csv = render_itens_csv(rep)
        ins_csv = render_insumos_abc_csv(rep)
        md = render_markdown(rep)
        svg = render_svg(rep)
        self.assertIn("custo_total_direto_centavos", itens_csv)
        self.assertIn("participacao_acumulada_percentual", ins_csv)
        self.assertIn("Relatório Analítico de Orçamento", md)
        self.assertTrue(svg.startswith("<svg") and svg.strip().endswith("</svg>"))

    def test_44_write_bundle_zip_and_refuse_overwrite(self) -> None:
        raw = EXAMPLE_PATH.read_bytes()
        rep = calcular_orcamento(loads(raw))
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "pacote.zip"
            hashes = write_bundle_zip(out, raw, rep)
            self.assertEqual(len(hashes), 7)
            self.assertTrue(out.is_file())
            with self.assertRaises(OrcamentoError) as ctx:
                write_bundle_zip(out, raw, rep)
            self.assertEqual(ctx.exception.code, "DESTINO_EXISTENTE")

    def test_45_cli_exemplo_and_calcular(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            z1 = tmp / "ex.zip"
            rc1 = cli_main(["exemplo", "--saida", str(z1)])
            self.assertEqual(rc1, 0)
            self.assertTrue(z1.is_file())

            z2 = tmp / "calc.zip"
            rc2 = cli_main(["calcular", str(EXAMPLE_PATH), "--saida", str(z2)])
            self.assertEqual(rc2, 0)
            self.assertEqual(z1.read_bytes(), z2.read_bytes())

    def test_46_cli_returns_2_on_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad = Path(tmpdir) / "bad.json"
            bad.write_text('{"schema_version": 99}', encoding="utf-8")
            out = Path(tmpdir) / "out.zip"
            rc = cli_main(["calcular", str(bad), "--saida", str(out)])
            self.assertEqual(rc, 2)
            self.assertFalse(out.exists())

    def test_47_cli_rejects_symlink_input(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("Symlinks não suportados.")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            link = tmp / "link.json"
            os.symlink(EXAMPLE_PATH, link)
            out = tmp / "out.zip"
            rc = cli_main(["calcular", str(link), "--saida", str(out)])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()

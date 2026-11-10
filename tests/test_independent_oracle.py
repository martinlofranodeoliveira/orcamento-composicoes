"""Testes do verificador independente e de casos de borda algébricos."""
from __future__ import annotations

import copy
from fractions import Fraction
import importlib.util
from pathlib import Path
import tempfile
import unittest

from orcamento_composicoes import OrcamentoError, calcular_orcamento, loads
from orcamento_composicoes.cli import main as cli_main

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PATH = ROOT / "src" / "orcamento_composicoes" / "data" / "exemplo.json"

SPEC = importlib.util.spec_from_file_location("verify_independent", ROOT / "tools" / "verify_independent.py")
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def base_doc() -> dict:
    return loads(EXAMPLE_PATH.read_bytes())


class TestIndependentOracleAndEdgeCases(unittest.TestCase):
    def test_01_independent_verifier_accepts_example_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            zpath = Path(tmpdir) / "exemplo.zip"
            rc = cli_main(["exemplo", "--saida", str(zpath)])
            self.assertEqual(rc, 0)
            result = verifier.verify_zip_bundle(zpath)
            self.assertTrue(result["ok"])
            self.assertEqual(result["itensVerificados"], 4)
            self.assertEqual(result["insumosExplodidosVerificados"], 11)

    def test_02_deep_3_level_composition_dag(self) -> None:
        doc = {
            "schema_version": 1,
            "orcamento": {
                "id": "dag-3",
                "titulo": "DAG 3 Níveis",
                "moeda": "BRL",
                "encargos_sociais_percentual": "50",
                "bdi_padrao_percentual": "20",
                "bdi_equipamentos_percentual": "10",
            },
            "insumos": [
                {
                    "id": "i1",
                    "descricao": "Insumo Base",
                    "unidade": "kg",
                    "natureza": "material",
                    "preco_unitario_centavos": 1000,
                    "aplicar_encargos": False,
                }
            ],
            "composicoes": [
                {
                    "id": "c1",
                    "descricao": "Nível 1",
                    "unidade": "un",
                    "componentes": [
                        {"tipo": "insumo", "referencia_id": "i1", "coeficiente": "2", "perda_percentual": "0"}
                    ],
                },
                {
                    "id": "c2",
                    "descricao": "Nível 2",
                    "unidade": "un",
                    "componentes": [
                        {"tipo": "composicao", "referencia_id": "c1", "coeficiente": "3", "perda_percentual": "0"}
                    ],
                },
                {
                    "id": "c3",
                    "descricao": "Nível 3",
                    "unidade": "un",
                    "componentes": [
                        {"tipo": "composicao", "referencia_id": "c2", "coeficiente": "4", "perda_percentual": "0"}
                    ],
                },
            ],
            "itens_orcamento": [
                {
                    "id": "it1",
                    "etapa": "Única",
                    "composicao_id": "c3",
                    "quantidade": "5",
                    "bdi_modo": "padrao",
                }
            ],
        }
        rep = calcular_orcamento(doc)
        # 2 * 3 * 4 * 5 = 120 kg * 1000 = 120_000 centavos direto; BDI 20% = 24_000; Total = 144_000
        self.assertEqual(rep["resumo_geral"]["custo_total_direto"]["centavos_arredondados"], 120_000)
        self.assertEqual(rep["explosao_insumos"][0]["quantidade_total"]["centavos_arredondados"], 120)
        self.assertEqual(rep["resumo_geral"]["preco_total_orcamento"]["centavos_arredondados"], 144_000)

    def test_03_diamond_dag_accumulates_both_branches(self) -> None:
        doc = {
            "schema_version": 1,
            "orcamento": {
                "id": "diamond",
                "titulo": "Grafo Diamante",
                "moeda": "BRL",
                "encargos_sociais_percentual": "0",
                "bdi_padrao_percentual": "0",
                "bdi_equipamentos_percentual": "0",
            },
            "insumos": [
                {
                    "id": "areia",
                    "descricao": "Areia",
                    "unidade": "m3",
                    "natureza": "material",
                    "preco_unitario_centavos": 10000,
                    "aplicar_encargos": False,
                }
            ],
            "composicoes": [
                {
                    "id": "base",
                    "descricao": "Base",
                    "unidade": "m3",
                    "componentes": [
                        {"tipo": "insumo", "referencia_id": "areia", "coeficiente": "0.5", "perda_percentual": "0"}
                    ],
                },
                {
                    "id": "left",
                    "descricao": "Ramo Esquerdo",
                    "unidade": "m3",
                    "componentes": [
                        {"tipo": "composicao", "referencia_id": "base", "coeficiente": "2", "perda_percentual": "0"}
                    ],
                },
                {
                    "id": "right",
                    "descricao": "Ramo Direito",
                    "unidade": "m3",
                    "componentes": [
                        {"tipo": "composicao", "referencia_id": "base", "coeficiente": "4", "perda_percentual": "0"}
                    ],
                },
                {
                    "id": "top",
                    "descricao": "Topo",
                    "unidade": "un",
                    "componentes": [
                        {"tipo": "composicao", "referencia_id": "left", "coeficiente": "1", "perda_percentual": "0"},
                        {"tipo": "composicao", "referencia_id": "right", "coeficiente": "1", "perda_percentual": "0"},
                    ],
                },
            ],
            "itens_orcamento": [
                {
                    "id": "item-top",
                    "etapa": "Diamante",
                    "composicao_id": "top",
                    "quantidade": "1",
                    "bdi_modo": "isento",
                }
            ],
        }
        rep = calcular_orcamento(doc)
        # (2 * 0.5) + (4 * 0.5) = 3 m3 of areia -> 30000 centavos
        self.assertEqual(rep["explosao_insumos"][0]["quantidade_total"]["decimal_4"], "3.0000")
        self.assertEqual(rep["resumo_geral"]["custo_total_direto"]["centavos_arredondados"], 30000)

    def test_04_waste_percentage_exact_fraction(self) -> None:
        doc = base_doc()
        rep = calcular_orcamento(doc)
        # Verify all fractions in report have positive integer denominators
        for comp in rep["composicoes"]:
            self.assertGreater(int(comp["custo_unitario_direto"]["denominador"]), 0)
        for it in rep["itens_orcamento"]:
            self.assertGreater(int(it["preco_total"]["denominador"]), 0)

    def test_05_rejects_duplicate_budget_item_id(self) -> None:
        doc = base_doc()
        doc["itens_orcamento"].append(copy.deepcopy(doc["itens_orcamento"][0]))
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "ID_DUPLICADO")

    def test_06_rejects_missing_composition_in_budget_item(self) -> None:
        doc = base_doc()
        doc["itens_orcamento"][0]["composicao_id"] = "comp-fantasma"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "COMPOSICAO_NAO_ENCONTRADA")

    def test_07_rejects_invalid_rational_string(self) -> None:
        doc = base_doc()
        doc["itens_orcamento"][0]["quantidade"] = "12,5"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "RACIONAL_INVALIDO")

    def test_08_rejects_negative_rational_int(self) -> None:
        doc = base_doc()
        doc["itens_orcamento"][0]["quantidade"] = -5
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "RACIONAL_INVALIDO")

    def test_09_rejects_invalid_component_type(self) -> None:
        doc = base_doc()
        doc["composicoes"][0]["componentes"][0]["tipo"] = "outro"
        with self.assertRaises(OrcamentoError) as ctx:
            calcular_orcamento(doc)
        self.assertEqual(ctx.exception.code, "TIPO_COMPONENTE_INVALIDO")

    def test_10_rejects_nonexistent_parent_dir_for_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_out = Path(tmpdir) / "nao_existe" / "out.zip"
            rc = cli_main(["exemplo", "--saida", str(missing_out)])
            self.assertEqual(rc, 2)

    def test_11_pareto_tie_breaker_by_ascii_id(self) -> None:
        doc = {
            "schema_version": 1,
            "orcamento": {
                "id": "empate",
                "titulo": "Empate ABC",
                "moeda": "BRL",
                "encargos_sociais_percentual": "0",
                "bdi_padrao_percentual": "0",
                "bdi_equipamentos_percentual": "0",
            },
            "insumos": [
                {
                    "id": "ins-b",
                    "descricao": "Insumo B",
                    "unidade": "un",
                    "natureza": "material",
                    "preco_unitario_centavos": 1000,
                    "aplicar_encargos": False,
                },
                {
                    "id": "ins-a",
                    "descricao": "Insumo A",
                    "unidade": "un",
                    "natureza": "material",
                    "preco_unitario_centavos": 1000,
                    "aplicar_encargos": False,
                },
            ],
            "composicoes": [
                {
                    "id": "comp-u",
                    "descricao": "Composição Única",
                    "unidade": "un",
                    "componentes": [
                        {"tipo": "insumo", "referencia_id": "ins-b", "coeficiente": "1", "perda_percentual": "0"},
                        {"tipo": "insumo", "referencia_id": "ins-a", "coeficiente": "1", "perda_percentual": "0"},
                    ],
                }
            ],
            "itens_orcamento": [
                {
                    "id": "it-u",
                    "etapa": "Etapa",
                    "composicao_id": "comp-u",
                    "quantidade": "1",
                    "bdi_modo": "isento",
                }
            ],
        }
        rep = calcular_orcamento(doc)
        ids = [x["id"] for x in rep["explosao_insumos"]]
        self.assertEqual(ids, ["ins-a", "ins-b"])

    def test_12_abc_classes_a_b_c_assigned_by_cumulative_threshold(self) -> None:
        doc = {
            "schema_version": 1,
            "orcamento": {
                "id": "abc-3",
                "titulo": "Três Classes ABC",
                "moeda": "BRL",
                "encargos_sociais_percentual": "0",
                "bdi_padrao_percentual": "0",
                "bdi_equipamentos_percentual": "0",
            },
            "insumos": [
                {"id": "i-a", "descricao": "Item A", "unidade": "un", "natureza": "material", "preco_unitario_centavos": 8500, "aplicar_encargos": False},
                {"id": "i-b", "descricao": "Item B", "unidade": "un", "natureza": "material", "preco_unitario_centavos": 1200, "aplicar_encargos": False},
                {"id": "i-c", "descricao": "Item C", "unidade": "un", "natureza": "material", "preco_unitario_centavos": 300, "aplicar_encargos": False},
            ],
            "composicoes": [
                {
                    "id": "c-abc",
                    "descricao": "Mix ABC",
                    "unidade": "un",
                    "componentes": [
                        {"tipo": "insumo", "referencia_id": "i-a", "coeficiente": "1", "perda_percentual": "0"},
                        {"tipo": "insumo", "referencia_id": "i-b", "coeficiente": "1", "perda_percentual": "0"},
                        {"tipo": "insumo", "referencia_id": "i-c", "coeficiente": "1", "perda_percentual": "0"},
                    ],
                }
            ],
            "itens_orcamento": [
                {"id": "it-abc", "etapa": "Etapa", "composicao_id": "c-abc", "quantidade": "1", "bdi_modo": "isento"}
            ],
        }
        rep = calcular_orcamento(doc)
        classes = [x["classe_abc"] for x in rep["explosao_insumos"]]
        self.assertEqual(classes, ["A", "B", "C"])


if __name__ == "__main__":
    unittest.main()

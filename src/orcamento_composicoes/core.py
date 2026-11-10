"""Motor de orçamento analítico por composições de preços unitários (CPU), BDI e explosão de insumos."""
from __future__ import annotations

from fractions import Fraction
import re
from typing import Any

from .errors import OrcamentoError

SCHEMA_VERSION = 1
MAX_INSUMOS = 2_000
MAX_COMPOSICOES = 1_000
MAX_COMPONENTES_POR_COMPOSICAO = 200
MAX_ITENS_ORCAMENTO = 1_000
MAX_CENTAVOS = 1_000_000_000_000
MAX_RATIONAL_DIGITS = 18

NATUREZAS_VALIDAS = ("material", "mao_de_obra", "equipamento", "servico_terceiro")
BDI_MODOS_VALIDOS = ("padrao", "diferenciado_equipamentos", "isento")

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,8})?\Z", re.ASCII)


def _require(condition: bool, code: str, message: str, path: str = "$") -> None:
    if not condition:
        raise OrcamentoError(code, message, path)


def _check_dict(obj: Any, expected_keys: set[str], path: str) -> dict[str, Any]:
    _require(type(obj) is dict, "FORMATO_INVALIDO", "Esperado objeto JSON.", path)
    actual = set(obj.keys())
    missing = sorted(expected_keys - actual)
    extra = sorted(actual - expected_keys)
    _require(not missing, "CAMPO_OBRIGATORIO", f"Campos obrigatórios ausentes: {', '.join(missing)}.", path)
    _require(not extra, "CAMPO_DESCONHECIDO", f"Campos desconhecidos: {', '.join(extra)}.", path)
    return obj


def _check_id(value: Any, path: str) -> str:
    _require(
        type(value) is str and _ID_RE.fullmatch(value) is not None,
        "ID_INVALIDO",
        "Identificador deve ser ASCII alfanumérico (1..64 caracteres).",
        path,
    )
    return value


def _check_label(value: Any, path: str, max_len: int = 160) -> str:
    _require(
        type(value) is str and 1 <= len(value) <= max_len and value == value.strip(),
        "TEXTO_INVALIDO",
        f"Texto deve ter entre 1 e {max_len} caracteres sem espaços nas extremidades.",
        path,
    )
    _require(
        not any(ord(c) < 32 or ord(c) == 127 or (0xD800 <= ord(c) <= 0xDFFF) for c in value),
        "TEXTO_INVALIDO",
        "Texto contém caracteres de controle ou substitutos inválidos.",
        path,
    )
    return value


def _check_int(value: Any, min_val: int, max_val: int, path: str) -> int:
    _require(
        type(value) is int and min_val <= value <= max_val,
        "INTEIRO_INVALIDO",
        f"Esperado inteiro entre {min_val} e {max_val}.",
        path,
    )
    return value


def _parse_rational(value: Any, *, allow_zero: bool, max_val: Fraction, path: str) -> Fraction:
    if type(value) is int:
        _require(value >= 0, "RACIONAL_INVALIDO", "Valor racional não pode ser negativo.", path)
        frac = Fraction(value, 1)
    elif type(value) is str:
        _require(
            _DECIMAL_RE.fullmatch(value) is not None,
            "RACIONAL_INVALIDO",
            "Texto racional deve usar dígitos ASCII e ponto decimal opcional (até 8 casas).",
            path,
        )
        frac = Fraction(value)
    else:
        raise OrcamentoError(
            "RACIONAL_INVALIDO",
            "Valor racional deve ser inteiro ou texto decimal estrito.",
            path,
        )
    if not allow_zero:
        _require(frac > 0, "RACIONAL_INVALIDO", "Valor racional deve ser estritamente positivo.", path)
    _require(frac <= max_val, "LIMITE_EXCEDIDO", "Valor racional excede o limite permitido.", path)
    return frac


def round_half_even_int(value: Fraction) -> int:
    """Arredonda Fraction para o inteiro mais próximo (empate para o par)."""
    return int(round(value))


def format_decimal(value: Fraction, places: int = 4) -> str:
    """Formata Fraction com número fixo de casas decimais usando arredondamento half-even."""
    scale = 10**places
    scaled = round_half_even_int(value * scale)
    sign = "-" if scaled < 0 else ""
    scaled = abs(scaled)
    whole, rem = divmod(scaled, scale)
    if places == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{rem:0{places}d}"


def rational_dict(value: Fraction) -> dict[str, Any]:
    """Representação JSON auditável de um racional exato."""
    return {
        "numerador": str(value.numerator),
        "denominador": str(value.denominator),
        "decimal_4": format_decimal(value, 4),
        "centavos_arredondados": round_half_even_int(value),
    }


def calcular_orcamento(documento: Any) -> dict[str, Any]:
    """Valida e calcula o orçamento analítico, BDI, explosão de insumos e curva ABC."""
    doc = _check_dict(
        documento,
        {"schema_version", "orcamento", "insumos", "composicoes", "itens_orcamento"},
        "$",
    )
    _require(
        type(doc["schema_version"]) is int and doc["schema_version"] == SCHEMA_VERSION,
        "VERSAO_INVALIDA",
        "schema_version deve ser o inteiro 1.",
        "$.schema_version",
    )

    orc = _check_dict(
        doc["orcamento"],
        {
            "id",
            "titulo",
            "moeda",
            "encargos_sociais_percentual",
            "bdi_padrao_percentual",
            "bdi_equipamentos_percentual",
        },
        "$.orcamento",
    )
    orc_id = _check_id(orc["id"], "$.orcamento.id")
    orc_titulo = _check_label(orc["titulo"], "$.orcamento.titulo")
    _require(orc["moeda"] == "BRL", "MOEDA_INVALIDA", "Apenas a moeda BRL é suportada.", "$.orcamento.moeda")
    encargos_pct = _parse_rational(
        orc["encargos_sociais_percentual"],
        allow_zero=True,
        max_val=Fraction(500, 1),
        path="$.orcamento.encargos_sociais_percentual",
    )
    bdi_padrao_pct = _parse_rational(
        orc["bdi_padrao_percentual"],
        allow_zero=True,
        max_val=Fraction(500, 1),
        path="$.orcamento.bdi_padrao_percentual",
    )
    bdi_equip_pct = _parse_rational(
        orc["bdi_equipamentos_percentual"],
        allow_zero=True,
        max_val=Fraction(500, 1),
        path="$.orcamento.bdi_equipamentos_percentual",
    )
    _require(
        bdi_equip_pct <= bdi_padrao_pct,
        "BDI_INVALIDO",
        "O BDI diferenciado de equipamentos não pode superar o BDI padrão.",
        "$.orcamento.bdi_equipamentos_percentual",
    )

    raw_insumos = doc["insumos"]
    _require(type(raw_insumos) is list, "FORMATO_INVALIDO", "insumos deve ser uma lista.", "$.insumos")
    _require(1 <= len(raw_insumos) <= MAX_INSUMOS, "LIMITE_EXCEDIDO", "Quantidade de insumos fora do limite.", "$.insumos")

    insumos_map: dict[str, dict[str, Any]] = {}
    for idx, raw_ins in enumerate(raw_insumos):
        ipath = f"$.insumos[{idx}]"
        ins = _check_dict(
            raw_ins,
            {"id", "descricao", "unidade", "natureza", "preco_unitario_centavos", "aplicar_encargos"},
            ipath,
        )
        ins_id = _check_id(ins["id"], f"{ipath}.id")
        _require(ins_id not in insumos_map, "ID_DUPLICADO", f"Insumo duplicado: {ins_id}.", f"{ipath}.id")
        descricao = _check_label(ins["descricao"], f"{ipath}.descricao")
        unidade = _check_label(ins["unidade"], f"{ipath}.unidade", max_len=16)
        natureza = ins["natureza"]
        _require(
            type(natureza) is str and natureza in NATUREZAS_VALIDAS,
            "NATUREZA_INVALIDA",
            f"Natureza inválida: {natureza}.",
            f"{ipath}.natureza",
        )
        preco_base = _check_int(ins["preco_unitario_centavos"], 1, MAX_CENTAVOS, f"{ipath}.preco_unitario_centavos")
        aplicar_enc = ins["aplicar_encargos"]
        _require(type(aplicar_enc) is bool, "FORMATO_INVALIDO", "aplicar_encargos deve ser booleano.", f"{ipath}.aplicar_encargos")
        if aplicar_enc and natureza != "mao_de_obra":
            raise OrcamentoError(
                "ENCARGOS_NATUREZA_INVALIDA",
                "Encargos sociais só podem ser aplicados à natureza mao_de_obra.",
                f"{ipath}.aplicar_encargos",
            )
        fator_encargos = Fraction(1, 1) + (encargos_pct / Fraction(100, 1)) if aplicar_enc else Fraction(1, 1)
        custo_efetivo = Fraction(preco_base, 1) * fator_encargos
        insumos_map[ins_id] = {
            "id": ins_id,
            "descricao": descricao,
            "unidade": unidade,
            "natureza": natureza,
            "preco_unitario_centavos": preco_base,
            "aplicar_encargos": aplicar_enc,
            "custo_unitario_efetivo": custo_efetivo,
        }

    raw_composicoes = doc["composicoes"]
    _require(type(raw_composicoes) is list, "FORMATO_INVALIDO", "composicoes deve ser uma lista.", "$.composicoes")
    _require(
        1 <= len(raw_composicoes) <= MAX_COMPOSICOES,
        "LIMITE_EXCEDIDO",
        "Quantidade de composições fora do limite.",
        "$.composicoes",
    )

    composicoes_raw_map: dict[str, dict[str, Any]] = {}
    for idx, raw_comp in enumerate(raw_composicoes):
        cpath = f"$.composicoes[{idx}]"
        comp = _check_dict(raw_comp, {"id", "descricao", "unidade", "componentes"}, cpath)
        comp_id = _check_id(comp["id"], f"{cpath}.id")
        _require(comp_id not in composicoes_raw_map, "ID_DUPLICADO", f"Composição duplicada: {comp_id}.", f"{cpath}.id")
        _require(
            comp_id not in insumos_map,
            "ID_CONFLITANTE",
            f"Identificador de composição colide com insumo: {comp_id}.",
            f"{cpath}.id",
        )
        descricao = _check_label(comp["descricao"], f"{cpath}.descricao")
        unidade = _check_label(comp["unidade"], f"{cpath}.unidade", max_len=16)
        raw_componentes = comp["componentes"]
        _require(type(raw_componentes) is list, "FORMATO_INVALIDO", "componentes deve ser uma lista.", f"{cpath}.componentes")
        _require(
            1 <= len(raw_componentes) <= MAX_COMPONENTES_POR_COMPOSICAO,
            "LIMITE_EXCEDIDO",
            "Quantidade de componentes da composição fora do limite.",
            f"{cpath}.componentes",
        )
        seen_refs: set[tuple[str, str]] = set()
        parsed_componentes: list[dict[str, Any]] = []
        for k, raw_item in enumerate(raw_componentes):
            kpath = f"{cpath}.componentes[{k}]"
            citem = _check_dict(raw_item, {"tipo", "referencia_id", "coeficiente", "perda_percentual"}, kpath)
            tipo = citem["tipo"]
            _require(
                tipo in ("insumo", "composicao"),
                "TIPO_COMPONENTE_INVALIDO",
                "tipo do componente deve ser 'insumo' ou 'composicao'.",
                f"{kpath}.tipo",
            )
            ref_id = _check_id(citem["referencia_id"], f"{kpath}.referencia_id")
            pair_key = (tipo, ref_id)
            _require(
                pair_key not in seen_refs,
                "COMPONENTE_DUPLICADO",
                f"Referência repetida na mesma composição: {tipo}:{ref_id}.",
                f"{kpath}.referencia_id",
            )
            seen_refs.add(pair_key)
            coef = _parse_rational(
                citem["coeficiente"],
                allow_zero=False,
                max_val=Fraction(1_000_000, 1),
                path=f"{kpath}.coeficiente",
            )
            perda = _parse_rational(
                citem["perda_percentual"],
                allow_zero=True,
                max_val=Fraction(500, 1),
                path=f"{kpath}.perda_percentual",
            )
            fator_total = coef * (Fraction(1, 1) + perda / Fraction(100, 1))
            parsed_componentes.append(
                {
                    "tipo": tipo,
                    "referencia_id": ref_id,
                    "coeficiente": coef,
                    "perda_percentual": perda,
                    "fator_efetivo": fator_total,
                    "path": kpath,
                }
            )
        composicoes_raw_map[comp_id] = {
            "id": comp_id,
            "descricao": descricao,
            "unidade": unidade,
            "componentes": parsed_componentes,
        }

    # Check references in compositions
    for comp_id, comp_data in composicoes_raw_map.items():
        for comp_item in comp_data["componentes"]:
            ref_id = comp_item["referencia_id"]
            if comp_item["tipo"] == "insumo":
                _require(
                    ref_id in insumos_map,
                    "INSUMO_NAO_ENCONTRADO",
                    f"Insumo referenciado não existe: {ref_id}.",
                    f"{comp_item['path']}.referencia_id",
                )
            else:
                _require(
                    ref_id in composicoes_raw_map,
                    "COMPOSICAO_NAO_ENCONTRADA",
                    f"Composição auxiliar referenciada não existe: {ref_id}.",
                    f"{comp_item['path']}.referencia_id",
                )

    # Detect cycles in composition dependency graph deterministically
    state: dict[str, int] = {cid: 0 for cid in composicoes_raw_map}
    stack: list[str] = []
    topo_order: list[str] = []

    def dfs(cid: str) -> None:
        state[cid] = 1
        stack.append(cid)
        sub_refs = sorted(
            c["referencia_id"]
            for c in composicoes_raw_map[cid]["componentes"]
            if c["tipo"] == "composicao"
        )
        for nxt in sub_refs:
            if state[nxt] == 1:
                idx_start = stack.index(nxt)
                cycle = stack[idx_start:] + [nxt]
                raise OrcamentoError(
                    "CICLO_COMPOSICAO",
                    f"Ciclo detectado entre composições: {' -> '.join(cycle)}.",
                    "$.composicoes",
                )
            if state[nxt] == 0:
                dfs(nxt)
        stack.pop()
        state[cid] = 2
        topo_order.append(cid)

    for cid in sorted(composicoes_raw_map):
        if state[cid] == 0:
            dfs(cid)

    # Evaluate compositions in bottom-up topological order
    composicoes_calc: dict[str, dict[str, Any]] = {}
    for cid in topo_order:
        cdata = composicoes_raw_map[cid]
        por_natureza: dict[str, Fraction] = {n: Fraction(0, 1) for n in NATUREZAS_VALIDAS}
        insumos_equivalentes: dict[str, Fraction] = {}
        componentes_detalhados: list[dict[str, Any]] = []

        for citem in cdata["componentes"]:
            fator = citem["fator_efetivo"]
            ref_id = citem["referencia_id"]
            if citem["tipo"] == "insumo":
                ins = insumos_map[ref_id]
                custo_comp = fator * ins["custo_unitario_efetivo"]
                por_natureza[ins["natureza"]] += custo_comp
                insumos_equivalentes[ref_id] = insumos_equivalentes.get(ref_id, Fraction(0, 1)) + fator
                componentes_detalhados.append(
                    {
                        "tipo": "insumo",
                        "referencia_id": ref_id,
                        "descricao": ins["descricao"],
                        "unidade": ins["unidade"],
                        "coeficiente": format_decimal(citem["coeficiente"], 4),
                        "perda_percentual": format_decimal(citem["perda_percentual"], 4),
                        "fator_efetivo": rational_dict(fator),
                        "custo_unitario_origem": rational_dict(ins["custo_unitario_efetivo"]),
                        "custo_total_componente": rational_dict(custo_comp),
                    }
                )
            else:
                sub = composicoes_calc[ref_id]
                custo_comp = fator * sub["_custo_total_frac"]
                for nat in NATUREZAS_VALIDAS:
                    por_natureza[nat] += fator * sub["_por_natureza_frac"][nat]
                for iid, qtd_sub in sub["_insumos_eq_frac"].items():
                    insumos_equivalentes[iid] = insumos_equivalentes.get(iid, Fraction(0, 1)) + (fator * qtd_sub)
                componentes_detalhados.append(
                    {
                        "tipo": "composicao",
                        "referencia_id": ref_id,
                        "descricao": sub["descricao"],
                        "unidade": sub["unidade"],
                        "coeficiente": format_decimal(citem["coeficiente"], 4),
                        "perda_percentual": format_decimal(citem["perda_percentual"], 4),
                        "fator_efetivo": rational_dict(fator),
                        "custo_unitario_origem": rational_dict(sub["_custo_total_frac"]),
                        "custo_total_componente": rational_dict(custo_comp),
                    }
                )

        custo_total_comp = sum(por_natureza.values(), Fraction(0, 1))
        composicoes_calc[cid] = {
            "id": cid,
            "descricao": cdata["descricao"],
            "unidade": cdata["unidade"],
            "custo_unitario_direto": rational_dict(custo_total_comp),
            "por_natureza": {nat: rational_dict(por_natureza[nat]) for nat in NATUREZAS_VALIDAS},
            "componentes": componentes_detalhados,
            "_custo_total_frac": custo_total_comp,
            "_por_natureza_frac": por_natureza,
            "_insumos_eq_frac": insumos_equivalentes,
        }

    # Validate and evaluate budget items (itens_orcamento)
    raw_itens = doc["itens_orcamento"]
    _require(type(raw_itens) is list, "FORMATO_INVALIDO", "itens_orcamento deve ser uma lista.", "$.itens_orcamento")
    _require(
        1 <= len(raw_itens) <= MAX_ITENS_ORCAMENTO,
        "LIMITE_EXCEDIDO",
        "Quantidade de itens do orçamento fora do limite.",
        "$.itens_orcamento",
    )

    seen_item_ids: set[str] = set()
    itens_calculados: list[dict[str, Any]] = []
    demanda_global_insumos: dict[str, Fraction] = {iid: Fraction(0, 1) for iid in insumos_map}
    totais_natureza_direto: dict[str, Fraction] = {nat: Fraction(0, 1) for nat in NATUREZAS_VALIDAS}
    total_direto_exato = Fraction(0, 1)
    total_bdi_exato = Fraction(0, 1)
    total_preco_exato = Fraction(0, 1)

    for idx, raw_it in enumerate(raw_itens):
        itpath = f"$.itens_orcamento[{idx}]"
        it = _check_dict(raw_it, {"id", "etapa", "composicao_id", "quantidade", "bdi_modo"}, itpath)
        item_id = _check_id(it["id"], f"{itpath}.id")
        _require(item_id not in seen_item_ids, "ID_DUPLICADO", f"Item de orçamento duplicado: {item_id}.", f"{itpath}.id")
        seen_item_ids.add(item_id)
        etapa = _check_label(it["etapa"], f"{itpath}.etapa")
        comp_id = _check_id(it["composicao_id"], f"{itpath}.composicao_id")
        _require(
            comp_id in composicoes_calc,
            "COMPOSICAO_NAO_ENCONTRADA",
            f"Composição referenciada pelo item não existe: {comp_id}.",
            f"{itpath}.composicao_id",
        )
        quantidade = _parse_rational(
            it["quantidade"],
            allow_zero=False,
            max_val=Fraction(1_000_000, 1),
            path=f"{itpath}.quantidade",
        )
        bdi_modo = it["bdi_modo"]
        _require(
            type(bdi_modo) is str and bdi_modo in BDI_MODOS_VALIDOS,
            "BDI_MODO_INVALIDO",
            f"Modo de BDI inválido: {bdi_modo}.",
            f"{itpath}.bdi_modo",
        )

        comp = composicoes_calc[comp_id]
        custo_unit_direto = comp["_custo_total_frac"]
        custo_direto_item = quantidade * custo_unit_direto

        # Decompose direct cost by nature for this budget item
        item_natureza: dict[str, Fraction] = {}
        for nat in NATUREZAS_VALIDAS:
            val_nat = quantidade * comp["_por_natureza_frac"][nat]
            item_natureza[nat] = val_nat
            totais_natureza_direto[nat] += val_nat

        if bdi_modo == "isento":
            bdi_item = Fraction(0, 1)
        elif bdi_modo == "padrao":
            bdi_item = custo_direto_item * (bdi_padrao_pct / Fraction(100, 1))
        else:
            # diferenciado_equipamentos: equipamentos usam bdi_equip_pct, demais usam bdi_padrao_pct
            custo_equip = item_natureza["equipamento"]
            custo_outros = custo_direto_item - custo_equip
            bdi_item = (custo_outros * (bdi_padrao_pct / Fraction(100, 1))) + (
                custo_equip * (bdi_equip_pct / Fraction(100, 1))
            )

        preco_final_item = custo_direto_item + bdi_item
        total_direto_exato += custo_direto_item
        total_bdi_exato += bdi_item
        total_preco_exato += preco_final_item

        for iid, coef_eq in comp["_insumos_eq_frac"].items():
            demanda_global_insumos[iid] += quantidade * coef_eq

        itens_calculados.append(
            {
                "id": item_id,
                "etapa": etapa,
                "composicao_id": comp_id,
                "descricao": comp["descricao"],
                "unidade": comp["unidade"],
                "quantidade": rational_dict(quantidade),
                "bdi_modo": bdi_modo,
                "custo_unitario_direto": rational_dict(custo_unit_direto),
                "custo_total_direto": rational_dict(custo_direto_item),
                "valor_bdi": rational_dict(bdi_item),
                "preco_total": rational_dict(preco_final_item),
                "por_natureza_direto": {nat: rational_dict(item_natureza[nat]) for nat in NATUREZAS_VALIDAS},
                "_preco_total_frac": preco_final_item,
            }
        )

    # Compute item shares in total budget price
    for item_entry in itens_calculados:
        part = item_entry["_preco_total_frac"] / total_preco_exato if total_preco_exato > 0 else Fraction(0, 1)
        item_entry["participacao_orcamento_percentual"] = format_decimal(part * 100, 4)
        del item_entry["_preco_total_frac"]

    # Build Global Input Explosion (explosao_insumos) and ABC Pareto ranking
    active_insumos: list[tuple[Fraction, str, dict[str, Any]]] = []
    soma_explosao_direto = Fraction(0, 1)
    for iid, ins in insumos_map.items():
        qtd_total = demanda_global_insumos[iid]
        if qtd_total > 0:
            custo_total_ins = qtd_total * ins["custo_unitario_efetivo"]
            soma_explosao_direto += custo_total_ins
            active_insumos.append((custo_total_ins, iid, ins))

    # Fundamental conservation invariant: sum of direct costs of budget items == sum of exploded inputs
    _require(
        soma_explosao_direto == total_direto_exato,
        "INVARIANTE_CONSERVACAO",
        "Falha interna de conservação entre itens e explosão de insumos.",
        "$",
    )

    active_insumos.sort(key=lambda t: (-t[0], t[1]))
    explosao_lista: list[dict[str, Any]] = []
    acumulado_frac = Fraction(0, 1)

    for rank, (custo_ins, iid, ins) in enumerate(active_insumos, start=1):
        qtd_total = demanda_global_insumos[iid]
        part_frac = custo_ins / total_direto_exato
        acumulado_antes = acumulado_frac
        acumulado_frac += part_frac
        if acumulado_antes < Fraction(80, 100):
            classe_abc = "A"
        elif acumulado_antes < Fraction(95, 100):
            classe_abc = "B"
        else:
            classe_abc = "C"

        explosao_lista.append(
            {
                "ordem_abc": rank,
                "id": iid,
                "descricao": ins["descricao"],
                "unidade": ins["unidade"],
                "natureza": ins["natureza"],
                "preco_unitario_base_centavos": ins["preco_unitario_centavos"],
                "aplicar_encargos": ins["aplicar_encargos"],
                "custo_unitario_efetivo": rational_dict(ins["custo_unitario_efetivo"]),
                "quantidade_total": rational_dict(qtd_total),
                "custo_total_direto": rational_dict(custo_ins),
                "participacao_direta": {
                    "numerador": str(part_frac.numerator),
                    "denominador": str(part_frac.denominator),
                    "percentual_4": format_decimal(part_frac * 100, 4),
                },
                "participacao_acumulada": {
                    "numerador": str(acumulado_frac.numerator),
                    "denominador": str(acumulado_frac.denominator),
                    "percentual_4": format_decimal(acumulado_frac * 100, 4),
                },
                "classe_abc": classe_abc,
            }
        )

    composicoes_publicas = []
    for cid in sorted(composicoes_calc):
        c = composicoes_calc[cid]
        composicoes_publicas.append(
            {
                "id": c["id"],
                "descricao": c["descricao"],
                "unidade": c["unidade"],
                "custo_unitario_direto": c["custo_unitario_direto"],
                "por_natureza": c["por_natureza"],
                "componentes": c["componentes"],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "orcamento": {
            "id": orc_id,
            "titulo": orc_titulo,
            "moeda": "BRL",
            "encargos_sociais_percentual": format_decimal(encargos_pct, 4),
            "bdi_padrao_percentual": format_decimal(bdi_padrao_pct, 4),
            "bdi_equipamentos_percentual": format_decimal(bdi_equip_pct, 4),
        },
        "resumo_geral": {
            "quantidade_insumos_catalogo": len(insumos_map),
            "quantidade_insumos_utilizados": len(explosao_lista),
            "quantidade_composicoes": len(composicoes_publicas),
            "quantidade_itens_orcamento": len(itens_calculados),
            "custo_total_direto": rational_dict(total_direto_exato),
            "custo_explosao_insumos": rational_dict(soma_explosao_direto),
            "conservacao_exata_direto": soma_explosao_direto == total_direto_exato,
            "valor_total_bdi": rational_dict(total_bdi_exato),
            "preco_total_orcamento": rational_dict(total_preco_exato),
            "por_natureza_direto": {nat: rational_dict(totais_natureza_direto[nat]) for nat in NATUREZAS_VALIDAS},
        },
        "composicoes": composicoes_publicas,
        "itens_orcamento": itens_calculados,
        "explosao_insumos": explosao_lista,
    }

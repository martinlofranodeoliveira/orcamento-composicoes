"""API pública e CLI do pacote orcamento-composicoes."""
from __future__ import annotations

from .core import calcular_orcamento, format_decimal, rational_dict, round_half_even_int
from .errors import OrcamentoError
from .jsoncodec import dumps, dumps_output, loads

__all__ = [
    "OrcamentoError",
    "calcular_orcamento",
    "dumps",
    "dumps_output",
    "format_decimal",
    "loads",
    "rational_dict",
    "round_half_even_int",
]
__version__ = "1.0.0"

"""Erros públicos com códigos estáveis e mensagens em português."""
from __future__ import annotations


class OrcamentoError(ValueError):
    """Erro de validação, domínio ou entrada/saída do pacote orcamento-composicoes."""

    def __init__(self, code: str, message: str, path: str = "$") -> None:
        self.code = code
        self.message = message
        self.path = path
        super().__init__(f"[{code}] {message} (caminho: {path})")

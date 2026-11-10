#!/usr/bin/env python3
"""Confere os artefatos de distribuição (wheel e sdist) e exercita a instalação isolada."""
from __future__ import annotations

import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile
import venv
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = "orcamento_composicoes"
DIST_NAME = "orcamento-composicoes"
VERSION = "1.0.0"
DISTINFO = f"{NAME}-{VERSION}.dist-info"
ROOT_FILES = {
    ".gitattributes",
    ".gitignore",
    "LICENSE",
    "README.md",
    "MANIFEST.in",
    "pyproject.toml",
    "requirements-build.txt",
}
SUFFIXES = {
    "src": {".py", ".json"},
    "tests": {".py"},
    "scripts": {".py"},
    "tools": {".py"},
    "docs": {".md", ".png"},
    ".github": {".yml"},
}
FORBIDDEN = {".git", "local", "dist", "build", "__pycache__", ".openai", ".impeccable", "node_modules"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def safe_name(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    require(
        bool(name) and not p.is_absolute() and str(p) == name and "\\" not in name,
        "Nome de arquivo não canônico no artefato.",
    )
    require(
        all(x not in FORBIDDEN and x not in {".", ".."} and not x.startswith((".venv", ".env")) for x in p.parts),
        f"Contexto proibido na distribuição: {name}",
    )
    return p


def runtime_files(root: Path = ROOT) -> dict[str, bytes]:
    package = root / "src" / NAME
    return {
        p.relative_to(root / "src").as_posix(): p.read_bytes()
        for p in package.rglob("*")
        if p.is_file() and p.suffix in {".py", ".json"}
    }


def check_wheel(path: Path, root: Path = ROOT) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        require(archive.testzip() is None, "CRC do wheel inválido.")
        names = archive.namelist()
        require(len(names) == len(set(names)), "Membro repetido no wheel.")
        for name in names:
            safe_name(name)
            require(not name.endswith("/"), "Diretório inesperado no wheel.")
        files = {name: archive.read(name) for name in names}
    runtime = runtime_files(root)
    metadata_names = {
        f"{DISTINFO}/{name}"
        for name in ["METADATA", "WHEEL", "entry_points.txt", "top_level.txt", "RECORD"]
    }
    metadata_names.add(f"{DISTINFO}/licenses/LICENSE")
    require(set(files) == set(runtime) | metadata_names, f"Lista fechada do wheel diverge: {set(files) ^ (set(runtime) | metadata_names)}")
    for name, expected in runtime.items():
        require(files[name] == expected, f"O wheel alterou bytes de {name}.")
    require(files[f"{DISTINFO}/licenses/LICENSE"] == (root / "LICENSE").read_bytes(), "Licença do wheel divergente.")
    metadata = BytesParser().parsebytes(files[f"{DISTINFO}/METADATA"])
    require(metadata["Name"] == DIST_NAME and metadata["Version"] == VERSION, "Identidade do wheel divergente.")
    require(metadata["Requires-Python"] == ">=3.11" and metadata["License-Expression"] == "MIT", "Metadados divergentes.")
    require(not metadata.get_all("Requires-Dist"), "O runtime não deve ter dependências externas.")
    require("orcamento-composicoes = orcamento_composicoes.cli:main" in files[f"{DISTINFO}/entry_points.txt"].decode(), "Entry point ausente.")
    rows = list(csv.reader(io.StringIO(files[f"{DISTINFO}/RECORD"].decode())))
    require(len(rows) == len(files) and {r[0] for r in rows} == set(files), "Cobertura RECORD divergente.")
    for name, digest, size in rows:
        if name.endswith("/RECORD"):
            require(digest == size == "", "RECORD não deve assinar a si próprio.")
        else:
            expected_hash = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b"=").decode()
            require(digest == "sha256=" + expected_hash and size == str(len(files[name])), f"Hash/tamanho RECORD inválido para {name}.")
    return {"kind": "wheel", "members": len(files), "runtimeFiles": len(runtime)}


def check_sdist(path: Path, root: Path = ROOT) -> dict[str, object]:
    prefix = f"{NAME}-{VERSION}/"
    files: dict[str, bytes] = {}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            require(member.isfile(), f"Membro não regular no sdist: {member.name}")
            require(member.name.startswith(prefix), f"Prefixo inesperado no sdist: {member.name}")
            rel = member.name[len(prefix) :]
            safe_name(rel)
            extracted = archive.extractfile(member)
            require(extracted is not None, f"Falha ao ler {rel}")
            files[rel] = extracted.read()
    require("PKG-INFO" in files and "pyproject.toml" in files and "LICENSE" in files, "Metadados essenciais ausentes no sdist.")
    for rt_name, rt_bytes in runtime_files(root).items():
        sdist_key = f"src/{rt_name}"
        require(files.get(sdist_key) == rt_bytes, f"Fonte de runtime ausente ou divergente no sdist: {sdist_key}")
    return {"kind": "sdist", "members": len(files)}


def exercise_install(artifact: Path) -> dict[str, object]:
    artifact = artifact.resolve()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        venv_dir = tmp / "venv"
        venv.EnvBuilder(with_pip=True).create(venv_dir)
        py = venv_dir / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
        subprocess.run([str(py), "-m", "pip", "install", "--no-deps", str(artifact)], check=True, cwd=tmp)
        out_zip = tmp / "exemplo.zip"
        subprocess.run([str(py), "-m", "orcamento_composicoes.cli", "exemplo", "--saida", str(out_zip)], check=True, cwd=tmp)
        require(out_zip.is_file(), "Pacote de exemplo não foi gerado na instalação isolada.")
        # Also verify non-overwrite guarantee
        dup = subprocess.run([str(py), "-m", "orcamento_composicoes.cli", "exemplo", "--saida", str(out_zip)], cwd=tmp, capture_output=True)
        require(dup.returncode == 2, "CLI instalada deveria recusar sobrescrita de destino existente.")
    return {"installed": artifact.name, "verified": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, help="Diretório dist contendo wheel e sdist.")
    parser.add_argument("--install", type=Path, help="Artefato específico para instalar e exercitar fora da árvore.")
    args = parser.parse_args()

    if args.dist:
        wheels = list(args.dist.glob("*.whl"))
        sdists = list(args.dist.glob("*.tar.gz"))
        require(len(wheels) == 1 and len(sdists) == 1, "Esperado exatamente 1 wheel e 1 sdist em dist/.")
        w_info = check_wheel(wheels[0])
        s_info = check_sdist(sdists[0])
        print({"wheel": w_info, "sdist": s_info})
    if args.install:
        info = exercise_install(args.install)
        print(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

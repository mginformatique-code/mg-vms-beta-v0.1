"""MG-VMS Plugin Packager — empaquette un plugin en `.mgpkg` (tar.gz).

Usage :
    python -m plugin_sdk.pack my-plugin/
    python -m plugin_sdk.pack my-plugin/ --out dist/

Produit : `dist/my-plugin-{version}.mgpkg`
"""
from __future__ import annotations

import argparse
import sys
import tarfile
from pathlib import Path

try:
    import yaml  # noqa
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


def _read_version(manifest_path: Path) -> str:
    """Lit `metadata.version` du manifest — fallback regex si pyyaml absent."""
    text = manifest_path.read_text(encoding="utf-8")
    if _HAS_YAML:
        import yaml
        data = yaml.safe_load(text)
        return str(data.get("metadata", {}).get("version") or "0.0.0")
    # Fallback minimaliste
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return "0.0.0"


def _read_name(manifest_path: Path) -> str:
    text = manifest_path.read_text(encoding="utf-8")
    if _HAS_YAML:
        import yaml
        data = yaml.safe_load(text)
        return str(data.get("metadata", {}).get("name") or manifest_path.parent.name)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return manifest_path.parent.name


def pack(plugin_dir: Path, out_dir: Path | None = None) -> Path:
    """Empaquette `plugin_dir/` en `.mgpkg`. Retourne le chemin du fichier créé."""
    plugin_dir = Path(plugin_dir).resolve()
    if not plugin_dir.is_dir():
        raise NotADirectoryError(f"'{plugin_dir}' n'est pas un dossier")
    manifest = plugin_dir / "manifest.yaml"
    if not manifest.is_file():
        raise FileNotFoundError(f"manifest.yaml introuvable dans '{plugin_dir}'")
    plugin_py = plugin_dir / "plugin.py"
    if not plugin_py.is_file():
        raise FileNotFoundError(f"plugin.py introuvable dans '{plugin_dir}'")

    name = _read_name(manifest)
    version = _read_version(manifest)
    out_dir = (out_dir or Path.cwd()).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{name}-{version}.mgpkg"

    # Fichiers à inclure : tout sauf __pycache__, .venv, node_modules
    def _filter(tarinfo: tarfile.TarInfo):
        n = tarinfo.name.lower()
        if "__pycache__" in n or ".venv" in n or "node_modules" in n or n.endswith(".pyc"):
            return None
        return tarinfo

    with tarfile.open(out_path, "w:gz") as tar:
        tar.add(plugin_dir, arcname=name, filter=_filter)

    return out_path


def _main():
    parser = argparse.ArgumentParser(description="Empaquette un plugin MG-VMS en .mgpkg.")
    parser.add_argument("plugin_dir", help="Dossier du plugin (contient manifest.yaml)")
    parser.add_argument("--out", default=".", help="Dossier de sortie (défaut: courant)")
    args = parser.parse_args()

    try:
        path = pack(Path(args.plugin_dir), Path(args.out))
    except (NotADirectoryError, FileNotFoundError) as e:
        print(f"ERREUR: {e}", file=sys.stderr)
        sys.exit(1)

    size_kb = path.stat().st_size / 1024
    print(f"✓ {path} ({size_kb:.1f} Ko)")


if __name__ == "__main__":
    _main()

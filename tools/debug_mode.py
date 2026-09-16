#!/usr/bin/env python3
"""
Liga e desliga o modo de teste do FishingMPFix.

O modo de teste quebra a pesca de proposito (ver dev/FishingMPFix_Debug.lua).
Ele nunca deve ser publicado nem rodar no servidor de verdade, entao vive fora
da pasta do mod e so e copiado para la sob demanda.

Uso:
    .venv/bin/python tools/debug_mode.py on
    .venv/bin/python tools/debug_mode.py off
    .venv/bin/python tools/debug_mode.py status
"""
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "dev/FishingMPFix_Debug.lua"

# O modo de teste so faz sentido na copia local que o jogo carrega.
import paths

TARGET_DIR = paths.mod_in_stage() / "42/media/lua/server"
TARGET = TARGET_DIR / "FishingMPFix_Debug.lua"


def status() -> bool:
    on = TARGET.exists()
    print(f"modo de teste: {'LIGADO' if on else 'desligado'}")
    print(f"  {TARGET}")
    if on:
        print("\n  Lembre de rodar 'debug_mode.py off' antes de publicar.")
        print("  O build_vdf.py se recusa a subir com o arquivo presente.")
    return on


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "status"

    if action == "status":
        status()
        return

    if not TARGET_DIR.exists():
        sys.exit(f"pasta do mod nao encontrada: {TARGET_DIR}")

    if action == "on":
        if not SOURCE.exists():
            sys.exit(f"arquivo de teste nao encontrado: {SOURCE}")
        shutil.copy2(SOURCE, TARGET)
        print(f"modo de teste LIGADO -> {TARGET}")
        print("\nNo jogo: HOST -> co-op sozinho -> painel de admin -> Fishing Cheat.")
        print("Edite DISABLE_FIX em dev/FishingMPFix_Debug.lua e rode 'on' de novo")
        print("para alternar entre ver o bug e ver o fix.")
    elif action == "off":
        if TARGET.exists():
            TARGET.unlink()
            print(f"modo de teste desligado (removido de {TARGET})")
        else:
            print("modo de teste ja estava desligado")
    else:
        sys.exit(f"acao desconhecida: {action}  (use on / off / status)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Resolucao dos caminhos que dependem da maquina.

O projeto vive no WSL mas depende de tres coisas do lado Windows: a instalacao
do jogo (para os testes lerem o Bobber.lua real), a pasta Zomboid do usuario
(onde fica o staging da Oficina) e o steamcmd. O nome do usuario do Windows e a
letra do disco mudam de maquina para maquina, entao nada disso pode ficar
cravado no codigo.

Ordem de resolucao, da maior para a menor prioridade:
  1. variavel de ambiente  (PZFIX_GAME, PZFIX_ZOMBOID, PZFIX_STEAMCMD)
  2. tools/paths.local.ini (fora do git)
  3. autodeteccao varrendo /mnt/<letra>/

Diagnostico:  .venv/bin/python tools/paths.py
"""
import configparser
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOCAL_INI = REPO / "tools/paths.local.ini"

MOD_ID = "FishingMPFix"


def _from_ini(chave):
    if not LOCAL_INI.exists():
        return None
    cp = configparser.ConfigParser()
    cp.read(LOCAL_INI)
    valor = cp.get("paths", chave, fallback="").strip()
    return Path(valor) if valor else None


def _drives():
    """Letras de disco montadas pelo WSL, com C: primeiro."""
    mnt = Path("/mnt")
    if not mnt.is_dir():
        return []
    letras = sorted(p for p in mnt.iterdir()
                    if p.is_dir() and len(p.name) == 1)
    return sorted(letras, key=lambda p: (p.name != "c", p.name))


def _detect_game():
    for d in _drives():
        for sufixo in ("Program Files (x86)/Steam", "Program Files/Steam",
                       "SteamLibrary", "Steam"):
            alvo = d / sufixo / "steamapps/common/ProjectZomboid"
            if (alvo / "media/lua/shared/Fishing/Bobber.lua").exists():
                return alvo
    return None


def _detect_zomboid():
    for d in _drives():
        users = d / "Users"
        if not users.is_dir():
            continue
        try:
            candidatos = [u / "Zomboid" for u in users.iterdir() if u.is_dir()]
        except PermissionError:
            continue
        # o perfil certo e o que tem a pasta Workshop
        for z in candidatos:
            if (z / "Workshop").is_dir():
                return z
        for z in candidatos:
            if z.is_dir():
                return z
    return None


def _resolver(chave, env, detector, obrigatorio=True):
    bruto = os.environ.get(env)
    if bruto:
        return Path(bruto)
    do_ini = _from_ini(chave)
    if do_ini:
        return do_ini
    achado = detector()
    if achado is None and obrigatorio:
        raise SystemExit(
            f"nao encontrei o caminho '{chave}'.\n"
            f"  defina {env}=... ou crie {LOCAL_INI} com:\n"
            f"    [paths]\n    {chave} = /mnt/c/...")
    return achado


def game():
    """Instalacao do Project Zomboid (para ler o Bobber.lua do jogo)."""
    return _resolver("game", "PZFIX_GAME", _detect_game)


def zomboid():
    """Pasta Zomboid do usuario (Saves, Workshop, console.txt)."""
    return _resolver("zomboid", "PZFIX_ZOMBOID", _detect_zomboid)


def workshop_stage():
    """Pasta de staging que o uploader da Oficina le."""
    return zomboid() / "Workshop" / MOD_ID


def mod_in_stage():
    return workshop_stage() / "Contents/mods" / MOD_ID


def steamcmd():
    """Pasta do steamcmd (opcional: so publicar precisa)."""
    def detectar():
        for d in _drives():
            p = d / "steamcmd"
            if (p / "steamcmd.exe").exists():
                return p
        return None
    return _resolver("steamcmd", "PZFIX_STEAMCMD", detectar, obrigatorio=False)


def to_windows(p):
    """Caminho WSL -> caminho Windows, para o VDF do steamcmd."""
    try:
        saida = subprocess.run(["wslpath", "-w", str(p)],
                               capture_output=True, text=True, timeout=10)
        if saida.returncode == 0 and saida.stdout.strip():
            return saida.stdout.strip()
    except Exception:
        pass
    # /mnt/c/x/y -> C:\x\y
    s = str(p)
    if s.startswith("/mnt/") and len(s) > 6:
        return f"{s[5].upper()}:\\" + s[7:].replace("/", "\\")
    return s


if __name__ == "__main__":
    print(f"repo        {REPO}")
    for nome, fn in (("game", game), ("zomboid", zomboid),
                     ("staging", workshop_stage), ("steamcmd", steamcmd)):
        try:
            v = fn()
            marca = "ok " if v and Path(v).exists() else "NAO EXISTE"
            print(f"{nome:<11} {marca} {v}")
        except SystemExit as e:
            print(f"{nome:<11} FALTA  {e}")

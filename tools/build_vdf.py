#!/usr/bin/env python3
"""
Gera e valida tools/workshop_item.vdf.

Duas armadilhas do parser KeyValues da Valve, ambas por escape sequences
estarem DESABILITADAS no workshop_build_item:

  1. Aspa dupla dentro de um valor encerra a string ali, mesmo escrita
     como \\" -- quebra o parse com "got } in key".
  2. \\n nao vira quebra de linha; sai literal na descricao publicada.
     Quebra de linha de verdade tem que ser um newline real dentro do
     valor entre aspas (KeyValues le ate a aspa de fechamento).

Uso:  .venv/bin/python tools/build_vdf.py
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VDF = REPO / "tools/workshop_item.vdf"
import paths

_sc = paths.steamcmd()
STEAMCMD = (_sc / "workshop_item.vdf") if _sc else None

WORKSHOP_ID = "3795522820"
MOD_ID = "FishingMPFix"

FIELDS = {
    "appid": "108600",
    "publishedfileid": WORKSHOP_ID,
    # o KeyValues exige barra invertida dupla
    "contentfolder": paths.to_windows(paths.workshop_stage() / "Contents").replace("\\", "\\\\"),
    "previewfile": paths.to_windows(paths.workshop_stage() / "preview.png").replace("\\", "\\\\"),
    "visibility": "0",  # 0 public, 1 friends, 2 hidden, 3 unlisted
    "title": "No Catch Fix - MP Fishing [B42.20]",
    "description": f"""[h1]No Catch Fix - MP Fishing [B42.20][/h1]
[b]Workshop ID:[/b] {WORKSHOP_ID}
[b]Mod ID:[/b] {MOD_ID}
[b]Build:[/b] 42.20+

[b]Also known as:[/b] no catch bug, no catch fishing, bait disappears, fish vanishes on reel, tension disappears halfway, only the first player can fish, fishing panel errors, fishing panel not updating, caught fish list resets

Fixes the [b]No Catch[/b] bug in Build 42 multiplayer fishing: the bait unequips in the middle of the fight and the catch turns into No Catch, with no fish, no XP, and the line worn down anyway.

Symptoms you will recognise: the tension disappears halfway through reeling, the fish stops resisting out of nowhere, the bait is gone and no XP is granted. On a server it usually reads as only the first angler being able to land anything, while everybody else watches the bar run out with nothing they can do about it. Multiplayer only.

[h2]Installing on a hosted server[/h2]
On hosting panels (Pterodactyl and similar), fill in:

[b]Workshop ID:[/b] [code]{WORKSHOP_ID}[/code]
[b]Mod IDs:[/b] [code]{MOD_ID}[/code]

Editing servertest.ini by hand, [b]append without removing what is already there[/b], separated by semicolons:

[code]WorkshopItems=...your current IDs...;{WORKSHOP_ID}
Mods=...your current mods...;{MOD_ID}[/code]

[b]Warning:[/b] writing Mods={MOD_ID} on its own wipes every other mod on the server.

Installing is still one field on the panel. Both halves of the mod travel in this Workshop item and the game delivers a server mods to every client that connects: no manual install, no javaagent, no launch options.

[h2]Bite indicator[/h2]
While fighting a fish, a small window appears just below your character, following it around the screen, showing how long is left before the server gives up on the bite. Every time the fix prevents that, a [b]+1[/b] floats up. It fades on its own when the fight ends.

It exists because in vanilla both outcomes look identical: the needle drops and No catch appears, with nothing separating the fish got away from the server threw your fish out. Press F7 to toggle, rebindable under Options - Key Bindings.

[h2]Fishing Panel[/h2]
The panel you open by right-clicking water has two vanilla defects in multiplayer, and the mod fixes both on the client:

[list]
[*][b]The caught-fish list empties every session.[/b] Vanilla keeps that list only on your client, but in multiplayer your character is saved from the server copy, so it never survives a reconnect. The server does record every catch under its own key, and that one is saved; the mod rebuilds the list from it, so fish you caught before installing the mod come back too.
[*][b]Error spam and a panel that stops updating.[/b] When the server sends your character data, the game wipes the table the panel reads, and every fish row throws an error on every frame. After dying and respawning the panel also kept showing the dead character. The mod keeps the table in place and points the panel at your current character before each frame.
[/list]

No new network traffic and nothing new written on the server.

[h2]Compatibility and removal[/h2]
The mod wraps Bobber:update instead of replacing it, so it chains with other fishing mods in any load order. If another mod replaces the function outright, the patch detects it and re-chains on top instead of silently disappearing. Verified against TwisTonFire - Better Fishing: no code conflict and no UI overlap.

[b]It writes nothing persistent of its own:[/b] no modData keys of its own, no item changes, no sandbox vars, no files. The fishing state lives on the bobber, which is destroyed on every cast; the panel fix only fills the list vanilla itself keeps. Uninstalling leaves no trace, does not break saves and needs no wipe.

[h2]What causes the bug[/h2]
When a fish bites, the server lights a 360 tick fuse, and the client sets a flag as soon as you start reeling. The flag has to travel back, and that is where it breaks.

Each client numbers its own network actions from a counter that starts at 1, inside its own process. The server keeps every action in one queue and resolves them by that number alone, taking the first one that holds it. Since every client counts from 1 on its own, the anglers collide: the flag that says I am reeling in gets credited to whoever started fishing first, and lands on the bobber of that player.

So the first angler quietly collects the flags of everybody else and is never punished, while all the others keep the flag false until the fuse runs out and the server calls removeLure() and discards the fish.

That is why the bug needs 2 or more players to show up, why it so often reads as only the first player to connect can fish, and why both community workarounds work for the same reason, shortening the reel: casting closer, or standing 1 to 4 tiles back from the shore (the bobber reaches dry land before it reaches you and isPickupBobber() ends the reel right there).

[h2]What this mod does NOT fix[/h2]
Bubble spots that never bite are a different problem. The client draws fishing points the server does not consider stocked, so getFishAbundance returns zero and bites almost never happen. This mod handles what happens AFTER the bite.

If your symptom is never getting a bite at a given spot, or having to hop between bubbles constantly, the problem is fish zone synchronisation, not the timer.

[h2]What the mod does[/h2]
It stops using the broken route. The client reports the reel over a channel that does not involve that number at all: the server identifies the sender from the connection the packet arrived on, so the flag can only ever reach the right bobber. From there the fight behaves exactly like single player.

Behind it sits a safety net, for a client that has not updated yet or a packet that goes missing. Before letting the fuse punish you, the server confirms whether the player is still fishing, and re-arms the fuse instead of taking the bait away. The evidence it trusts is calibrated on the bite itself, the one moment when the right answer is known: the bobber is in the water and a fish has just taken the bait, so the player IS fishing. The mod works out, on each server, which signal is usable there, because the obvious one, the character state, does not exist inside a dedicated server process.

The server console names both halves as they come up, so you can confirm at a glance which one is doing the work.

No balance changes. The re-arm is capped, so a player who genuinely ignores the bite still loses the bait. Single player never had the bug and is left alone. A game hosted from the main menu is covered for everyone, host included: the game runs that server as a separate process and the host joins it like any friend.

[h2]One thing that still needs the developers[/h2]
The same collision makes the server stop every action sharing a number, not only the one being stopped. So when one angler stops fishing, another can lose their line on the server side and has to re-equip the rod to start again. That part cannot be fixed from mod code.""",
    "changenote": "v1.3.1 - The bite indicator no longer blocks the mouse.\n\nReported on this page, with the right diagnosis: the indicator stayed on screen as an empty, invisible box when there was nothing to show. In Project Zomboid an invisible-but-visible element still blocks hover and clicks for whatever is under it - at login that was the equipped-item icons in the top-left corner, and after fishing it was the spot at your character's feet. The indicator is now hidden whenever it has nothing to draw and only appears during a bite.\n\nNo change to the No Catch fix or the Fishing Panel fix.",
}


def build() -> str:
    body = "\n".join(f'\t"{k}"\t\t"{v}"' for k, v in FIELDS.items())
    return '"workshopitem"\n{\n' + body + "\n}\n"


def validate(text: str) -> bool:
    """Le o arquivo como o KeyValues leria: so a aspa dupla delimita."""
    for key, value in FIELDS.items():
        if '"' in value:
            print(f"  ERRO: valor de {key} contem aspa dupla")
            return False
        if "\\n" in value:
            print(f"  ERRO: valor de {key} contem \\n literal (use newline real)")
            return False

    tokens = re.findall(r'"([^"]*)"', text)
    if tokens[0] != "workshopitem":
        print("  ERRO: raiz nao e workshopitem")
        return False
    pairs = tokens[1:]
    if len(pairs) % 2:
        print("  ERRO: numero impar de tokens - aspa sobrando em algum valor")
        return False
    parsed = dict(zip(pairs[::2], pairs[1::2]))
    if parsed != FIELDS:
        for k in set(FIELDS) | set(parsed):
            if FIELDS.get(k) != parsed.get(k):
                print(f"  ERRO: {k} nao sobreviveu ao parse")
        return False
    print(f"  {len(parsed)} pares, todos intactos apos o parse")
    return True


# O modo de teste quebra a pesca de proposito; publicar com ele seria enviar
# um mod que estraga a pesca de todo mundo que assinar.
DEBUG_IN_PACKAGE = (paths.mod_in_stage()
                    / "42/media/lua/server/FishingMPFix_Debug.lua")


def main():
    if DEBUG_IN_PACKAGE.exists():
        sys.exit(
            "RECUSADO: o modo de teste esta ativo dentro do pacote.\n"
            f"  {DEBUG_IN_PACKAGE}\n"
            "Rode:  .venv/bin/python tools/debug_mode.py off")

    text = build()
    print("Validando...")
    if not validate(text):
        sys.exit("VDF invalido, nada foi escrito.")
    VDF.write_text(text, encoding="utf-8")
    print(f"escrito: {VDF}")
    if STEAMCMD.parent.exists():
        STEAMCMD.write_text(text, encoding="utf-8")
        print(f"escrito: {STEAMCMD}")


if __name__ == "__main__":
    main()

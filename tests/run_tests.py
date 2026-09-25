#!/usr/bin/env python3
"""
Testes do FishingMPFix.

Carrega o Bobber.lua REAL do Project Zomboid instalado, exercita o "pavio" de
360 ticks que causa o bug em multiplayer e verifica o comportamento com e sem
o mod aplicado.
"""
import sys
from pathlib import Path

from lupa import LuaRuntime

HERE = Path(__file__).resolve().parent
MOD_LUA = HERE.parent / "42/media/lua/server/FishingMPFix.lua"
HUD_LUA = HERE.parent / "42/media/lua/client/FishingMPFix_HUD.lua"
sys.path.insert(0, str(HERE.parent / "tools"))
import paths  # noqa: E402  resolve os caminhos que dependem da maquina

VANILLA_BOBBER = paths.game() / "media/lua/shared/Fishing/Bobber.lua"

PASS, FAIL = [], []


def new_env(load_mod: bool, **env):
    """Runtime Lua limpo: stubs + Bobber.lua real + (opcionalmente) o mod."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'dofile("{HERE / "pz_stubs.lua"}")')
    for key, value in env.items():
        lua.globals().TestEnv[key] = value
    lua.execute(f'dofile("{VANILLA_BOBBER}")')
    if load_mod:
        if not MOD_LUA.exists():
            raise FileNotFoundError(MOD_LUA)
        lua.execute(f'dofile("{MOD_LUA}")')
    return lua


def new_ui_env(**env):
    """Runtime com os stubs de UI e o HUD carregado, ja apos o OnGameStart."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'dofile("{HERE / "pz_stubs.lua"}")')
    lua.globals().TestEnv["isServer"] = False
    for key, value in env.items():
        lua.globals().TestEnv[key] = value
    lua.execute(f'dofile("{HERE / "ui_stubs.lua"}")')
    lua.execute(f'dofile("{HUD_LUA}")')
    # dispara os handlers de OnGameStart registrados pelo mod
    lua.execute("for _, fn in ipairs(Events.OnGameStart.handlers) do fn() end")
    return lua


RELAY_LUA = HERE.parent / "42/media/lua/client/FishingMPFix_Catch.lua"


def new_relay_env():
    """Runtime de CLIENTE com o relay de fisgada carregado."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'dofile("{HERE / "pz_stubs.lua"}")')
    lua.globals().TestEnv["isClient"] = True
    lua.globals().TestEnv["isServer"] = False
    # o cliente usa a mesma classe Bobber do jogo
    lua.execute(f'dofile("{VANILLA_BOBBER}")')
    if not RELAY_LUA.exists():
        raise FileNotFoundError(RELAY_LUA)
    lua.execute(f'dofile("{RELAY_LUA}")')
    return lua


def relay_tick(lua, n=1):
    """Roda os handlers de OnTick registrados pelo relay."""
    for _ in range(n):
        lua.execute("for _, fn in ipairs(Events.OnTick.handlers) do fn() end")


def client_command(lua, module, command, player, args=None):
    """Entrega uma mensagem cliente -> servidor ao lado servidor do mod.

    O player vem da CONEXAO (GameServer.receiveClientCommand chama
    getPlayerFromConnection), nao do id de acao -- e por isso que esse canal
    nao sofre a colisao que quebra o vanilla.
    """
    handlers = lua.globals().Events.OnClientCommand.handlers
    for i in range(1, len(handlers) + 1):
        handlers[i](module, command, player, args or lua.table_from({}))


def two_anglers(lua, nibble=360):
    """Dois jogadores pescando ao mesmo tempo num servidor dedicado."""
    g = lua.globals()
    out = []
    for online_id in (1, 2):
        rod = g.makeRod(lua.table_from({"rodId": online_id}))
        player = g.makePlayer(lua.table_from({
            "onlineID": online_id, "primaryHand": rod.rodItem,
            "state": g.IdleState.instance()}))
        bobber = g.makeHookedBobber(lua.table_from({
            "rod": rod, "player": player, "nibbleTimer": nibble}))
        g.Fishing.ServerBobberManager[online_id] = bobber
        out.append((rod, player, bobber))
    return out


def flag_com_id_colidido(lua, dono_do_id):
    """O flag de recolhimento como o servidor REALMENTE o entrega.

    Verificado no bytecode de 42.20:

        Action.set()                 -> id = ++lastId, e lastId e um byte
                                        estatico DE CADA CLIENTE
        ActionManager.getPlayer(id)  -> primeira acao da fila com aquele id
        FishingAction.getLuaTable()  -> data.player = getPlayer(id)

    Como cada cliente conta do 1 por conta propria, todo mundo manda id 1 na
    primeira pescaria e data.player e sempre o PRIMEIRO jogador da fila --
    quem recolhe a linha nao importa.
    """
    data = lua.table_from({
        "player": dono_do_id,
        "UpdateFish": False,
        "UpdateBobberParameters": True,
        "CatchFishStarted": True,
    })
    lua.globals().Fishing.Bobber.onFishingActionMPUpdate(data)


def hud_send(lua, event, fuse=360, rearms=0):
    """Simula a mensagem que o servidor manda para a HUD."""
    args = lua.table_from({"event": event, "fuse": fuse, "rearms": rearms})
    for i in range(1, len(lua.globals().Events.OnServerCommand.handlers) + 1):
        lua.globals().Events.OnServerCommand.handlers[i](
            "FishingMPFix", "hud", args)


def hud_draw(lua):
    """Roda prerender + render e devolve o elemento e o que foi desenhado."""
    lua.execute("""
        resetDrawn()
        LastUI:prerender()
        LastUI:render()
    """)
    g = lua.globals()
    return g.LastUI, g.Drawn


def hud_tick(lua, n=1):
    """Roda os handlers de OnTick registrados pelo HUD."""
    for _ in range(n):
        lua.execute("for _, fn in ipairs(Events.OnTick.handlers) do fn() end")


def texts_by_align(drawn, align):
    out = []
    for i in range(1, len(drawn.texts) + 1):
        t = drawn.texts[i]
        if t.align == align:
            out.append(t)
    return out


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FALHOU'}  {name}{'' if cond else '  <- ' + detail}")


def burn_fuse(lua, bobber, ticks=3):
    """Roda update() ate o pavio queimar (nibbleTimer comeca em 0.5)."""
    for _ in range(ticks):
        lua.globals().Fishing.Bobber.update(bobber)


# ---------------------------------------------------------------------------

def test_vanilla_reproduz_o_bug():
    """Sem o mod: o pavio queima, a isca some e o peixe some. E o bug."""
    lua = new_env(load_mod=False)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("vanilla: removeLure() e chamado (isca desequipa)",
          rod.removeLureCalls == 1, f"chamadas={rod.removeLureCalls}")
    check("vanilla: o peixe e descartado (vira No Catch)",
          b.fish is None, f"fish={b.fish}")


def test_fix_mantem_isca_com_jogador_pescando():
    """Com o mod: jogador ainda em FishingState -> pavio rearmado, nada perdido."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("fix: removeLure() NAO e chamado", rod.removeLureCalls == 0,
          f"chamadas={rod.removeLureCalls}")
    check("fix: o peixe continua na linha", b.fish is not None)
    check("fix: o pavio foi rearmado", b.nibbleTimer > 100,
          f"nibbleTimer={b.nibbleTimer}")


def test_fix_preserva_vanilla_se_parou_de_pescar():
    """Jogador largou a vara: a punicao do vanilla deve continuar valendo."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({"primaryHand": None, "state": None}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("fix: quem largou a vara ainda perde a isca", rod.removeLureCalls == 1,
          f"chamadas={rod.removeLureCalls}")
    check("fix: e perde o peixe", b.fish is None)


def test_fix_pune_quem_parou_de_pescar_mas_segura_a_vara():
    """O caso realista que faltava: saiu do FishingState, mas a vara continua
    na mao. Como FishingRod:new guarda o item que estava na mao, o teste de
    'segurando a vara' e sempre verdadeiro enquanto a boia existe — ele nao
    pode ser usado para desempatar quando o estado ja respondeu.

    O jogador precisa estar em FishingState NA MORDIDA: e ali que o mod
    descobre se o estado enxerga neste processo. Comecar ja fora do estado
    seria indistinguivel de um servidor dedicado, onde ninguem entra nele e um
    "nao" nao quer dizer nada (test_fix_funciona_em_servidor_dedicado).
    """
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "noFish": True}))

    burn_fuse(lua, b, ticks=2)          # boia na agua, ainda sem peixe
    g.giveFish(b, 5)                    # morde estando em FishingState
    lua.globals().Fishing.Bobber.update(b)   # o mod calibra o sinal neste tick
    player._state = None                # e so agora o jogador larga a pescaria
    burn_fuse(lua, b, ticks=6)

    check("fix: parou de pescar (ainda com a vara) -> perde a isca",
          rod.removeLureCalls == 1, f"chamadas={rod.removeLureCalls}")
    check("fix: parou de pescar -> perde o peixe", b.fish is None)


def test_fix_funciona_em_servidor_dedicado():
    """O caso que faltava, e o que os jogadores relataram: num servidor
    dedicado o jogador NUNCA aparece em FishingState.

    Quem entra nesse estado e IsoPlayer.setFishingStage, e a chamada esta
    atras de um `if (GameClient.client)`. A outra porta e o evento
    EventFishing do grafo de animacao, disparado num unico lugar:
    client/Fishing/FishingStates.lua:55. Nenhum dos dois roda no processo do
    servidor, entao getCurrentState() devolve IdleState mesmo para quem esta
    com o peixe na linha.

    Perguntar sem calibrar transforma "nao da para saber" em "nao esta
    pescando": o mod anuncia a fisgada na HUD e deixa o pavio queimar do
    mesmo jeito -- que e exatamente o relato de quem disse que o mod so avisa
    do peixe e perde a fisgada assim mesmo.
    """
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.IdleState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("dedicado: a isca continua na vara", rod.removeLureCalls == 0,
          f"chamadas={rod.removeLureCalls}")
    check("dedicado: o peixe continua na linha", b.fish is not None)
    check("dedicado: o pavio foi rearmado", b.nibbleTimer > 100,
          f"nibbleTimer={b.nibbleTimer}")


def test_fix_nao_prende_peixe_lixo():
    """Lixo nao custa isca no vanilla (Bobber.lua:150 checa isTrash), entao
    rearmar so prende o lixo na linha — e enquanto houver fish, Bobber.lua:128
    impede novas mordidas."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5, "isTrash": True}))

    burn_fuse(lua, b)

    check("fix: lixo e descartado na hora, como no vanilla", b.fish is None,
          f"fish ainda na linha, nibbleTimer={b.nibbleTimer}")
    check("fix: lixo nunca chama removeLure", rod.removeLureCalls == 0)


def test_fix_desiste_apos_o_limite():
    """O rearme e finito: um AFK eterno ainda perde a isca."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    # cada rearme repoe 360 ticks; queima muito alem do teto
    g.TestEnv.tickMultiplier = 400.0
    for _ in range(60):
        lua.globals().Fishing.Bobber.update(b)

    check("fix: apos o teto de rearmes a punicao volta", rod.removeLureCalls >= 1,
          f"chamadas={rod.removeLureCalls}")


def test_fix_sequencia_realista_de_rearmes():
    """O teste do teto usa multiplier=400, onde cada rearme morre no tick
    seguinte. Aqui a sequencia real: multiplier 1.0, 20 rearmes de 360 ticks
    cada. Verifica que a folga total e ~MAX_REARMS*360 — se algo contasse
    dobrado (wrapper empilhado) ou pulasse, a janela mudaria de tamanho."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    update = lua.globals().Fishing.Bobber.update
    ticks = 0
    while rod.removeLureCalls == 0 and ticks < 12000:
        update(b)
        ticks += 1

    esperado = 20 * 360  # MAX_REARMS * REARM_TICKS
    check("fix: a punicao chega perto de MAX_REARMS*360 ticks",
          abs(ticks - esperado) <= 400, f"levou {ticks} ticks, esperado ~{esperado}")
    check("fix: contou exatamente MAX_REARMS saves, sem somar a negada",
          b.fishingMPFix_rearms == 20, f"rearms={b.fishingMPFix_rearms}")


def test_fix_zera_contagem_apos_captura():
    """Numa captura o vanilla fixa nibbleTimer=-1 mas mantem o fish ate o
    pickup. Se a contagem so zerasse quando fish some, a proxima fisgada da
    mesma boia comecaria com o contador sujo e receberia menos rearmes."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)
    antes = b.fishingMPFix_rearms
    b.catchFishStarted = True          # o flag finalmente chegou
    lua.globals().Fishing.Bobber.update(b)

    check("fix: contagem existia antes da captura", antes == 1, f"rearms={antes}")
    check("fix: captura zera a contagem, mesmo com o peixe ainda na linha",
          b.fishingMPFix_rearms is None, f"rearms={b.fishingMPFix_rearms}")


def test_contador_so_conta_save_de_verdade():
    """O "saved Nx" e o numero que o jogador usa para julgar o mod, entao nao
    pode contar tentativa que nao salvou nada.

    Incrementar antes de decidir somava a tentativa negada -- teto batido ou
    jogador que largou a pescaria -- e o `Bite lost` seguinte levava o numero
    inflado para a HUD: "perdi a fisgada, mas salvei 21x".
    """
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)
    check("contador: um save de verdade conta 1", b.fishingMPFix_rearms == 1,
          f"rearms={b.fishingMPFix_rearms}")

    # o jogador larga a pescaria: a proxima expiracao tem de ser negada
    player._state = g.IdleState.instance()
    b.nibbleTimer = 0.5
    burn_fuse(lua, b, ticks=1)          # so o tick da expiracao

    check("contador: a tentativa negada nao entra na conta",
          rod.removeLureCalls == 1 and b.fishingMPFix_rearms == 1,
          f"removeLure={rod.removeLureCalls} rearms={b.fishingMPFix_rearms}")

    burn_fuse(lua, b, ticks=1)          # a transicao que fecha a fisgada
    ultima = g.SentServerCommands[len(g.SentServerCommands)]
    check("contador: a HUD recebeu o numero verdadeiro no fim da fisgada",
          ultima.args.event == "lost" and ultima.args.rearms == 1,
          f"{ultima.args.event} rearms={ultima.args.rearms}")


def test_convive_com_mod_que_substitui_o_update():
    """Um mod que SUBSTITUI Bobber.update (em vez de envolver) apagaria o nosso
    patch em silencio. applyPatch detecta e se reencadeia por cima do dele, de
    modo que os dois rodem."""
    lua = new_env(load_mod=True)
    g = lua.globals()

    # Outro mod entra depois e troca a funcao inteira.
    lua.execute("""
        OutroModRodou = 0
        local anterior = Fishing.Bobber.update
        function Fishing.Bobber:update()
            OutroModRodou = OutroModRodou + 1
            return anterior(self)
        end
        Fishing.Bobber.update_substituida = true
    """)
    lua.execute(f'dofile("{MOD_LUA}")')   # nos reencadeamos por cima

    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("convivencia: o outro mod continua rodando",
          g.OutroModRodou == 3, f"rodou {g.OutroModRodou}x em 3 ticks")
    check("convivencia: o nosso fix volta a valer", rod.removeLureCalls == 0,
          f"chamadas={rod.removeLureCalls}")
    check("convivencia: sem contagem duplicada", b.fishingMPFix_rearms == 1,
          f"rearms={b.fishingMPFix_rearms}")


def test_hud_nao_avisa_nada_em_boia_recem_lancada():
    """Boia sem peixe nao pode gerar aviso. Em Lua `false ~= nil` e verdadeiro,
    entao um wasBurning nao inicializado dispara uma transicao falsa no primeiro
    tick — a HUD piscaria "Fisgada perdida" logo depois do lancamento."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "noFish": True}))

    burn_fuse(lua, b, ticks=5)

    sent = g.SentServerCommands
    eventos = [sent[i].args.event for i in range(1, len(sent) + 1)]
    check("hud: boia sem peixe nao manda aviso nenhum", eventos == [],
          f"eventos={eventos}")


def _debug_env(lua, **flags):
    lua.globals().FishingMPFixDebug = lua.table_from(flags)


def _host_pescando_solo(lua):
    """Co-op solo: o unico pescador e o host, e o cliente ja marcou o flag."""
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance(),
        "isLocal": True}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5,
        "catchFishStarted": True}))
    return rod, b


def test_debug_simulate_desync_reproduz_o_bug_solo():
    """Com DISABLE_FIX o teste solo mostra o BUG: mesmo o cliente tendo marcado
    catchFishStarted, o pavio queima e a isca vai embora."""
    lua = new_env(load_mod=True, isServer=False)   # host de co-op
    _debug_env(lua, SIMULATE_DESYNC=True, INCLUDE_LOCAL=True, DISABLE_FIX=True)
    rod, b = _host_pescando_solo(lua)

    burn_fuse(lua, b)

    check("debug: solo reproduz a perda da isca", rod.removeLureCalls == 1,
          f"chamadas={rod.removeLureCalls}")
    check("debug: solo reproduz o No Catch", b.fish is None)


def test_debug_com_o_fix_ligado_salva_a_fisgada():
    """O outro lado do A/B, so trocando DISABLE_FIX: mesma situacao, mas o fix
    mantem a fisgada. E a prova que nao depende de sorte na pescaria."""
    lua = new_env(load_mod=True, isServer=False)
    _debug_env(lua, SIMULATE_DESYNC=True, INCLUDE_LOCAL=True, DISABLE_FIX=False)
    rod, b = _host_pescando_solo(lua)

    burn_fuse(lua, b)

    check("debug: com o fix a isca fica", rod.removeLureCalls == 0,
          f"chamadas={rod.removeLureCalls}")
    check("debug: com o fix o peixe fica", b.fish is not None)
    check("debug: o pavio foi rearmado", b.nibbleTimer > 100,
          f"nibbleTimer={b.nibbleTimer}")


def test_debug_inerte_quando_o_arquivo_nao_existe():
    """Sem o arquivo de teste, os ganchos precisam sumir por completo: a boia do
    host volta a ser ignorada e o catchFishStarted volta a valer."""
    lua = new_env(load_mod=True, isServer=False)
    rod, b = _host_pescando_solo(lua)          # sem _debug_env

    burn_fuse(lua, b)

    check("debug: sem o arquivo, o flag do cliente e respeitado",
          rod.removeLureCalls == 0, f"chamadas={rod.removeLureCalls}")
    check("debug: sem o arquivo, o vanilla congela o pavio (-1)",
          b.nibbleTimer == -1, f"nibbleTimer={b.nibbleTimer}")


def test_hud_recebe_as_transicoes():
    """Segue o ciclo real: a boia nasce vazia, o peixe morde depois. A HUD e
    alimentada so por transicoes; se o servidor mandasse por tick isso viraria
    trafego de rede a 60/s por pescador."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "noFish": True}))

    burn_fuse(lua, b, ticks=3)      # boia vazia na agua: nada a avisar
    g.giveFish(b, 0.5)              # o peixe morde
    burn_fuse(lua, b, ticks=10)

    sent = g.SentServerCommands
    eventos = [sent[i].args.event for i in range(1, len(sent) + 1)]

    check("hud: avisa a fisgada e o rearme, nesta ordem",
          eventos == ["hooked", "rearmed"], f"eventos={eventos}")
    check("hud: nao manda uma mensagem por tick", len(eventos) == 2,
          f"{len(eventos)} mensagens em 13 ticks")


def test_fix_nao_empilha_no_reload():
    """/reloadlua reexecuta o arquivo. Se a marca de 'ja aplicado' fosse uma
    local do arquivo, o segundo patch envolveria a funcao JA patcheada e cada
    expiracao contaria dobrado, cortando MAX_REARMS pela metade."""
    lua = new_env(load_mod=True)
    lua.execute(f'dofile("{MOD_LUA}")')  # simula o reload
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("fix: reload nao duplica a contagem de rearmes",
          b.fishingMPFix_rearms == 1, f"rearms={b.fishingMPFix_rearms}")
    check("fix: reload nao quebra o rearme", b.nibbleTimer > 100,
          f"nibbleTimer={b.nibbleTimer}")


def test_fix_nao_toca_singleplayer():
    """Em SP o flag chega certo; o mod nao pode alterar o balanceamento."""
    lua = new_env(load_mod=True, isMultiplayer=False, isServer=False)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("fix: singleplayer segue o vanilla", rod.removeLureCalls == 1,
          f"chamadas={rod.removeLureCalls}")


def test_fix_nao_toca_jogador_local():
    """No host de co-op a propria boia do host funciona: nao mexer nela.

    isClient()==false E isServer()==false com isMultiplayer()==true e o host
    de co-op, nao single-player: e exatamente por isso que o vanilla escreve
    "if not isClient()" e "if not isServer()" em blocos separados, para que o
    host execute os dois. Em SP o isMultiplayer() seria false, caso ja coberto
    por test_fix_nao_toca_singleplayer."""
    lua = new_env(load_mod=True, isServer=False)  # host: nem client, nem server
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance(),
        "isLocal": True}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    burn_fuse(lua, b)

    check("fix: boia do jogador local segue o vanilla", rod.removeLureCalls == 1,
          f"chamadas={rod.removeLureCalls}")


def test_fix_nao_interfere_quando_sync_funciona():
    """catchFishStarted chegou: o vanilla ja resolve, o mod fica fora do caminho."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.FishingState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5,
        "catchFishStarted": True}))

    burn_fuse(lua, b)

    check("fix: com sync ok, nada e punido", rod.removeLureCalls == 0)
    check("fix: com sync ok, o peixe fica", b.fish is not None)
    check("fix: com sync ok, vanilla congela o pavio (-1)", b.nibbleTimer == -1,
          f"nibbleTimer={b.nibbleTimer}")


def test_mp_vanilla_so_o_primeiro_jogador_pesca():
    """O relato da Oficina, reproduzido: com dois pescadores, o flag de quem
    recolhe a linha cai sempre na boia do PRIMEIRO da fila de acoes."""
    lua = new_env(load_mod=False)
    (rodA, A, bA), (rodB, B, bB) = two_anglers(lua)

    # B recolhe a linha; o servidor resolve o dono pelo id colidido -> A.
    flag_com_id_colidido(lua, A)

    check("vanilla mp: o flag caiu na boia do outro jogador",
          bool(bA.catchFishStarted) and not bool(bB.catchFishStarted),
          f"A={bA.catchFishStarted} B={bB.catchFishStarted}")

    for _ in range(400):
        lua.globals().Fishing.Bobber.update(bA)
        lua.globals().Fishing.Bobber.update(bB)

    check("vanilla mp: o primeiro jogador fica com o peixe",
          bA.fish is not None and rodA.removeLureCalls == 0)
    check("vanilla mp: o segundo perde peixe e isca (No Catch)",
          bB.fish is None and rodB.removeLureCalls == 1,
          f"fish={bB.fish} removeLure={rodB.removeLureCalls}")


def test_mp_relay_entrega_o_flag_na_boia_certa():
    """A correcao: o cliente avisa o servidor por OnClientCommand, que resolve
    o jogador pela CONEXAO. O flag chega na boia de quem recolheu."""
    lua = new_env(load_mod=True)
    (rodA, A, bA), (rodB, B, bB) = two_anglers(lua)

    client_command(lua, "FishingMPFix", "catch", B)

    check("relay: a boia de quem recolheu recebeu o flag",
          bool(bB.catchFishStarted), f"B={bB.catchFishStarted}")
    check("relay: a boia do outro jogador nao foi tocada",
          not bool(bA.catchFishStarted), f"A={bA.catchFishStarted}")

    for _ in range(400):
        lua.globals().Fishing.Bobber.update(bB)

    check("relay: o segundo jogador fica com o peixe", bB.fish is not None)
    check("relay: a isca continua na vara", rodB.removeLureCalls == 0)
    check("relay: nem precisou rearmar o pavio",
          bB.fishingMPFix_rearms is None, f"rearms={bB.fishingMPFix_rearms}")


def test_mp_relay_ignora_modulo_e_comando_alheios():
    """Nada de reagir a mensagem de outro mod."""
    lua = new_env(load_mod=True)
    (_, A, bA), (_, B, bB) = two_anglers(lua)

    client_command(lua, "OutroMod", "catch", B)
    client_command(lua, "FishingMPFix", "outraCoisa", B)

    check("relay: so responde ao proprio modulo e comando",
          not bool(bB.catchFishStarted) and not bool(bA.catchFishStarted))


def test_mp_fallback_rearma_quando_o_relay_nao_chega():
    """Cliente desatualizado ou pacote perdido: a rede de seguranca antiga
    continua de pe e o segundo jogador nao perde a isca."""
    lua = new_env(load_mod=True)
    (_, A, bA), (rodB, B, bB) = two_anglers(lua, nibble=0.5)

    flag_com_id_colidido(lua, A)   # o flag vai para o jogador errado
    burn_fuse(lua, bB)

    check("fallback: sem relay, o pavio ainda e rearmado", bB.nibbleTimer > 100,
          f"nibbleTimer={bB.nibbleTimer}")
    check("fallback: a isca continua na vara", rodB.removeLureCalls == 0)


def test_fix_reconhece_vara_recriada_pelo_servidor():
    """A prova da vara na mao nao pode depender da IDENTIDADE do InventoryItem.

    Kahlua compara objetos Java por referencia (BaseLib.luaEquals -> if_acmpne).
    Se o servidor ressincroniza o inventario e troca a instancia, a comparacao
    antiga dizia "nao esta mais pescando" e o mod virava inerte -- em silencio,
    exatamente o que o relato descreve.
    """
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod(lua.table_from({"rodId": 7}))
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.IdleState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    # mesma vara, outra instancia: e o que o jogador tem na mao agora
    player._primaryHand = g.makeItem(7)

    burn_fuse(lua, b)

    check("vara recriada: ainda reconhece que esta pescando", b.nibbleTimer > 100,
          f"nibbleTimer={b.nibbleTimer}")
    check("vara recriada: a isca continua na vara", rod.removeLureCalls == 0)


def test_fix_pune_quem_guardou_outra_vara():
    """Trocar para OUTRA vara continua sendo 'parou de pescar'."""
    lua = new_env(load_mod=True)
    g = lua.globals()
    rod = g.makeRod(lua.table_from({"rodId": 7}))
    player = g.makePlayer(lua.table_from({
        "primaryHand": rod.rodItem, "state": g.IdleState.instance()}))
    b = g.makeHookedBobber(lua.table_from({
        "rod": rod, "player": player, "nibbleTimer": 0.5}))

    player._primaryHand = g.makeItem(99)   # outro item na mao

    burn_fuse(lua, b)

    check("outra vara: o vanilla volta a punir", rod.removeLureCalls == 1,
          f"chamadas={rod.removeLureCalls}")


def test_relay_cliente_avisa_uma_vez_por_fisgada():
    """O lado cliente: um unico pacote por lancamento, no momento em que o
    vanilla marca catchFishStarted na boia local."""
    lua = new_relay_env()
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "onlineID": 5, "username": "fisher", "isLocal": True,
        "primaryHand": rod.rodItem}))
    bobber = g.makeHookedBobber(lua.table_from({"rod": rod, "player": player}))
    rod.bobber = bobber
    g.Fishing.ManagerInstances["fisher"] = lua.table_from(
        {"player": player, "fishingRod": rod})

    relay_tick(lua, 5)
    check("relay cliente: calado enquanto ninguem recolhe",
          len(g.SentClientCommands) == 0, f"{len(g.SentClientCommands)}")

    bobber.catchFishStarted = True     # o vanilla marca ao comecar a recolher
    relay_tick(lua, 30)

    check("relay cliente: mandou exatamente um pacote",
          len(g.SentClientCommands) == 1, f"{len(g.SentClientCommands)}")
    if len(g.SentClientCommands) == 1:
        cmd = g.SentClientCommands[1]
        check("relay cliente: modulo e comando corretos",
              cmd.module == "FishingMPFix" and cmd.command == "catch",
              f"{cmd.module}/{cmd.command}")
        check("relay cliente: mandou em nome do proprio jogador",
              cmd.player.getUsername(cmd.player) == "fisher")


def test_relay_cliente_avisa_de_novo_no_proximo_lancamento():
    """Boia nova, fisgada nova: o aviso tem de sair outra vez."""
    lua = new_relay_env()
    g = lua.globals()
    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({
        "onlineID": 5, "username": "fisher", "isLocal": True,
        "primaryHand": rod.rodItem}))
    g.Fishing.ManagerInstances["fisher"] = lua.table_from(
        {"player": player, "fishingRod": rod})

    for _ in range(2):
        bobber = g.makeHookedBobber(lua.table_from({"rod": rod, "player": player}))
        rod.bobber = bobber
        relay_tick(lua, 2)
        bobber.catchFishStarted = True
        relay_tick(lua, 2)

    check("relay cliente: um aviso por lancamento",
          len(g.SentClientCommands) == 2, f"{len(g.SentClientCommands)}")


def test_relay_cliente_nao_quebra_sem_pescaria():
    """Sem manager, sem vara ou sem boia o tick tem de passar batido."""
    lua = new_relay_env()
    g = lua.globals()
    relay_tick(lua, 3)

    rod = g.makeRod()
    player = g.makePlayer(lua.table_from({"username": "fisher", "isLocal": True}))
    g.Fishing.ManagerInstances["fisher"] = lua.table_from(
        {"player": player, "fishingRod": rod})    # rod sem bobber
    relay_tick(lua, 3)

    check("relay cliente: nao manda nada sem boia na agua",
          len(g.SentClientCommands) == 0, f"{len(g.SentClientCommands)}")


def test_ui_caixa_cabe_rotulo_e_contador():
    """O caso apertado: rotulo longo + contador de dois digitos. Com largura
    fixa os dois se sobrepoem; medindo, a caixa cresce e sobra folga."""
    lua = new_ui_env()
    hud_send(lua, "rearmed", fuse=360, rearms=20)
    ui, drawn = hud_draw(lua)

    esq = texts_by_align(drawn, "left")[0]
    dir_ = texts_by_align(drawn, "right")[0]
    fim_esq = lua.globals().textBounds(esq)
    ini_dir = lua.globals().textBounds(dir_)

    check("ui: rotulo e contador nao se sobrepoem",
          ini_dir[0] >= fim_esq[1], f"rotulo termina em {fim_esq[1]}, contador comeca em {ini_dir[0]}")
    check("ui: o contador cabe dentro da caixa",
          ini_dir[1] <= ui.width, f"contador termina em {ini_dir[1]}, caixa tem {ui.width}")
    check("ui: a caixa cresceu para caber os dois",
          ui.width > 148, f"largura={ui.width}")


def test_ui_largura_minima_quando_o_texto_e_curto():
    """Sem contador e com rotulo curto, a caixa nao pode encolher a ponto de a
    barra virar um risco."""
    lua = new_ui_env()
    hud_send(lua, "hooked", fuse=360, rearms=0)
    ui, drawn = hud_draw(lua)

    check("ui: respeita a largura minima", ui.width == 148, f"largura={ui.width}")
    check("ui: sem contador, so um texto na linha",
          len(texts_by_align(drawn, "right")) == 0)


def test_ui_remede_quando_a_fase_muda():
    """Cada fase tem um rotulo de tamanho diferente; a caixa acompanha."""
    lua = new_ui_env()
    hud_send(lua, "hooked", rearms=0)
    curta, _ = hud_draw(lua)
    largura_curta = curta.width

    hud_send(lua, "rearmed", rearms=13)
    longa, _ = hud_draw(lua)

    check("ui: a largura mudou junto com o texto",
          longa.width > largura_curta,
          f"{largura_curta} -> {longa.width}")


def test_ui_altura_vem_da_fonte_e_o_pop_cabe():
    """Altura = folga do +1 + padding + linha + barra. Nada em pixel cravado."""
    lua = new_ui_env()
    hud_send(lua, "rearmed", rearms=1)
    ui, drawn = hud_draw(lua)

    # Small=12, Medium=16 nos stubs; POP_RISE=34
    esperado = (16 + 34) + 6 + 12 + 6 + 5 + 6
    check("ui: altura derivada das metricas de fonte", ui.height == esperado,
          f"altura={ui.height}, esperado={esperado}")

    pop = texts_by_align(drawn, "centre")[0]
    check("ui: o +1 e desenhado dentro do elemento", pop.y >= 0,
          f"y do pop={pop.y}")


def test_ui_fica_presa_a_tela_na_borda():
    """Personagem colado na borda: a caixa encosta em vez de sair da tela."""
    lua = new_ui_env()
    lua.execute("function isoToScreenX() return ScreenW - 2 end")
    hud_send(lua, "hooked", rearms=0)
    ui, _ = hud_draw(lua)

    check("ui: nao ultrapassa a borda direita",
          ui.x + ui.width <= lua.globals().ScreenW,
          f"x={ui.x} + largura={ui.width} > {lua.globals().ScreenW}")


def test_ui_some_quando_o_jogador_para_de_pescar():
    """O painel nao pode ficar preso na tela depois que a pessoa larga a vara.

    O fim da fisgada chega por mensagem do servidor ("caught"/"lost"), e essa
    mensagem so existe se Bobber:update rodar mais uma vez com o pavio apagado.
    Quando o jogador para de pescar a boia e DESTRUIDA: o update nao roda de
    novo, a transicao nunca acontece e nada e enviado. Sem uma checagem local o
    painel fica em "Bite held" para sempre, seguindo alguem que nem vara na mao
    tem mais.
    """
    lua = new_ui_env()
    g = lua.globals()

    hud_send(lua, "rearmed", fuse=360, rearms=1)
    _, drawn = hud_draw(lua)
    check("ui: durante a fisgada o painel aparece", len(drawn.texts) > 0,
          "nada foi desenhado com a fisgada ativa")

    g.setPlayerFishing(False)      # guardou a vara: saiu do FishingState
    hud_tick(lua)
    _, drawn = hud_draw(lua)

    textos = [drawn.texts[i].text for i in range(1, len(drawn.texts) + 1)]
    check("ui: o painel some quando a pescaria acaba", len(textos) == 0,
          f"ainda desenhando {textos}")


def test_ui_nao_some_no_meio_da_fisgada():
    """A checagem nao pode derrubar o painel de quem ainda esta pescando."""
    lua = new_ui_env()
    hud_send(lua, "rearmed", fuse=360, rearms=1)
    hud_tick(lua, n=5)
    _, drawn = hud_draw(lua)

    check("ui: quem continua pescando mantem o painel", len(drawn.texts) > 0,
          "o painel sumiu com a fisgada ainda ativa")


def test_ui_atalho_aparece_nas_opcoes():
    """A tela de Key Bindings e montada a partir da tabela global keyBinding.
    Chamar getCore():addKeyBinding sozinho registra a tecla mas nao a mostra
    nas opcoes — e o jogador fica sem como remapear quando o padrao ja esta
    ocupado por outro mod."""
    lua = new_ui_env()
    kb = lua.globals().keyBinding
    entradas = [kb[i] for i in range(1, len(kb) + 1)]
    valores = [e.value for e in entradas]

    check("ui: registra a secao do mod nas opcoes",
          "[No Catch Fix]" in valores, f"valores={valores}")

    nossa = [e for e in entradas if e.value and e.value.startswith("FishingMPFix")]
    check("ui: registra a acao remapeavel", len(nossa) == 1,
          f"encontradas={len(nossa)}")
    if nossa:
        check("ui: com uma tecla padrao definida", nossa[0].key is not None,
              f"key={nossa[0].key}")


# ---------------------------------------------------------------------------
# Fishing Panel (clique direito na agua) -- FishWindow.lua REAL do jogo
# ---------------------------------------------------------------------------

PANEL_LUA = HERE.parent / "42/media/lua/client/FishingMPFix_Panel.lua"
VANILLA_FISHWINDOW = paths.game() / "media/lua/client/PZAPI/ui/organisms/FishWindow.lua"
VANILLA_META = paths.game() / "media/lua/client/PZAPI/ui/atoms/Meta.lua"


def new_panel_env(with_fix: bool, player_name="fisher"):
    """Cliente MP com o painel vanilla carregado e (opcionalmente) o conserto."""
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'dofile("{HERE / "pz_stubs.lua"}")')
    g = lua.globals()
    g.TestEnv["isClient"] = True
    g.TestEnv["isServer"] = False
    g.TestEnv["metaPath"] = str(VANILLA_META)
    lua.execute(f'dofile("{HERE / "panel_stubs.lua"}")')
    lua.execute(f'dofile("{VANILLA_FISHWINDOW}")')
    g.CurrentPlayer = g.makePanelPlayer(player_name)
    if with_fix:
        lua.execute(f'dofile("{PANEL_LUA}")')
        lua.execute("for _, fn in ipairs(Events.OnGameStart.handlers) do fn() end")
    return lua


def test_painel_vanilla_reproduz_a_enxurrada_de_erros():
    """Sem o conserto: a modData do jogador chega do servidor (wipe + load) sem
    fishing_catchedFish e cada linha de peixe erra em todo frame."""
    lua = new_panel_env(with_fix=False)
    g = lua.globals()
    _, info = g.openPanel()
    n, _ = g.frame(info)
    check("painel vanilla: frame normal nao erra", n == 0, f"erros={n}")
    g.CurrentPlayer.modData = lua.table_from({})       # o wipe do ObjectModDataPacket
    n, err = g.frame(info)
    check("painel vanilla: uma linha errando por especie de peixe",
          n == len(g.Fishing.fishes), f"erros={n} ({err})")


def test_painel_fix_nao_erra_depois_do_wipe():
    lua = new_panel_env(with_fix=True)
    g = lua.globals()
    _, info = g.openPanel()
    g.CurrentPlayer.modData = lua.table_from({})
    total = sum(g.frame(info)[0] for _ in range(5))
    check("painel fix: nenhum erro apos o wipe", total == 0, f"erros={total}")
    check("painel fix: a tabela voltou a existir",
          lua.eval("type(CurrentPlayer.modData.fishing_catchedFish)") == "table")


def test_painel_fix_recupera_o_historico_do_servidor():
    """A lista que o servidor guarda (fishing_CatchDone_*) aparece no painel,
    inclusive peixes pescados antes de o mod existir."""
    lua = new_panel_env(with_fix=False)
    g = lua.globals()
    g.CurrentPlayer.modData = lua.table_from({"fishing_CatchDone_Base.Bass": True})
    lua.execute(f'dofile("{PANEL_LUA}")')
    lua.execute("for _, fn in ipairs(Events.OnGameStart.handlers) do fn() end")
    _, info = g.openPanel()
    g.frame(info)
    bass = g.rowOf(info, "Base.Bass").children.text.text
    crappie = g.rowOf(info, "Base.Crappie").children.text.text
    check("painel fix: peixe gravado pelo servidor aparece pelo nome",
          bass == "name:Base.Bass", f"{bass}")
    check("painel fix: peixe nunca pescado continua ---", crappie == "---", f"{crappie}")


def test_painel_fix_pega_captura_nova_com_o_painel_aberto():
    lua = new_panel_env(with_fix=True)
    g = lua.globals()
    _, info = g.openPanel()
    g.frame(info)
    g.CurrentPlayer.modData = lua.table_from({"fishing_CatchDone_Base.Catfish": True})
    for _ in range(61):                                  # ate a proxima leitura (~1 s)
        g.frame(info)
    txt = g.rowOf(info, "Base.Catfish").children.text.text
    check("painel fix: captura nova aparece sem reabrir", txt == "name:Base.Catfish", f"{txt}")


def test_painel_fix_segue_o_personagem_novo_apos_morrer():
    lua = new_panel_env(with_fix=True, player_name="morto")
    g = lua.globals()
    _, info = g.openPanel()
    g.frame(info)
    novo = g.makePanelPlayer("renascido")
    novo.modData = lua.table_from({"fishing_CatchDone_Base.Crappie": True})
    g.CurrentPlayer = novo
    g.frame(info)
    nomes = {row.player.name for row in info.children.values()
             if lua.eval("type")(row) == "table" and row.fishType}
    check("painel fix: todas as linhas apontam para o personagem atual",
          nomes == {"renascido"}, f"{nomes}")
    txt = g.rowOf(info, "Base.Crappie").children.text.text
    check("painel fix: mostra o catalogo do personagem atual", txt == "name:Base.Crappie", f"{txt}")


def test_painel_fix_sem_jogador_pula_o_frame():
    """Tela de morte / carregamento: getPlayer() nil nao pode virar erro."""
    lua = new_panel_env(with_fix=True)
    g = lua.globals()
    _, info = g.openPanel()
    g.CurrentPlayer = None
    ok = lua.eval("function(info) return (pcall(info.update, info)) end")(info)
    check("painel fix: sem jogador, o update do info nao erra", ok)


def test_painel_fix_desliga_sozinho_se_o_layout_mudar():
    """Se um update do jogo mover o painel, o mod avisa e sai do caminho."""
    lua = new_panel_env(with_fix=False)
    g = lua.globals()
    g.PZAPI.UI.FishWindow.children.body = None
    lua.execute(f'dofile("{PANEL_LUA}")')
    check("painel fix: layout desconhecido nao aplica e nao quebra",
          g.FishingMPFixPanel.templatePatched is False)


def test_painel_fix_nao_empilha_no_reload():
    lua = new_panel_env(with_fix=True)
    g = lua.globals()
    lua.execute("_antes = PZAPI.UI.FishWindow.children.body.children.tabPanel.children.info.update")
    g.FishingMPFixPanel.templatePatched = False
    lua.execute(f'dofile("{PANEL_LUA}")')
    igual = lua.eval("_antes == PZAPI.UI.FishWindow.children.body.children.tabPanel.children.info.update")
    check("painel fix: recarregar nao embrulha de novo", igual is True)


def test_painel_fix_nao_carrega_no_servidor():
    lua = LuaRuntime(unpack_returned_tuples=True)
    lua.execute(f'dofile("{HERE / "pz_stubs.lua"}")')
    lua.execute(f'dofile("{PANEL_LUA}")')
    check("painel fix: inerte no processo do servidor",
          lua.globals().FishingMPFixPanel is None)


TESTS = [
    test_vanilla_reproduz_o_bug,
    test_fix_mantem_isca_com_jogador_pescando,
    test_fix_preserva_vanilla_se_parou_de_pescar,
    test_fix_pune_quem_parou_de_pescar_mas_segura_a_vara,
    test_fix_funciona_em_servidor_dedicado,
    test_fix_nao_prende_peixe_lixo,
    test_fix_desiste_apos_o_limite,
    test_fix_sequencia_realista_de_rearmes,
    test_fix_zera_contagem_apos_captura,
    test_contador_so_conta_save_de_verdade,
    test_fix_nao_empilha_no_reload,
    test_debug_simulate_desync_reproduz_o_bug_solo,
    test_debug_com_o_fix_ligado_salva_a_fisgada,
    test_debug_inerte_quando_o_arquivo_nao_existe,
    test_hud_recebe_as_transicoes,
    test_hud_nao_avisa_nada_em_boia_recem_lancada,
    test_convive_com_mod_que_substitui_o_update,
    test_fix_nao_toca_singleplayer,
    test_fix_nao_toca_jogador_local,
    test_fix_nao_interfere_quando_sync_funciona,
    test_mp_vanilla_so_o_primeiro_jogador_pesca,
    test_mp_relay_entrega_o_flag_na_boia_certa,
    test_mp_relay_ignora_modulo_e_comando_alheios,
    test_mp_fallback_rearma_quando_o_relay_nao_chega,
    test_fix_reconhece_vara_recriada_pelo_servidor,
    test_fix_pune_quem_guardou_outra_vara,
    test_relay_cliente_avisa_uma_vez_por_fisgada,
    test_relay_cliente_avisa_de_novo_no_proximo_lancamento,
    test_relay_cliente_nao_quebra_sem_pescaria,
    test_ui_caixa_cabe_rotulo_e_contador,
    test_ui_largura_minima_quando_o_texto_e_curto,
    test_ui_remede_quando_a_fase_muda,
    test_ui_altura_vem_da_fonte_e_o_pop_cabe,
    test_ui_fica_presa_a_tela_na_borda,
    test_ui_some_quando_o_jogador_para_de_pescar,
    test_ui_nao_some_no_meio_da_fisgada,
    test_ui_atalho_aparece_nas_opcoes,
    test_painel_vanilla_reproduz_a_enxurrada_de_erros,
    test_painel_fix_nao_erra_depois_do_wipe,
    test_painel_fix_recupera_o_historico_do_servidor,
    test_painel_fix_pega_captura_nova_com_o_painel_aberto,
    test_painel_fix_segue_o_personagem_novo_apos_morrer,
    test_painel_fix_sem_jogador_pula_o_frame,
    test_painel_fix_desliga_sozinho_se_o_layout_mudar,
    test_painel_fix_nao_empilha_no_reload,
    test_painel_fix_nao_carrega_no_servidor,
]

if __name__ == "__main__":
    if not VANILLA_BOBBER.exists():
        sys.exit(f"Bobber.lua do jogo nao encontrado em {VANILLA_BOBBER}")
    for t in TESTS:
        print(f"\n{t.__name__}")
        try:
            t()
        except Exception as exc:
            FAIL.append(t.__name__)
            print(f"  ERRO  {type(exc).__name__}: {exc}")
    print(f"\n{'=' * 60}\n{len(PASS)} passaram, {len(FAIL)} falharam")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1 if FAIL else 0)

--[[
    FishingMPFix - MODO DE TESTE

    !!! NAO DISTRIBUIR !!!
    Este arquivo quebra a pesca de proposito. Ele nao acompanha o mod publicado
    e nao deve ficar no servidor de verdade. Use tools/debug_mode.py para
    ligar e desligar; o build_vdf.py se recusa a publicar com ele presente.

    PARA QUE SERVE
    --------------
    O bug so aparece com 2+ jogadores conectados, o que torna cada tentativa
    dependente de juntar duas pessoas. Com SIMULATE_DESYNC da para reproduzir o
    mesmo defeito sozinho, num co-op hospedado na sua propria maquina.

    COMO USAR
    ---------
    1. tools/debug_mode.py on          (copia este arquivo para o mod)
    2. No jogo: HOST -> inicie um co-op, entre sozinho
    3. Painel de admin -> ligue "Fishing Cheat" (o peixe morde em ~1s)
    4. Pesque e observe o indicador na tela (F7)

    A/B QUE INTERESSA
    -----------------
    DISABLE_FIX = true   -> voce ve O BUG: barra zera, "Fisgada perdida",
                            isca some. E o comportamento que os jogadores
                            relatam no servidor.
    DISABLE_FIX = false  -> voce ve O FIX: "Fisgada mantida - salvo Nx",
                            a isca fica, o peixe entra.

    Rodar os dois em sequencia prova o fix sem depender de sorte na pescaria.

    5. tools/debug_mode.py off         (remove antes de publicar ou de jogar)
]]

FishingMPFixDebug = {
    -- Finge que o catchFishStarted nunca chega, como acontece em MP quando o
    -- flag e entregue na boia errada. E o que reproduz o bug sozinho.
    SIMULATE_DESYNC = true,

    -- Em co-op solo o unico pescador e o host, e o mod ignora a boia do host
    -- de proposito (ela nao tem o bug de verdade). Sem isto, nada acontece.
    INCLUDE_LOCAL = true,

    -- Alterne este para comparar os dois lados.
    --   true  = ve o bug (fix desligado)
    --   false = ve o fix agindo
    DISABLE_FIX = false,
}

print("[FishingMPFix] *** MODO DE TESTE ATIVO ***"
      .. "  SIMULATE_DESYNC=" .. tostring(FishingMPFixDebug.SIMULATE_DESYNC)
      .. "  DISABLE_FIX=" .. tostring(FishingMPFixDebug.DISABLE_FIX)
      .. "  -- nao use em servidor de producao")

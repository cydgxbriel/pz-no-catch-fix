-- Stubs minimos da API do Project Zomboid, suficientes para carregar e exercitar
-- o Bobber.lua real do jogo fora da engine.

TestEnv = {
    isClient = false,      -- servidor dedicado
    isServer = true,
    isMultiplayer = true,
    tickMultiplier = 1.0,
}

function isClient() return TestEnv.isClient end
function isServer() return TestEnv.isServer end
function isMultiplayer() return TestEnv.isMultiplayer end

function getGameTime()
    return { getMultiplier = function() return TestEnv.tickMultiplier end }
end
GameTime = { getInstance = function() return { getTimeOfDay = function() return 12 end } end }

function ZombRand(n) return 0 end

-- Captura as mensagens servidor -> cliente que alimentam a HUD.
SentServerCommands = {}
function sendServerCommand(player, module, command, args)
    table.insert(SentServerCommands,
                 { module = module, command = command, args = args })
end

-- Captura as mensagens cliente -> servidor do relay de fisgada.
SentClientCommands = {}
function sendClientCommand(player, module, command, args)
    table.insert(SentClientCommands,
                 { player = player, module = module, command = command,
                   args = args })
end

IsoUtils = {
    DistanceTo = function(x1, y1, x2, y2)
        local dx, dy = x2 - x1, y2 - y1
        return math.sqrt(dx * dx + dy * dy)
    end
}

-- Events: registra callbacks sem executar nada
local function newEvent()
    local e = { handlers = {} }
    e.Add = function(fn) table.insert(e.handlers, fn) end
    e.Remove = function(fn) end
    return e
end
Events = setmetatable({}, {
    __index = function(t, k)
        local e = newEvent()
        rawset(t, k, e)
        return e
    end
})

-- Dependencias do Bobber.lua que nao participam do caminho testado
FishSchoolManager = { getInstance = function() return { getFishAbundance = function() return 20 end } end }
function getClimateManager()
    return {
        getAirTemperatureForCharacter = function() return 20 end,
        getFogIntensity = function() return 0 end,
        getWindPower = function() return 0 end,
    }
end
RainManager = { isRaining = function() return false end }
function getCell() return { getGridSquare = function() return {} end } end
function instanceItem() return {} end
function Render3DItem() end
ItemKey = { Normal = { BOBBER = "Base.Bobber" } }
function startFishingAction() return 1 end
function removeAction() end

Fishing = Fishing or {}
-- Registro dos FishingManager locais, que o Bobber.lua vanilla nao cria (quem
-- cria e client/Fishing/FishingHandler.lua, indexado pelo username em MP).
Fishing.ManagerInstances = Fishing.ManagerInstances or {}
Fishing.Utils = {
    isWaterCoords = function() return true end,
    isNearShore = function() return false end,
}
Fishing.Fish = {}

-- ---------------------------------------------------------------------------
-- Dublês controlaveis pelos testes
-- ---------------------------------------------------------------------------

FishingState = {
    _instance = { name = "FishingState" },
    instance = function() return FishingState._instance end,
}

-- O estado que o servidor dedicado realmente ve num jogador remoto. Quem entra
-- em FishingState e IsoPlayer.setFishingStage, atras de um if (GameClient.client),
-- e a outra porta e o evento EventFishing, disparado so por
-- client/Fishing/FishingStates.lua:55 -- nenhum dos dois roda no servidor.
IdleState = {
    _instance = { name = "IdleState" },
    instance = function() return IdleState._instance end,
}

function makePlayer(opts)
    opts = opts or {}
    local p = {
        _onlineID = opts.onlineID or 1,
        _local = opts.isLocal or false,
        _state = opts.state,           -- FishingState.instance() quando pescando
        _primaryHand = opts.primaryHand,
        _username = opts.username or ("player" .. tostring(opts.onlineID or 1)),
    }
    function p:getX() return 10 end
    function p:getY() return 10 end
    function p:getOnlineID() return self._onlineID end
    function p:getUsername() return self._username end
    function p:isLocalPlayer() return self._local end
    function p:getCurrentState() return self._state end
    function p:getPrimaryHandItem() return self._primaryHand end
    function p:isFishingCheat() return false end
    function p:playSound() end
    function p:getForwardDirection() return { getDirection = function() return 0 end } end
    return p
end

-- Um InventoryItem tem identidade de objeto Java, mas o servidor pode trocar a
-- instancia ao ressincronizar o inventario; o que sobrevive e o getID().
function makeItem(id)
    local item = { id = id or 1 }
    function item:getID() return self.id end
    return item
end

function makeRod(opts)
    opts = opts or {}
    local rod = {
        rodItem = opts.rodItem or makeItem(opts.rodId or 1),
        removeLureCalls = 0,
        _tension = opts.tension or 0.5,
    }
    function rod:getTension() return self._tension end
    function rod:getRodEndXY() return 10, 10 end
    function rod:removeLure() self.removeLureCalls = self.removeLureCalls + 1 end
    return rod
end

-- Coloca um peixe numa boia que estava vazia, como o servidor faz na mordida.
function giveFish(bobber, nibbleTimer, isTrash)
    bobber.fish = { isTrash = isTrash or false, dx = 0, dy = 0,
                    update = function() end }
    bobber.nibbleTimer = nibbleTimer or 360
end

-- Constroi um Bobber ja "no meio da fisgada": peixe fisgado, pavio aceso.
function makeHookedBobber(opts)
    opts = opts or {}
    local rod = opts.rod or makeRod()
    local player = opts.player or makePlayer({ primaryHand = rod.rodItem })

    -- Bobber:new faz "self.__index = self"; como nao chamamos new (precisaria da
    -- engine inteira), replicamos so isso para os metodos resolverem.
    Fishing.Bobber.__index = Fishing.Bobber
    local b = setmetatable({}, Fishing.Bobber)
    b.player = player
    b.fishingRod = rod
    b.x, b.y, b.z = 12, 12, 0
    b.attractTimer = 99999          -- fora do caminho testado
    b.nibbleTimer = opts.nibbleTimer or 360
    b.catchFishStarted = opts.catchFishStarted or false
    b.fish = opts.fish
    if b.fish == nil and not opts.noFish then
        b.fish = { isTrash = opts.isTrash or false, dx = 0, dy = 0,
                   update = function() end }
    end
    b.lure = "Base.Worm"
    b.fishingLvl = 1
    return b
end

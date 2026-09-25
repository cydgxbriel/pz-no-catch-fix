-- Stubs para carregar o FishWindow.lua REAL do jogo fora da engine.
--
-- O Meta.lua do PZAPI tambem e o real (TestEnv.metaPath): e ele que define como
-- um template vira instancia (__call copia e mescla), e o conserto depende de o
-- wrapper posto no template chegar na instancia. So a parte Java (AtomUI) e
-- fingida aqui: `frame()` imita AtomUI.update, que roda o update Lua do no
-- ANTES dos filhos e cada um dentro de pcall -- por isso o bug vira enxurrada
-- de erro e nao crash.

function require() end

PZAPI = { UI = { Extensions = { Hooks = {} } } }
dofile(TestEnv.metaPath)
local UI = PZAPI.UI

-- Metodos que no jogo vem das extensoes Java/Lua; aqui so guardam o valor.
local base = {
    setText = function(self, t) self.text = t end,
    setColor = function(self, r, g, b, a) self.color = { r, g, b, a } end,
    setTexture = function(self, t) self.texture = t end,
    setHeight = function(self, h) self.height = h end,
    setWidth = function(self, w) self.width = w end,
    setX = function(self, x) self.x = x end,
    setY = function(self, y) self.y = y end,
    setScaleX = function(self, s) self.scaleX = s end,
    setScaleY = function(self, s) self.scaleY = s end,
    setVisible = function(self, v) self.visible = v end,
    setEnabled = function(self, v) self.enable = v end,
}
UI.Node = setmetatable(base, UI._mt)
UI.Texture = UI.Node{}
UI.Text = UI.Node{}
UI.Panel = UI.Node{}
UI.TabPanel = UI.Node{}
UI.Window = UI.Node{
    children = {
        bar = UI.Panel{
            children = {
                settingsButton = UI.Node{},
                infoButton = UI.Node{},
                closeButton = UI.Node{ sounds = { activate = "click" } },
            }
        },
        body = UI.Node{ height = 400 },
        bottomBar = UI.Node{ children = { resizeButton = UI.Node{} } },
    }
}

local function fakeJava()
    return {
        getTextHeight = function() return 12 end,
        setAutoWidth = function() end,
        getLuaAbsolutePosition = function() return { x = 0, y = 0 } end,
    }
end

-- O jogo cria o objeto Java e roda o init; aqui so o init importa.
function UI._addChild(parent, child)
    UI._setParentChildRelationship(child)
    child.parent = parent
    child.javaObj = fakeJava()
    for _, c in pairs(child.children or {}) do c.javaObj = fakeJava() end
    if child.init then child:init() end
end

-- API do jogo usada pelo painel ------------------------------------------------

Perks = { Fishing = "Fishing" }
function getText(key) return key end
function getTexture(path) return path end
function getItemNameFromFullType(t) return "name:" .. t end
function getScriptManager() return { FindItem = function() return nil end } end

local color = { getR = function() return 1 end, getG = function() return 1 end,
                getB = function() return 1 end }
function getCore()
    return {
        getGoodHighlitedColor = function() return color end,
        getBadHighlitedColor = function() return color end,
        getScreenHeight = function() return 1080 end,
        getScreenWidth = function() return 1920 end,
    }
end

Fishing = Fishing or {}
Fishing.fishes = {
    { itemType = "Base.Bass" },
    { itemType = "Base.Crappie" },
    { itemType = "Base.Catfish" },
}
Fishing.Utils = Fishing.Utils or {}
Fishing.Utils.getTimeParams = function() return { coeff = 1 } end
Fishing.Utils.getTemperatureParams = function() return { coeff = 1 } end
Fishing.Utils.getWeatherParams = function() return { coeff = 1 } end

function makePanelPlayer(name)
    local p = { name = name, modData = {} }
    function p:getModData() return self.modData end
    function p:getPerkLevel() return 0 end
    return p
end

CurrentPlayer = nil
function getPlayer() return CurrentPlayer end
function getNumActivePlayers() return CurrentPlayer and 1 or 0 end
function getSpecificPlayer(i) return CurrentPlayer end

-- Abre o painel como o openFishWindow do jogo: instancia o template e roda os
-- init (o do info cria as linhas de peixe).
function openPanel()
    local w = UI.FishWindow{}
    UI._setParentChildRelationship(w)
    local info = w.children.body.children.tabPanel.children.info
    info:init()
    return w, info
end

-- Um frame da engine: update do info, depois o de cada linha, cada um em pcall.
-- Devolve quantos erros sairiam no console.
function frame(info)
    local errors = {}
    if info.update then
        local ok, err = pcall(info.update, info)
        if not ok then table.insert(errors, err) end
    end
    for _, row in pairs(info.children) do
        if type(row) == "table" and row.fishType and row.update then
            local ok, err = pcall(row.update, row)
            if not ok then table.insert(errors, err) end
        end
    end
    return #errors, errors[1]
end

function rowOf(info, fishType)
    return info.children[fishType]
end

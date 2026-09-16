-- Stubs da API de UI do Project Zomboid, o suficiente para carregar o
-- FishingMPFix_HUD.lua fora da engine e inspecionar o que ele desenha.

-- O jogo carrega ISUI antes; nos testes o require e um no-op.
function require() end

-- Tabela global que a tela de Key Bindings monta (shared/keyBinding.lua).
keyBinding = {}

UIFont = { Small = "Small", Medium = "Medium", Large = "Large" }
Keyboard = { KEY_F7 = 65 }

-- Larguras por fonte, proporcionais ao texto, como a engine faria.
local CHAR_W  = { Small = 7, Medium = 11, Large = 15 }
local LINE_H  = { Small = 12, Medium = 16, Large = 22 }

function getTextManager()
    return {
        MeasureStringX = function(_, font, text)
            return #tostring(text) * (CHAR_W[font] or 7)
        end,
        MeasureStringY = function(_, font) return LINE_H[font] or 12 end,
        getFontHeight  = function(_, font) return LINE_H[font] or 12 end,
    }
end

ScreenW, ScreenH = 1920, 1080

function getCore()
    return {
        getScreenWidth  = function() return ScreenW end,
        getScreenHeight = function() return ScreenH end,
        addKeyBinding   = function() end,
        getKey          = function(_, name) return Keyboard.KEY_F7 end,
    }
end

-- Personagem no centro da tela.
function isoToScreenX() return ScreenW / 2 end
function isoToScreenY() return ScreenH / 2 end

TestPlayer = {
    getX = function() return 10 end,
    getY = function() return 10 end,
    getZ = function() return 0 end,
    getPlayerNum = function() return 0 end,
    Say = function(_, msg) LastSay = msg end,
    -- Enquanto pesca o jogador esta em FishingState; o proprio FishingManager
    -- vanilla encerra a pescaria assim que ele sai (FishingManager.lua:65).
    getCurrentState = function() return TestPlayer._state end,
}
TestPlayer._state = FishingState.instance()

function setPlayerFishing(on)
    TestPlayer._state = on and FishingState.instance() or nil
end

function getPlayer() return TestPlayer end

-- ---------------------------------------------------------------------------
-- ISUIElement minimo, gravando tudo que for desenhado
-- ---------------------------------------------------------------------------

Drawn = { rects = {}, borders = {}, texts = {} }

function resetDrawn()
    Drawn = { rects = {}, borders = {}, texts = {} }
end

ISUIElement = {}
ISUIElement.__index = ISUIElement

function ISUIElement:derive(name)
    local o = setmetatable({}, { __index = self })
    o.__index = o
    o.Type = name
    return o
end

function ISUIElement:new(x, y, w, h)
    local o = setmetatable({}, self)
    self.__index = self
    o.x, o.y, o.width, o.height = x, y, w, h
    o.javaObject = { setConsumeMouseEvents = function() end }
    return o
end

function ISUIElement:initialise() end
function ISUIElement:instantiate() end
function ISUIElement:addToUIManager() LastUI = self end
function ISUIElement:setVisible(v) self.javaObject.visible = v end
function ISUIElement:isVisible() return self.javaObject.visible end
function ISUIElement:setX(v) self.x = v end
function ISUIElement:setY(v) self.y = v end
function ISUIElement:getX() return self.x end
function ISUIElement:getY() return self.y end
function ISUIElement:setWidth(v) self.width = v end
function ISUIElement:setHeight(v) self.height = v end
function ISUIElement:getWidth() return self.width end
function ISUIElement:getHeight() return self.height end

function ISUIElement:drawRect(x, y, w, h, a)
    table.insert(Drawn.rects, { x = x, y = y, w = w, h = h, a = a })
end

function ISUIElement:drawRectBorder(x, y, w, h, a)
    table.insert(Drawn.borders, { x = x, y = y, w = w, h = h, a = a })
end

local function recordText(text, x, y, font, align)
    table.insert(Drawn.texts, {
        text = tostring(text), x = x, y = y, font = font, align = align,
        w = #tostring(text) * (CHAR_W[font] or 7),
    })
end

function ISUIElement:drawText(text, x, y, r, g, b, a, font)
    recordText(text, x, y, font, "left")
end

function ISUIElement:drawTextRight(text, x, y, r, g, b, a, font)
    recordText(text, x, y, font, "right")
end

function ISUIElement:drawTextCentre(text, x, y, r, g, b, a, font)
    recordText(text, x, y, font, "centre")
end

-- Bordas reais de um texto desenhado, ja considerando o alinhamento.
function textBounds(entry)
    if entry.align == "right" then
        return entry.x - entry.w, entry.x
    elseif entry.align == "centre" then
        return entry.x - entry.w / 2, entry.x + entry.w / 2
    end
    return entry.x, entry.x + entry.w
end

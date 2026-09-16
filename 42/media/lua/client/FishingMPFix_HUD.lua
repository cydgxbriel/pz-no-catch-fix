--[[
    FishingMPFix - bite indicator (client)

    A small panel just below the character during the fight with a fish, showing
    the time left before the server gives up on the bite. Every time the fix
    prevents that, a "+1" floats up.

    Without it the player has no way to tell "the fish got away" from "the
    server threw my fish out": in vanilla both look identical, the tension
    needle simply drops and "No catch" appears.

    The server sends only the transitions (hooked / re-armed / over); the
    countdown runs here, so there is no per-tick traffic.

    LAYOUT
    ------
    Nothing here has a fixed pixel size. The box is measured from the text it
    contains (MeasureStringX / getFontHeight), because the label changes from
    phase to phase, the counter grows from "saved 1x" to "saved 20x", and the
    font height depends on the player's UI scale. With a fixed width, label and
    counter overlap in the first tight case.

    Measuring runs when the text changes, not every frame.

    Default key to show/hide: F7 (rebindable in Key Bindings).
]]

if isServer() then return end

-- Makes sure ISUIElement exists before the derive below. The vanilla TensionUI
-- gets away without this by living in client/Fishing/, which loads after
-- client/ISUI/ - this file sits at the root of client/ and has no such
-- guarantee. A derive on top of nil would kill the whole file at load time.
require "ISUI/ISUIElement"

local KEY_NAME = "FishingMPFix: bite indicator"

-- 65 is the LWJGL code for F7. Vanilla never uses Keyboard.KEY_F7, so there is
-- no way to confirm the constant exists by reading the game; without the
-- fallback, a nil constant here would take the file down before anything loads.
local DEFAULT_KEY = (Keyboard and Keyboard.KEY_F7) or 65

-- The Key Bindings screen is built from the global `keyBinding` table
-- (shared/keyBinding.lua): the game itself iterates that list and calls
-- getCore():addKeyBinding for each entry. Calling addKeyBinding on our own
-- registers the key on the Java side but does NOT make it appear in the
-- options, leaving the player unable to rebind when the default is taken.
-- This has to run at file scope: by OnGameStart the screen is already built.
-- Entries whose value starts with "[" become a section header.
if keyBinding then
    local bind = {}
    bind.value = "[No Catch Fix]"
    table.insert(keyBinding, bind)

    bind = {}
    bind.value = KEY_NAME
    bind.key = DEFAULT_KEY
    table.insert(keyBinding, bind)
end

local FONT       = UIFont.Small
local POP_FONT   = UIFont.Medium

local PAD_X      = 10      -- side breathing room inside the box
local PAD_Y      = 6       -- vertical breathing room
local GAP_X      = 16      -- minimum space between label and counter
local GAP_Y      = 6       -- between the text line and the bar
local BAR_H      = 5
local MIN_W      = 148     -- below this the bar becomes an unreadable sliver

local BELOW_FEET = 46      -- distance from the character's feet to the box
local FADE_TICKS = 90      -- how long the box lingers after the fight
local POP_TICKS  = 70      -- lifetime of the "+1" that rises when the fix acts
local POP_RISE   = 34      -- how many pixels it rises in that time

local COLOR = {
    bg     = { r = 0.05, g = 0.07, b = 0.09 },
    border = { r = 0.30, g = 0.36, b = 0.41 },
    text   = { r = 0.93, g = 0.95, b = 0.96 },
    accent = { r = 0.89, g = 0.66, b = 0.29 },
    ok     = { r = 0.45, g = 0.78, b = 0.55 },
    danger = { r = 0.84, g = 0.35, b = 0.29 },
}

local state = {
    enabled = true,
    active  = false,   -- a bite is in progress
    fuse    = 0,       -- ticks left before the server gives up
    fuseMax = 1,
    rearms  = 0,
    label   = nil,
    tone    = COLOR.text,
    fade    = 0,       -- ticks of display left after the end
    pops    = {},      -- floating texts ("+1") rising
}

-- Measurements derived from the text; recomputed only when the content changes.
local box = { w = MIN_W, h = 40, headroom = 40, lineH = 12 }

local hud

local function counterText()
    if state.rearms <= 0 then return nil end
    return "saved " .. state.rearms .. "x"
end

local function measure()
    local tm = getTextManager()
    if tm == nil then return end

    local lineH = tm:getFontHeight(FONT)
    local labelW = state.label and tm:MeasureStringX(FONT, state.label) or 0

    local counter = counterText()
    local counterW = counter and tm:MeasureStringX(FONT, counter) or 0

    local w = PAD_X + labelW + PAD_X
    if counterW > 0 then w = w + GAP_X + counterW end

    box.lineH    = lineH
    box.w        = math.max(MIN_W, math.ceil(w))
    box.h        = PAD_Y + lineH + GAP_Y + BAR_H + PAD_Y
    -- Headroom above the box so the "+1" rises INSIDE the element: drawing at a
    -- negative coordinate would depend on the element not clipping.
    box.headroom = tm:getFontHeight(POP_FONT) + POP_RISE

    if hud then
        hud:setWidth(box.w)
        hud:setHeight(box.headroom + box.h)
    end
end

local function addPop(text, tone)
    table.insert(state.pops, { text = text, tone = tone, life = POP_TICKS })
end

local function setPhase(label, tone)
    state.label = label
    state.tone = tone or COLOR.text
    measure()          -- the label changed width
end

-- ---------------------------------------------------------------------------
-- Panel
-- ---------------------------------------------------------------------------

local HUD = ISUIElement:derive("FishingMPFixHUD")

function HUD:new()
    local o = ISUIElement:new(0, 0, box.w, box.headroom + box.h)
    setmetatable(o, self)
    self.__index = self
    return o
end

function HUD:shouldDraw()
    return state.enabled
        and (state.active or state.fade > 0 or #state.pops > 0)
end

-- Follows the character, the way the vanilla TensionUI does with its needle.
function HUD:prerender()
    if not self:shouldDraw() then return end

    local player = getPlayer()
    if player == nil then return end

    local idx = player:getPlayerNum()
    local ok, sx, sy = pcall(function()
        return isoToScreenX(idx, player:getX(), player:getY(), player:getZ()),
               isoToScreenY(idx, player:getX(), player:getY(), player:getZ())
    end)
    if not ok or sx == nil then return end

    -- Pinned to the screen: near the edge the box butts up instead of vanishing.
    local maxX = getCore():getScreenWidth() - box.w
    local maxY = getCore():getScreenHeight() - (box.headroom + box.h)
    local x = math.max(0, math.min(sx - box.w / 2, maxX))
    local y = math.max(0, math.min(sy + BELOW_FEET - box.headroom, maxY))
    self:setX(math.floor(x))
    self:setY(math.floor(y))
end

function HUD:render()
    if not self:shouldDraw() then return end

    -- Fades out over the last ticks instead of blinking away.
    local alpha = 1.0
    if not state.active then
        alpha = math.min(1.0, state.fade / (FADE_TICKS * 0.6))
    end

    local top = box.headroom

    if state.active or state.fade > 0 then
        self:drawRect(0, top, box.w, box.h, 0.72 * alpha,
                      COLOR.bg.r, COLOR.bg.g, COLOR.bg.b)
        self:drawRectBorder(0, top, box.w, box.h, 0.55 * alpha,
                            COLOR.border.r, COLOR.border.g, COLOR.border.b)

        local textY = top + PAD_Y
        local tone = state.tone
        self:drawText(state.label or "", PAD_X, textY,
                      tone.r, tone.g, tone.b, alpha, FONT)

        -- How many times the fix has already saved this bite. The box was
        -- measured to fit both texts, so there is no overlap risk here.
        local counter = counterText()
        if counter then
            self:drawTextRight(counter, box.w - PAD_X, textY,
                               COLOR.accent.r, COLOR.accent.g, COLOR.accent.b,
                               alpha, FONT)
        end

        -- Remaining-time bar.
        local by = textY + box.lineH + GAP_Y
        local bw = box.w - PAD_X * 2
        self:drawRect(PAD_X, by, bw, BAR_H, 0.35 * alpha, 1, 1, 1)

        local frac = 0
        if state.fuseMax > 0 then
            frac = math.max(0, math.min(1, state.fuse / state.fuseMax))
        end

        -- Green with room to spare, amber when it tightens, red at the end.
        local bar = COLOR.ok
        if frac < 0.25 then
            bar = COLOR.danger
        elseif frac < 0.6 then
            bar = COLOR.accent
        end

        if frac > 0 then
            self:drawRect(PAD_X, by, bw * frac, BAR_H, 0.95 * alpha,
                          bar.r, bar.g, bar.b)
        end
    end

    -- "+1" rising inside the headroom reserved above the box.
    for _, pop in ipairs(state.pops) do
        local t = pop.life / POP_TICKS               -- 1 -> 0
        local py = top - PAD_Y - (1 - t) * POP_RISE
        self:drawTextCentre(pop.text, box.w / 2, py,
                            pop.tone.r, pop.tone.g, pop.tone.b, t, POP_FONT)
    end
end

-- ---------------------------------------------------------------------------
-- State
-- ---------------------------------------------------------------------------

local function onServerCommand(module, command, args)
    if module ~= "FishingMPFix" or command ~= "hud" then return end

    state.rearms = args.rearms or 0

    if args.event == "hooked" then
        state.active = true
        state.fade = FADE_TICKS
        state.fuse = args.fuse or 0
        state.fuseMax = math.max(1, state.fuse)
        setPhase("Fish on the line", COLOR.text)

    elseif args.event == "rearmed" then
        state.active = true
        state.fade = FADE_TICKS
        state.fuse = args.fuse or 0
        state.fuseMax = math.max(state.fuseMax, state.fuse)
        setPhase("Bite held", COLOR.accent)
        addPop("+1", COLOR.accent)

    elseif args.event == "caught" then
        state.active = false
        state.fade = FADE_TICKS
        state.fuse = state.fuseMax
        setPhase("Catch confirmed", COLOR.ok)
        addPop("+", COLOR.ok)

    elseif args.event == "lost" then
        state.active = false
        state.fade = FADE_TICKS
        state.fuse = 0
        setPhase("Bite lost", COLOR.danger)
    end
end

-- The panel's lifetime cannot depend on the server's closing message. That
-- message ("caught" / "lost") is only sent when Bobber:update runs once more
-- with the fuse out - and when the player stops fishing the bobber is
-- DESTROYED, so update never runs again and the transition never happens.
-- Without a local check the box stays on "Bite held" forever, following a
-- player who no longer even has a rod in hand.
--
-- The client can answer this on its own: while fishing the player is in
-- FishingState. Vanilla leans on the same invariant - FishingManager:update
-- ends the session the moment that state changes (FishingManager.lua:65).
local function stillFishing()
    local player = getPlayer()
    if player == nil then return false end
    local ok, fishing = pcall(function()
        if FishingState == nil then return true end
        return player:getCurrentState() == FishingState.instance()
    end)
    -- If the question cannot be asked, keep showing: a stuck panel is a
    -- nuisance, hiding a live one hides the fix doing its job.
    if not ok then return true end
    return fishing
end

local function endFight()
    state.active = false
    state.fade   = 0
    state.fuse   = 0
    state.rearms = 0
    state.label  = nil
    state.pops   = {}
end

local function onTick()
    -- Runs on every game tick: bail out early when there is nothing on screen.
    if not state.active and state.fade <= 0 and #state.pops == 0 then return end

    -- Fishing ended without the server getting a chance to say so.
    if state.active and not stillFishing() then
        endFight()
        return
    end

    local step = getGameTime():getMultiplier()

    if state.active then
        state.fuse = math.max(0, state.fuse - step)
    elseif state.fade > 0 then
        state.fade = state.fade - step
    end

    for i = #state.pops, 1, -1 do
        state.pops[i].life = state.pops[i].life - step
        if state.pops[i].life <= 0 then table.remove(state.pops, i) end
    end
end

-- Resolved once at boot: querying the binding on every key press would be a
-- pcall per key, all day long.
local boundKey = DEFAULT_KEY

local function onKeyPressed(key)
    if key == boundKey then
        state.enabled = not state.enabled
        local player = getPlayer()
        if player then
            player:Say(state.enabled and "Bite indicator: on"
                                      or "Bite indicator: off")
        end
    end
end

local function onGameStart()
    -- The registration itself was already done by the game from the keyBinding
    -- table; here we only read the key the player actually has configured.
    pcall(function()
        boundKey = getCore():getKey(KEY_NAME) or DEFAULT_KEY
    end)

    hud = HUD:new()
    hud:initialise()
    hud:instantiate()
    -- The box sits glued to the character, which is exactly where fishing
    -- clicks happen: it must never swallow one.
    pcall(function() hud.javaObject:setConsumeMouseEvents(false) end)
    hud:addToUIManager()
    hud:setVisible(true)

    measure()   -- first measurement, with the TextManager already available

    Events.OnServerCommand.Add(onServerCommand)
    Events.OnTick.Add(onTick)
    Events.OnKeyPressed.Add(onKeyPressed)
end

Events.OnGameStart.Add(onGameStart)

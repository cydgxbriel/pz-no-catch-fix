--[[
    FishingMPFix - Fishing Panel (client)

    The panel you open by right-clicking water (PZAPI.UI.FishWindow) lists the
    fish you have already caught. In multiplayer that list does not stick, and
    the panel can flood the console with errors. Two vanilla defects (42.20):

    1. THE PANEL READS A KEY THE SERVER NEVER KEEPS
       The panel reads modData.fishing_catchedFish, which ISPickupFishAction
       writes only on the client (`if not isServer()`) and nothing transmits.
       In multiplayer the character is persisted from the SERVER's copy: every
       call to ServerPlayerDB.serverUpdateNetworkCharacter passes the server's
       IsoPlayer, and the client loads that copy back on reconnect
       (ClientPlayerDB.clientLoadNetworkPlayer). So the list empties every
       session.

       The history is not actually lost. When the fish reaches the inventory,
       the server itself records it under a different key,
       modData["fishing_CatchDone_" .. fullType] (ISPickupFishAction
       :PickupFishUpdate, `if not isClient()`), and that one IS saved and comes
       back with the character. Vanilla just never reads it.

       Fix: rebuild the panel's table from those server-side keys. No packet,
       nothing new written on the server, and old catches reappear too.

    2. THE PANEL CAN LOSE THE TABLE, AND NEVER REFRESHES ITS PLAYER
       Every fish row indexes player:getModData().fishing_catchedFish without a
       nil check (FishWindow.lua:44 and :63), and caches getPlayer() once, when
       the window is first built. The window is a singleton that closing only
       hides. So:
         - receiving the player's modData from the server runs
           KahluaTableImpl.load, which WIPES the table before loading
           (ObjectModDataPacket.parse); the field is gone and every row errors
           on every frame (the engine pcalls each update, hence a flood rather
           than a crash);
         - after dying and respawning, the panel keeps showing the dead
           character.

       Fix: wrap the update of the panel's "info" tab. AtomUI.update runs a
       node's Lua update BEFORE its children's, so on every frame the tab
       points each row at the current player and guarantees the table exists
       before any row reads it.

    Nothing here touches fishing itself, and nothing is sent over the network.
]]

if isServer() then return end

FishingMPFixPanel = FishingMPFixPanel or {}
local M = FishingMPFixPanel

local CATCH_PREFIX = "fishing_CatchDone_"

-- Makes sure the table the panel reads exists, and folds in the catches the
-- server recorded under its own keys. Returns the table (or nil, no player).
local function catalogOf(player)
    if player == nil then return nil end
    local modData = player:getModData()
    if modData == nil then return nil end
    if type(modData.fishing_catchedFish) ~= "table" then
        modData.fishing_catchedFish = {}
    end
    return modData.fishing_catchedFish
end

local function mergeServerCatches(player)
    local catalog = catalogOf(player)
    if catalog == nil then return nil end
    local modData = player:getModData()
    for key, value in pairs(modData) do
        if value == true and type(key) == "string"
            and string.sub(key, 1, #CATCH_PREFIX) == CATCH_PREFIX then
            local fullType = string.sub(key, #CATCH_PREFIX + 1)
            if fullType ~= "" then catalog[fullType] = true end
        end
    end
    return catalog
end
M.catalogOf = catalogOf
M.mergeServerCatches = mergeServerCatches

-- Walking the whole modData every frame would be wasteful; once a second is
-- plenty for a list that grows by one entry per catch.
local MERGE_EVERY = 60
local framesSinceMerge = MERGE_EVERY
local lastPlayer = nil

-- Runs before the fish rows on every frame (AtomUI.update: own Lua update
-- first, then the child nodes). Returns false when there is no player.
local function refreshRows(infoTab)
    local player = getPlayer()
    if player == nil then return false end

    framesSinceMerge = framesSinceMerge + 1
    local hadTable = type(player:getModData().fishing_catchedFish) == "table"
    if player ~= lastPlayer or not hadTable or framesSinceMerge >= MERGE_EVERY then
        mergeServerCatches(player)
        framesSinceMerge = 0
        lastPlayer = player
    end

    infoTab.player = player
    if infoTab.children ~= nil then
        for _, row in pairs(infoTab.children) do
            if type(row) == "table" and row.fishType ~= nil then
                row.player = player
            end
        end
    end
    return true
end
M.refreshRows = refreshRows

-- The window is built from this template the first time it opens
-- (ISWorldObjectContextMenu.openFishWindow), so wrapping the template is
-- enough. Returns false, and logs once, if a game update moved it.
function M.patchTemplate()
    local ok, info = pcall(function()
        return PZAPI.UI.FishWindow.children.body.children.tabPanel.children.info
    end)
    if not ok or type(info) ~= "table" or type(info.update) ~= "function" then
        print("[FishingMPFix] fishing panel layout not recognised; panel fix skipped")
        return false
    end
    if info.fishingMPFix_wrapped then return true end

    local originalUpdate = info.update
    info.update = function(self, ...)
        -- No player (death screen, loading): skip the frame instead of erroring.
        if not refreshRows(self) then return end
        return originalUpdate(self, ...)
    end
    info.fishingMPFix_wrapped = true
    return true
end

-- The rows also build themselves (init) from the same table, on the first
-- open; have it ready, history included, before that happens.
local function onGameStart()
    for i = 0, getNumActivePlayers() - 1 do
        mergeServerCatches(getSpecificPlayer(i))
    end
end
Events.OnGameStart.Add(onGameStart)

if not M.templatePatched then
    pcall(require, "PZAPI/ui/organisms/FishWindow")
    M.templatePatched = M.patchTemplate()
end

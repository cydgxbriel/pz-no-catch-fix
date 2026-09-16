--[[
    FishingMPFix - Build 42.20
    Fixes the "No Catch" bug in multiplayer fishing.

    ROOT CAUSE
    ----------
    When a fish bites, the server stores the fish on the bobber and lights a
    fuse:
    Bobber.lua:133  ->  self.nibbleTimer = 360

    The player starts reeling and the CLIENT sets the flag:
    FishingRod.lua:171  ->  self.bobber.catchFishStarted = true

    That flag travels back to the server through the OnFishingActionMPUpdate
    event, which resolves the bobber via
    Bobber.lua:265  ->  Fishing.ServerBobberManager[data.player:getOnlineID()]

    And data.player is where it breaks. Read out of the 42.20 bytecode:

        Action.set()                -> id = ++lastId, and lastId is a static
                                       byte inside EACH CLIENT's own process
        ActionManager.getPlayer(id) -> actions.stream()
                                          .filter(a -> a.id == id)
                                          .findFirst()
        FishingAction.getLuaTable() -> data.player = getPlayer(id)

    Every client counts from 1 on its own, so the second, third and fourth
    anglers all send id 1 for their first cast. The server keeps every action
    in ONE static queue and looks them up by that id alone, so getPlayer()
    always answers with whoever started fishing first. The catch flag of every
    other angler lands on that first player's bobber.

    Hence the shape players report: only the first person to start fishing can
    actually land anything. Their bobber collects everybody's flags, while all
    the others keep catchFishStarted = false until the fuse runs out and the
    server runs Bobber.lua:150-155:

        if self.nibbleTimer <= 0 and not self.catchFishStarted then
            if self.fish and not self.fish.isTrash then
                self.fishingRod:removeLure()   -- the bait unequips
            end
            self.fish = nil                    -- tension drops, "No Catch"
        end

    Result: bait gone, line worn, no XP, no fish. Both community workarounds
    shorten the reel for the same reason: cast closer, or stand 1-4 tiles back
    from the shore (the bobber hits dry land before it reaches the player and
    isPickupBobber(), FishingRod.lua:190, ends the reel right there - before
    the fuse burns out).

    THE FIX: A CHANNEL THAT CANNOT BE MISROUTED
    -------------------------------------------
    The id is built and consumed inside Java, so Lua cannot repair the routing
    of that packet. What it CAN do is not depend on it: the client half of this
    mod reports the reel through OnClientCommand, where the server resolves the
    sender from the CONNECTION the packet arrived on
    (GameServer.receiveClientCommand -> getPlayerFromConnection). No shared
    counter, nothing to collide with; the flag can only reach the sender's own
    bobber. See onCatchRelay below and client/FishingMPFix_Catch.lua.

    THE SAFETY NET: PATCH THE PUNISHMENT TOO
    ----------------------------------------
    A player whose client is on an older version of the mod, or whose one
    packet gets lost, would be back to losing the fish. So the second half
    stays: before letting the fuse punish, confirm that the player is still
    fishing and re-arm the fuse instead. Because that target is the punishment
    and not the sync, it holds regardless of why the flag never arrived.

    Which evidence it trusts depends on what the process can actually observe:
    the character state (FishingState) where that exists, the rod in hand where
    it does not. See calibrateStateSignal - inside a dedicated server nobody
    ever enters FishingState, and treating that as "stopped fishing" leaves the
    mod inert.

    The re-arm is finite (MAX_REARMS): a player who genuinely ignores the bite
    still loses the bait, preserving vanilla's intent.

    COMPATIBILITY AND REMOVAL
    -------------------------
    - Wraps Bobber:update instead of replacing it, so it chains with any other
      mod that does the same, in any load order.
    - If another mod REPLACES Bobber.update after us, applyPatch detects it and
      re-chains on top of the new version instead of vanishing silently.
    - Writes nothing persistent: no modData, no item changes, no sandbox vars,
      no files. All state lives on the bobber itself, which is destroyed on
      every cast. Uninstalling leaves no trace and does not affect saves.
]]

-- Floor for the re-arm. Mirrors vanilla's literal at Bobber.lua:133; the value
-- actually used is the larger of this and the fuse observed on the bite (see
-- update).
local REARM_TICKS = 360
local MAX_REARMS  = 20    -- ~2 min of slack; after that the punishment returns

-- Test-mode hooks. Inert in a normal distribution: the file that defines
-- FishingMPFixDebug does NOT ship with the mod (see dev/ in the repository).
local function debugFlag(name)
    return FishingMPFixDebug ~= nil and FishingMPFixDebug[name] == true
end

-- isClient() and isMultiplayer() do not change during a session, but update()
-- runs on every tick of every bobber. Resolve once, on the first call (at load
-- time they are not yet reliable).
local appliesHere = nil
local function applies()
    if appliesHere == nil then
        appliesHere = (not isClient()) and isMultiplayer() and true or false
    end
    return appliesHere
end

-- Answers whether the player is still fishing.
--   true / false -> reliable answer
--   nil          -> could not be evaluated (the caller decides)
local function queryFishingState(player)
    local ok, fishing = pcall(function()
        if FishingState == nil then return nil end
        return player:getCurrentState() == FishingState.instance()
    end)
    if not ok then return nil end
    return fishing
end

-- The character state only answers where it exists at all. What enters
-- FishingState is IsoPlayer.setFishingStage, and its StateManager.enterState
-- call sits behind an `if (GameClient.client)`; the other door is the
-- EventFishing animation event, reported from exactly one place:
-- client/Fishing/FishingStates.lua:55, which is client Lua. Inside a dedicated
-- server neither of those runs, so getCurrentState() NEVER returns FishingState
-- - not even for a player with a fish on the line.
--
-- Asking without calibrating turns "cannot tell from here" into "not fishing".
-- The mod announces the bite on the HUD and lets the fuse burn anyway: the
-- difference between fixing the bug and merely narrating the loss.
--
-- So we calibrate on the bite, the one moment when the right answer is known by
-- construction: the bobber is in the water and a fish has just taken the bait,
-- therefore the player IS fishing. If the state agrees, the signal can see in
-- this process and a later "no" means something. If it disagrees, the signal is
-- blind here and only the other evidence counts.
local stateSignalReported = false

local function calibrateStateSignal(bobber)
    local blind = queryFishingState(bobber.player) ~= true
    bobber.fishingMPFix_stateBlind = blind

    -- One line per process: without it the console cannot distinguish a server
    -- deciding case by case from one falling back on every bite.
    if not stateSignalReported then
        stateSignalReported = true
        print("[FishingMPFix] character state signal: "
              .. (blind
                  and "BLIND in this process (expected on a dedicated server); "
                      .. "the rod in hand becomes the evidence"
                  or "available"))
    end
end

local function isStillFishing(bobber)
    local player = bobber.player
    if player == nil then return false end

    -- 1) The character state, where it can see: that is the good answer.
    if not bobber.fishingMPFix_stateBlind then
        local fishing = queryFishingState(player)
        if fishing ~= nil then return fishing end
    end

    -- 2) Backup evidence, only for when the state does not answer. It cannot be
    -- used to override a negative from a signal that can see: FishingRod:new
    -- stores the item that was in hand, so "holding the rod" stays true for the
    -- whole life of the bobber and would say yes for anyone.
    local rod = bobber.fishingRod and bobber.fishingRod.rodItem
    if rod == nil then return false end
    local ok, holding = pcall(function()
        local inHand = player:getPrimaryHandItem()
        if inHand == nil then return false end
        -- Identity first, because that is what it is most of the time. But it
        -- cannot be the only test: Kahlua compares two Java objects by
        -- reference (BaseLib.luaEquals -> if_acmpne), and the server may hand
        -- back a different InventoryItem instance for the same rod after an
        -- inventory resync. Falling through on that would answer "stopped
        -- fishing" for someone with a fish on the line - the mod would go
        -- inert without a word. getID() survives the swap.
        if inHand == rod then return true end
        return inHand:getID() == rod:getID()
    end)
    return ok and holding or false
end

-- On a co-op host the host's own bobber gets the flag directly, without the
-- network: that one does not have the bug and must not be touched. When in
-- doubt, do not touch.
local function isLocallyTracked(player)
    -- In a solo test the only angler IS the host; without this there would be
    -- nothing to exercise.
    if debugFlag("INCLUDE_LOCAL") then return false end
    if player == nil then return true end
    local ok, isLocal = pcall(function() return player:isLocalPlayer() end)
    if not ok then return true end
    return isLocal and true or false
end

-- Tells the bobber's owner about the TRANSITIONS of the bite. The client counts
-- the time down on its own from the last value received, so there is no
-- per-tick network traffic.
local function notify(bobber, event)
    local player = bobber.player
    if player == nil then return end
    pcall(function()
        sendServerCommand(player, "FishingMPFix", "hud", {
            event  = event,
            fuse   = bobber.nibbleTimer or 0,
            rearms = bobber.fishingMPFix_rearms or 0,
        })
    end)
end

-- ---------------------------------------------------------------------------
-- The catch relay: the half that actually fixes the routing
-- ---------------------------------------------------------------------------

-- Announced once, so the console can tell a server where the clients carry the
-- mod from one where only the safety net is doing the work.
local relaySeen = false

local function onCatchRelay(module, command, player, args)
    if module ~= "FishingMPFix" or command ~= "catch" then return end
    if not applies() or player == nil then return end

    -- Unlike the vanilla path, `player` here came from the connection the
    -- packet arrived on, so this lookup resolves the sender's OWN bobber.
    local ok, bobber = pcall(function()
        return Fishing.ServerBobberManager
            and Fishing.ServerBobberManager[player:getOnlineID()]
    end)
    if not ok or bobber == nil then return end
    if bobber.catchFishStarted then return end

    bobber.catchFishStarted = true

    if not relaySeen then
        relaySeen = true
        print("[FishingMPFix] catch relay is live: clients are reporting the "
              .. "reel directly, the flag no longer depends on the action id")
    end
end

Events.OnClientCommand.Add(onCatchRelay)

-- We keep our own version so we can tell, later, whether it is still installed.
local ourUpdate = nil

local function applyPatch(source)
    if Fishing == nil or Fishing.Bobber == nil or Fishing.Bobber.update == nil then
        return false
    end

    if Fishing.Bobber.fishingMPFix_patched then
        if Fishing.Bobber.update == ourUpdate then
            return true
        end
        -- Another mod replaced Bobber.update outright instead of wrapping it.
        -- We re-chain on top of theirs: both end up running.
        print("[FishingMPFix] Bobber:update was replaced by another mod; "
              .. "re-chaining on top (" .. source .. ")")
        Fishing.Bobber.fishingMPFix_patched = nil
    end

    local originalUpdate = Fishing.Bobber.update

    function Fishing.Bobber:update()
        -- Hot path: runs on every tick of every bobber. Everything that does
        -- not change during a session is already resolved in applies().
        if applies() then
            -- Reproduces the MP defect with a single player: the flag vanishes
            -- as if it had landed on the wrong bobber.
            if debugFlag("SIMULATE_DESYNC") then
                self.catchFishStarted = false
            end

            -- The fuse is only burning with a fish on the line, no catch flag,
            -- and time left. Outside that there is nothing to postpone.
            local burning = self.fish ~= nil
                and not self.catchFishStarted
                and (self.nibbleTimer or 0) > 0

            local wasBurning = self.fishingMPFix_wasBurning
            if wasBurning == nil then
                -- First visit to this bobber. In Lua `false ~= nil` is true, so
                -- without this a freshly cast bobber would fire a phantom
                -- transition and the HUD would blink "Bite lost".
                self.fishingMPFix_wasBurning = burning
                if burning then calibrateStateSignal(self) end

            elseif burning ~= wasBurning then
                self.fishingMPFix_wasBurning = burning
                if burning then
                    calibrateStateSignal(self)
                    notify(self, "hooked")
                else
                    notify(self, self.catchFishStarted and "caught" or "lost")
                    -- End of the bite: clear here, once, instead of every tick.
                    -- This includes a successful catch, where vanilla pins
                    -- nibbleTimer at -1 but keeps the fish until pickup.
                    self.fishingMPFix_rearms = nil
                    self.fishingMPFix_fuse = nil
                end
            end

            -- Trash costs no bait in vanilla (Bobber.lua:151 checks isTrash).
            -- Re-arming would only pin the trash to the line, and while a fish
            -- is set Bobber.lua:128 blocks new bites.
            if burning and not self.fish.isTrash then
                -- Vanilla lights the fuse with a literal (360 today). Rather
                -- than trusting that number alone, we keep the largest value
                -- observed during this bite: if TIS raises the fuse, the re-arm
                -- follows. (A SMALLER value cannot be told apart from "we
                -- started watching mid-burn", so REARM_TICKS is the floor.)
                if (self.fishingMPFix_fuse or 0) < self.nibbleTimer then
                    self.fishingMPFix_fuse = self.nibbleTimer
                end

                -- The original update() is about to subtract this step and, if
                -- it reaches zero with catchFishStarted false, punish. We make
                -- the decision here, ahead of it. isLocallyTracked and
                -- isStillFishing only come in at this point: their result only
                -- changes anything on the expiry tick, and putting them in the
                -- condition above would cost a pcall per tick per bobber.
                local step = getGameTime():getMultiplier()
                if self.nibbleTimer - step <= 0
                    and not isLocallyTracked(self.player) then

                    -- The count only moves when a bite was actually saved.
                    -- Counting the attempt instead would put a denied one --
                    -- cap reached, or the player walked away -- into the
                    -- total, and the "Bite lost" that follows carries that
                    -- number to the HUD: "lost the fish, but saved 21x". It is
                    -- the number players read to judge whether the mod works.
                    local rearms = self.fishingMPFix_rearms or 0
                    if not debugFlag("DISABLE_FIX")
                        and rearms < MAX_REARMS and isStillFishing(self) then
                        self.fishingMPFix_rearms = rearms + 1
                        self.nibbleTimer =
                            math.max(REARM_TICKS, self.fishingMPFix_fuse or 0)
                        notify(self, "rearmed")
                    end
                end
            end
        end

        return originalUpdate(self)
    end

    -- The marker lives on the target table, not in a file-local: a /reloadlua
    -- re-executes this file and a local flag would go back to false, making the
    -- second patch wrap the ALREADY patched function and double the counting.
    ourUpdate = Fishing.Bobber.update
    Fishing.Bobber.fishingMPFix_patched = true
    print("[FishingMPFix] patch applied to Bobber:update (" .. source .. ")")
    return true
end

applyPatch("load")
Events.OnGameBoot.Add(function() applyPatch("OnGameBoot") end)
Events.OnServerStarted.Add(function()
    -- Last window after every mod has loaded: this is where a load-order
    -- conflict would show up.
    if not applyPatch("OnServerStarted") then
        -- Without this, a load-order failure becomes a silent no-op and there
        -- is no way to tell "working" from "inert" by reading the console.
        print("[FishingMPFix] ERROR: Fishing.Bobber not found. "
              .. "The mod is NOT active.")
    end
end)

--[[
    FishingMPFix - catch relay (client)

    Tells the server, over a channel that cannot be misrouted, that THIS player
    started reeling in.

    WHY A SECOND CHANNEL
    --------------------
    Vanilla already reports it, through the fishing action packet. The problem
    is how the server decides who sent it (42.20 bytecode):

        Action.set()                -> id = ++lastId, and lastId is a static
                                       byte inside EACH CLIENT's own process
        ActionManager.getPlayer(id) -> first action in the queue with that id
        FishingAction.getLuaTable() -> data.player = getPlayer(id)

    Every client counts from 1 on its own, so the second, third and fourth
    anglers all send id 1 for their first cast. On the server they share one
    static queue, and the lookup by id alone always answers with the FIRST
    action holding that id. So `data.player` is whoever started fishing first,
    no matter who actually reeled - and Bobber.onFishingActionMPUpdate writes
    catchFishStarted onto that person's bobber
    (Bobber.lua:265, ServerBobberManager[data.player:getOnlineID()]).

    That is why the bug reads as "only the first player to connect can fish":
    the first angler collects everyone's catch flags, and everybody else keeps
    catchFishStarted = false until the fuse runs out and the server throws the
    fish away.

    OnClientCommand does not use that id at all. The server resolves the sender
    from the CONNECTION the packet arrived on
    (GameServer.receiveClientCommand -> getPlayerFromConnection), so the flag
    can only ever land on the sender's own bobber.

    COST
    ----
    One packet per cast. The flag is latched on the bobber itself, which the
    game destroys on every cast, so there is nothing to reset by hand and
    nothing accumulates.
]]

if isServer() then return end

-- Only a real network client needs this. When the game hosts the server in
-- the same process there is a single Lua bobber: the vanilla write already
-- lands on the right one, and sendClientCommand would be a detour.
local function relayCatch()
    if not isClient() then return end

    local instances = Fishing and Fishing.ManagerInstances
    if instances == nil then return end

    -- ManagerInstances only ever holds this machine's own anglers
    -- (FishingHandler.lua:16 gates on player:isLocal()), so iterating it also
    -- covers split screen without asking anyone who they are.
    for _, manager in pairs(instances) do
        local rod = manager and manager.fishingRod
        local bobber = rod and rod.bobber
        if bobber ~= nil
            and bobber.catchFishStarted
            and not bobber.fishingMPFix_relayed then
            -- FishingRod:updateLineMoveCoeff (FishingRod.lua:171) is what sets
            -- the flag here, the moment reeling starts. We ride that instead
            -- of reading the mouse, so a rebind or a joypad changes nothing.
            bobber.fishingMPFix_relayed = true
            pcall(sendClientCommand, manager.player, "FishingMPFix", "catch",
                  {})
        end
    end
end

Events.OnTick.Add(relayCatch)

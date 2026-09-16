# No Catch Fix - MP Fishing [B42.20]

Fixes the **"No Catch"** bug in Build 42 multiplayer fishing: the bait
unequipping mid-fight and the `No Catch` that comes with it.

## The bug

When a fish bites, the server lights a 360-tick fuse (`Bobber.lua:133`). The
client sets `catchFishStarted = true` as soon as reeling starts
(`FishingRod.lua:171`), and that flag travels back to the server through the
`OnFishingActionMPUpdate` event, which resolves the bobber via
`Fishing.ServerBobberManager[data.player:getOnlineID()]` (`Bobber.lua:265`).

`data.player` is where it breaks, and the reason is an **id collision**. From
the 42.20 bytecode:

```java
// zombie.core.Action — runs on the CLIENT
void set(IsoPlayer p) { ...; this.id = lastId++; ... }   // lastId: static byte

// zombie.core.ActionManager — runs on the SERVER
static IsoPlayer getPlayer(byte id) {
    return actions.stream().filter(a -> a.id == id).findFirst()   // <-- first
                  .get().playerId.getPlayer();
}

// zombie.core.FishingAction
KahluaTable getLuaTable() { tbl.rawset("player", ActionManager.getPlayer(id)); }
```

Every claim about Java on this page can be checked against your own install —
the JRE the game ships is a runtime with no `javap`, so the repo carries a
disassembler:

```bash
.venv/bin/python tools/bytecode.py zombie.core.ActionManager getPlayer
.venv/bin/python tools/bytecode.py zombie.core.Action set
```

`lastId` is a static counter **inside each client's own process**. Every client
counts from 1 on its own, so the second, third and fourth anglers all send
id 1 for their first cast. The server keeps every action in one static queue and
looks them up by that id alone — so `getPlayer()` always answers with whoever
started fishing first, and *everyone's* catch flag lands on that one player's
bobber.

**That is why the bug reads as "only the first angler can fish".** Their bobber
collects everybody's flags and never gets punished; all the others keep
`catchFishStarted = false` until the fuse runs out and the server runs
`Bobber.lua:150-155`:

```lua
if self.nibbleTimer <= 0 and not self.catchFishStarted then
    if self.fish and not self.fish.isTrash then
        self.fishingRod:removeLure()   -- the bait unequips
    end
    self.fish = nil                    -- tension drops, "No Catch"
end
```

Bait gone, line worn, no XP, no fish. Standing a few tiles back from the shore
"works" because the bobber hits dry land before it reaches you, and
`isPickupBobber()` ends the reel right there — before the fuse burns out.

## The fix

The id is built and consumed inside Java, so Lua cannot repair the routing of
that packet. What it can do is **not depend on it**.

### 1. A channel that cannot be misrouted

The client half of the mod reports the reel a second time, through
`sendClientCommand`. That path never touches the action id: the server resolves
the sender from the **connection the packet arrived on**
(`GameServer.receiveClientCommand` → `getPlayerFromConnection`), so the flag can
only ever reach the sender's own bobber.

```lua
-- client: one packet per cast, latched on the bobber the game throws away anyway
if bobber.catchFishStarted and not bobber.fishingMPFix_relayed then
    bobber.fishingMPFix_relayed = true
    sendClientCommand(manager.player, "FishingMPFix", "catch", {})
end

-- server: this lookup is the right one, because `player` came from the socket
Fishing.ServerBobberManager[player:getOnlineID()].catchFishStarted = true
```

From there the fight is identical to single player: the fish stays on the line,
the bait stays on the rod, and the pickup already routes by player correctly
(`FishingAction.fishForPickUp` is keyed by `playerId.getPlayer()`).

### 2. A safety net, for when the flag still does not arrive

A client on an older version of the mod, or one lost packet, would be back to
losing the fish. So the original approach stays as a fallback: before letting
the fuse punish, the server confirms that the player is still fishing and
**re-arms** the fuse instead.

Because that target is the punishment and not the sync, it holds regardless of
why the flag never arrived — including reasons I have not found yet.

### What evidence proves the player is still fishing

The obvious route — `getCurrentState() == FishingState.instance()` — **does not
work inside a dedicated server**, and that is why the mod shipped inert for a
good share of the people who installed it. What enters `FishingState` is
`IsoPlayer.setFishingStage`, and its call sits behind an
`if (GameClient.client)`; the other door is the `EventFishing` animation event,
reported from exactly one place — `client/Fishing/FishingStates.lua:55`, which
is client Lua. Inside the server process neither of those runs, so the state is
never the fishing one **not even for a player with a fish on the line**.

Asking without calibrating turns *"cannot tell from here"* into *"not
fishing"*: the mod announces the bite on the HUD and lets the fuse burn anyway.

The fix is to calibrate **on the bite**, the one moment when the right answer is
known by construction: the bobber is in the water and a fish has just taken the
bait, so the player is fishing. If the state agrees, it can see in that process
and a later "no" means something. If it disagrees, the signal is blind there and
the evidence becomes the rod in hand — which goes away when the person actually
stops fishing.

That way the mod does not depend on my having read the game's internals
correctly: it measures, on every bite, whether the signal is usable.

"The rod in hand" is compared by `getID()`, not only by object identity. Kahlua
compares two Java objects by reference (`BaseLib.luaEquals` → `if_acmpne`), and
the server may hand back a different `InventoryItem` instance for the same rod
after an inventory resync. Falling through on that would answer *"stopped
fishing"* for someone with a fish on the line — and the safety net would go
inert without a word.

The re-arm is finite (20 times, ~2 min). A player who genuinely ignores the bite
still loses the bait — vanilla's intent is preserved. Single player and the
host's own bobber are untouched.

## Bite indicator

During the fight with a fish a small window appears **just below the character**
— following it around the screen, the way the tension needle does — showing the
time left before the server gives up on the bite. Every time the fix prevents
that, a **+1** floats up.

| Text | Meaning |
|---|---|
| `Fish on the line` | Hooked; the bar is the time left |
| `Bite held` + `saved Nx` | The fix stopped the server from discarding the fish |
| `Catch confirmed` | The catch flag arrived; it worked |
| `Bite lost` | Time ran out — the bait is gone, as in vanilla |

This exists because in vanilla both outcomes are **visually identical**: the
tension needle drops and "No catch" appears, with nothing separating "the fish
got away" from "the server threw the fish out".

The panel fades on its own when the fight ends. **F7** toggles it (rebindable
under Key Bindings).

**Nothing in the box has a fixed pixel size.** The width comes from
`MeasureStringX` and the height from `getFontHeight`, because the label changes
from phase to phase, the counter grows from `saved 1x` to `saved 20x`, and the
font height depends on the player's UI scale. With a fixed width, label and
counter overlap in the first tight case. Measuring runs when the text changes,
not every frame — and there are tests verifying that the two texts never
collide, that the box respects a minimum width, and that it does not run off
screen at the edge.

The server sends only the transitions — the countdown runs on the client, so
there is no per-tick network traffic.

## Installing on a server

Published on the Workshop: **Workshop ID `3795522820`**, **Mod ID
`FishingMPFix`**.

On hosting panels, fill in those two fields. Editing `servertest.ini` by hand,
**append without removing what is already there**:

```
WorkshopItems=...your current IDs...;3795522820
Mods=...your current mods...;FishingMPFix
```

⚠️ Writing `Mods=FishingMPFix` on its own **wipes every other mod** on the
server. Then just restart.

## How to test

The bug **does not show up with a single player**. The test needs:

- 2 players connected at the same time
- whoever tests must **not** be the first angler — that person's bobber is the
  one collecting everybody's catch flags, so fishing works for them either way
- cast far (~7 tiles) and stand **at the water's edge** — moving back from the
  shore shortens the reel and masks the bug

Expected with the mod: the tension holds to the end of the reel, the fish goes
into the inventory, Fishing XP rises and the bait stays on the rod — **for
every angler, not just the first one**.

The indicator (F7) tells the two halves apart. `Catch confirmed` means the
relay arrived and the catch went through normally. `Bite held` + `saved Nx`
means the relay did **not** arrive and the safety net is carrying that fight —
worth checking whether the clients really have the mod.

To confirm the mod loaded, look in `server-console.txt` for:

```
[FishingMPFix] patch applied to Bobber:update (...)
[FishingMPFix] catch relay is live: clients are reporting the reel directly...
[FishingMPFix] character state signal: ...
```

The **first** line is the mod loading. The **second** appears the first time a
client reports a reel: if it is there, the real fix is working and the flag no
longer depends on the action id. If it never appears while people are fishing,
the clients do not have the mod — only the safety net is holding, and everyone
past the first angler is being saved by the re-arm instead of catching normally.

The **third** appears on the first bite and says which evidence the safety net
is using on that server. `BLIND in this process` is what to expect on a
dedicated server — it means calibration worked and the rod in hand became the
criterion, not that something failed.

## Compatibility with other mods

The mod **wraps** `Bobber:update` instead of replacing it, so it chains with any
other mod that does the same, in any load order.

If another mod **replaces** `Bobber.update` outright after us, `applyPatch`
detects it in the next window (`OnGameBoot`, `OnServerStarted`) and re-chains on
top of the new version — both end up running, instead of ours vanishing
silently. There is a test covering that case.

Verified against **TwisTonFire - Better Fishing** (the most used fishing mod):
its `shared/BetterFishing.lua` does not touch `Bobber` or `update`, and its
StatusUI is pinned to the top of the screen (`y=80`) while ours follows the
character — no overlap.

The indicator calls `setConsumeMouseEvents(false)`: it sits glued to the
character, which is exactly where fishing clicks happen, and must never swallow
one.

Everything the mod adds at runtime is prefixed (`fishingMPFix_*`), and the
network channel uses the module `"FishingMPFix"` — no name collisions.

## Clean removal

**The mod writes nothing persistent.** No `modData`, no item changes, no sandbox
vars, no files on disk. All state lives on the bobber itself, which is destroyed
on every cast.

Consequence: uninstalling leaves no trace, does not break saves and needs no
wipe. The game simply returns to vanilla behaviour.

## Installing is still one field on the panel

The mod now has a client half, but **nothing changes for whoever runs the
server**. Both halves travel in the same Workshop item, and the game downloads
and enables a server's mods on every client that connects — there is no manual
install to hand out, no `-javaagent:`, no launch option, no startup change.

What the split does mean: a player still running an older version of the mod
falls back to the safety net and gets the re-arm instead of a clean catch. That
still keeps their bait and their fish, so a server that upgrades ahead of its
players is never worse off than before. The `catch relay is live` line in
`server-console.txt` is how you tell the two apart.

## Known risk

42.20.1 brought *"improved Lua checksum validation"*. If clients get kicked on
checksum, distribute the same folder to them under
`%USERPROFILE%\Zomboid\mods\` and enable the mod in the menu — still no
javaagent and no launch option, unlike the ZombieBuddy alternative.

## Test mode (reproducing the bug alone)

The bug only appears with 2+ players, which makes every attempt depend on
getting two people together. Test mode reproduces the same defect **solo**.

```bash
.venv/bin/python tools/debug_mode.py on
```

In game: **HOST** → co-op alone → admin panel → turn on **Fishing Cheat** (the
fish bites in ~1s). Fish and watch the indicator (F7).

The A/B that proves the fix — flip `DISABLE_FIX` in `dev/FishingMPFix_Debug.lua`
and run `on` again:

| `DISABLE_FIX` | What you see |
|---|---|
| `true` | **The bug**: bar empties, "Bite lost", bait gone |
| `false` | **The fix**: "Bite held · saved Nx", the bait stays |

```bash
.venv/bin/python tools/debug_mode.py off   # before publishing or playing
```

⚠️ Test mode **breaks fishing on purpose** and must never run on a real server.
That is why it lives outside the mod folder, and why `build_vdf.py` **refuses to
publish** while the file is present.

`INCLUDE_LOCAL` exists because in solo co-op the only angler is the host — and
the mod ignores the host's bobber on purpose, since it does not actually have
the bug. Without that flag, the solo test would exercise nothing.

## Workshop metrics

```bash
.venv/bin/python tools/workshop_stats.py          # collect and show the delta
.venv/bin/python tools/workshop_stats.py --show   # accumulated history only
```

The Steam API returns only a **snapshot** (`views`, `subscriptions`,
`favorited`) — the *Item Stats* tab shows a graph but does not export, and there
is no historical-series endpoint. The history is built here: each run appends a
row to `tools/workshop_stats.csv` and shows the gain since the previous
collection.

Run periodically (cron), that becomes the adoption curve Steam does not give
you.

**There is no in-game usage telemetry, and that is deliberate.** PZ's Lua API
has no HTTP call — only local file read and write — so knowing how many people
actually fish would require a javaagent, exactly what this mod avoids. On top of
that, a mod that sends data without saying so is a privacy violation and the
community reacts badly. The feedback channel is the comments on the page.

## What is still broken, and cannot be fixed from Lua

The same id collision has a second consequence this mod cannot reach.
`ActionManager.stop()` calls `remove(action.id, …)`, and on the server that
removes **every** action carrying that id — across players — calling `stop()`
on each, which destroys their bobbers:

```java
// zombie.core.ActionManager.remove(byte id, boolean) — server branch
List<Action> doomed = actions.stream().filter(a -> a.id == id).collect(toList());
actions.removeAll(doomed);
for (Action a : doomed) a.stop();     // FishingAction.stop() -> bobber:destroy()
```

So when one angler stops fishing, other anglers who share that id lose their
server-side fishing action as well. Re-equipping the rod restarts it. Fixing
this needs the id to be unique per player, which only TIS can do.

## Automated tests

The tests load the **real** `Bobber.lua` from the installed game and exercise
the fuse outside the engine — including tests that reproduce the bug in vanilla
code with two anglers and prove the relay lands the flag on the right bobber.

```bash
python -m venv .venv && .venv/bin/pip install lupa
.venv/bin/python tests/run_tests.py
```

The tests read `Bobber.lua` from
`/mnt/c/Program Files (x86)/Steam/steamapps/common/ProjectZomboid/`; adjust the
path in `tests/run_tests.py` if the installation lives elsewhere.

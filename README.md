# Clienter

Run `python Clienter.py`, select a trusted `.rbxl` or `.rbxlx`, click **Host this world**, then **Open Roblox**. Hosting starts Python automatically. Keep HTTP port **80**; the legacy trusted-content validator rejects our launch URLs on other ports.

The **Character** selector defaults to **Bacon Hair** with the **Man body bundle**, Pal Hair, classic motorcycle shirt, and jeans. **Noob** keeps the normal block body with yellow head/arms, a blue torso, green legs, and no hair/clothes. **BillyBloxxer** and **BettyBloxxer** wear Robloxian 2.0 bodies, the original guest jacket/jeans, and True Blue Hair or Lavender Updo respectively.

Select **Custom**, then click **Customize your avatar** to open the offline wardrobe: **100 hats, 100 classic shirts, and 100 classic pants**, with thumbnails, name/creator search, and a front-view outfit preview. Wear up to three hats, remove clothing with **None**, and color each body part separately or use the quick palette. Skin colors use the closest color in the legacy engine's BrickColor palette. Hat thumbnails indicate selected items; their actual fit is shown in-game.

The **Body bundles** tab offers ten R6 body shapes: **Blocky**, **Man**, **Robloxian 2.0**, **Woman**, **ROBLOX Boy**, **ROBLOX Girl (Classic)**, **ROBLOX Girl**, **Superhero**, **Cool Punk Kid**, and **Action Figure**. Blocky is the default. Body selection preserves your hats, shirt, pants, and skin colors, and persists with the saved outfit and through respawns. Bundle thumbnails show the source package; this selector applies its body meshes/textures only. The flat outfit preview does not render the 3D body shape; see the selected body in-game. Rebuild bundle assets with `python tools/setup_bundles.py` and test all choices with `python tools/verify_bundles.py`.

Click **Save outfit**, then **Apply character to game** (or host a map) to wear it. Outfits persist through respawns and are saved locally in `custom_avatar.json`. The launcher uses R6; the removed R6/R15 selector stays removed. No account login is needed. The cache includes 100 pre-2017 Roblox hats, 100 publicly downloadable Roblox shirts, and 41 Roblox pants plus 59 original Clienter pants designs. Original designs are labeled **Clienter Originals**; inaccessible catalog items are skipped. Rebuild with `python tools/setup_wardrobe.py`; verify with `python tools/verify_custom_avatar.py`. Item source links and file hashes are stored in `assets/wardrobe/catalog.json`. Catalog queries follow the [Roblox Marketplace API documentation](https://create.roblox.com/docs/projects/assets/api).

Preset guest hair/clothing use original asset versions. Assets and animations are cached for offline use. Rebuild guest assets with `python tools/setup_guests.py` and animations with `python tools/setup_animations.py`.

Missing assets requested through the local `/asset/?id=...` endpoint are downloaded automatically from Roblox's HTTPS asset delivery service. Bundled avatar/animation assets take priority. Successful public downloads are cached in `cache/roblox-assets` for offline reuse; requested versions have separate cache entries. This personal download cache is excluded from the distribution ZIP. Restricted assets still require Roblox authorization and are reported as unavailable; Clienter does not collect Roblox login cookies or bypass asset permissions. Newer asset formats may not be supported by the 2016 engine. Run `python tools/verify_asset_fetch.py --live` to check downloads, caching and the local route.

**Stop game** stops owned client/RCC processes and restores pre-host XML. **Stop all** also stops Python. **Restore XML** restores the first saved `AppSettings.xml.original` backups.

## Local play and tunnel multiplayer

For local play, select a map, click **Host this world**, then **Open Roblox**.

For friends in another country, the host clicks **Share game** after hosting. Clienter starts the bundled tunnel helper and checks the public route before displaying an invite link. Click **Copy** and send the complete link, including the `#` access code, to your friend. They open the same updated ZIP, choose their username/avatar, paste the link into **Join a friend**, and click **Join**. Guests do not need a map or RCC running. Both computers connect outward; no router access, UPnP, public home IP, VPN installation or separate tunnel installation is required. Normal access to Cloudflare's tunnel service must be available on the host network.

Only the multiplayer relay is published. Native game UDP packets are framed and carried through an authenticated persistent secure WebSocket, so an IPv4 guest can reach a host on another network through Cloudflare. Unlike the former HTTP polling relay, game traffic flows in both directions without waiting for an HTTP response per batch. The legacy player still talks to a loopback UDP bridge. Signing keys, RCC control calls and the asset/map HTTP server stay on each computer. Up to 15 guests have independent IDs, avatars and ticketed packet channels. **Wear this character** updates only your character. Anyone with the complete invite can join; share it privately. **Stop game**, **Stop all** or closing Clienter stops the owned helper and relay. Invite links change after the tunnel is restarted. Both players must use this updated ZIP (transport protocol 3).

The tunnel sends keepalive pings, reports its measured network round trip in Session notes, and reconnects interrupted streams. This removes avoidable polling/queueing delays; it cannot eliminate distance-related latency, congestion or TCP retransmission delays. In a controlled local comparison with 50 ms of delay in each direction and 120 packets sent at 200 packets/second, median packet latency was about 878 ms for the former polling algorithm versus 121 ms for the WebSocket transport; all 120 packets arrived in both runs. This is a simulated-network benchmark, not a measured Taiwan-to-France result. Reproduce with `python tools/benchmark_tunnel.py --delay-ms 50 --http-baseline` and `python tools/benchmark_tunnel.py --delay-ms 50`.

The official `cloudflared` Windows helper, its Apache-2.0 license and a SHA-256 manifest are bundled under `tools/tunnel`. It is verified before execution and is not installed as a service. To update it, run `python tools/setup_tunnel.py`. Cloudflare Quick Tunnels need no account but are a development service with no uptime guarantee, so connections can be interrupted and latency may be higher than direct UDP. See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). TLS certificate verification stays enabled; bundled CA roots and a Cloudflare DNS-over-HTTPS fallback handle missing roots and freshly created tunnel hostnames without changing system DNS settings.

`python tools/verify_tunnel.py` checks session authentication, isolated packet transport and cleanup. Add `--live` to exercise a real temporary public tunnel. `python tools/verify_tunnel_clients.py --live` checks two actual Roblox clients, independent avatars and stable gameplay through that public route; it cleans up its test clients and helper afterward.

## Launch fix

The crash dump revealed a failed numeric conversion of a missing `placeid` parameter. Launch URLs now include `?placeid=1`.

`legacy_support.py` creates separate `RobloxPlayerBeta_local_<revision>.exe` and `RCCService_local_<revision>.exe` copies. Revision names avoid overwriting an executable used by an older launcher window. Originals are preserved. The copies trust `localhost.` (a fixed-width ten-character legacy domain identifier) and a generated local RSA public key. Python signs JSON join data with the matching private key. Signature verification stays enabled. Keep `local-keys/` private and preserve it with these copies.

Cryptography is installed in `tools/python-deps`. The launcher extracts this Python installation's bundled Tcl/Tk archives into `tools/tk-runtime` and sets process-local library paths so the GUI opens.

Maps load from a temporary content-folder copy using `rbxasset://`. The copy is removed on stop; the original map is preserved.

## Compatible 2016 runtime

The launcher now uses `RobloxPlayer/RobloxPlayer` and `RobloxPlayer/RCCService`, both **0.271.1.32426**. The obsolete standalone 0.249 player folder was removed. The original top-level RCCService folder is retained; Clienter uses the matched RCCService inside RobloxPlayer. The original pair is not compatible; changing its version strings would not repair replication.

The matched pair uses `DebugLocalRccServerConnection` on both peers. This is the engine's local development mode and relaxes its normal client authentication/hash checks. RCC does not load the player's JSON settings, so its local executable copy initializes that flag with a patch restricted to the verified executable SHA-256 and original instruction bytes. Unknown RCC builds are refused. Signature verification of the join response remains enabled.

Keep this setup private for local testing. The Python server binds to loopback; RCC controls its own game and SOAP bindings. Do not expose those listeners publicly.

The launcher enables `FFlagNewColor3Functions`, required by the bundled VR/UI modules. Without it, `Color3.fromRGB` throws and prevents the topbar, menu, chat, and backpack modules from loading.

The Escape menu's Players tab is enabled with `FFlagUseUserListMenu`. The bundled SettingsHub's initial page reference is corrected to `PlayersPage`. Restart the hosted game and client after updating.

The local chat UI uses the local player metadata and v1 chat endpoints. The matched RCC build receives guarded URL/protocol patches so its native chat delivery handles messages and bubbles. The local endpoint normalizes text; it does not provide Roblox moderation. Both IPv4 and IPv6 loopback listeners serve `localhost`, avoiding Windows' approximately two-second IPv6 fallback delay. Run `python tools/verify_chat_http.py` to check chat responses, latency and listener cleanup. Restart Clienter and the hosted game after updating.

Classic R6 character animations are bundled under `assets/animations` as legacy XML. The local `/asset/?id=...` endpoint serves them without internet requests; animation URL and direct-loading flags are configured on both peers. Default Animate prefabs use local asset URLs, avoiding broken `www.localhost` requests. Original prefabs are saved beside them as `.rbxm.animation-original`. Your map and its custom animation scripts are not modified. To rebuild the public asset cache, run `python tools/setup_animations.py`; the included animation-only converter handles binary and gzip downloads.

`python verify_local.py --selected --animations` checks playing character tracks, client-side idle/walk/jump decoding, and absence of animation-load errors. The integration test confirmed decoded playing tracks with lengths of 1 second (idle), approximately 0.667 seconds (walk), and 0.625 seconds (jump).

Hosting checks for occupied UDP ports and selects a free nearby port. It waits for a per-job ready callback after map loading and network startup, then enables joining. Failed startup no longer sends the client to an older game server on the requested port. The actual selected port appears in the launcher log.

`python verify_local.py --selected --ui --occupied` exercises these fixes with the selected map and an intentionally occupied port. It saves `tools/client-verification.png`; the visual check showed the running map and menu/chat/backpack topbar icons.

`python verify_local.py --selected` tests the previously selected map, verifies the join signature, queries RCC for a connected player and spawned character, checks that the connection stays active, and rejects outdated-client or default-Players errors in new logs. It also checks cleanup and Tk GUI construction. Missing publicly accessible assets can be fetched from Roblox; online account avatars, marketplace services and persistence are not hosted.

If restoring the download on another machine, run `python tools/setup_compatible.py`. Download sources and original executable hashes are in `RobloxPlayer/manifest.json`. The launcher checks actual embedded version resources before starting either peer.

Run trusted maps only. RCC output is in `rccservice.log`; detailed engine logs are in `%LOCALAPPDATA%/Roblox/logs`. Close older launcher windows and restart `patcher.py` after an update, so the matching runtime is selected.

## References

Domain/key substitution follows [Roblox Auto Patcher](https://github.com/worships/roblox-auto-patcher) (Apache-2.0). Its source/license are retained in `tools/roblox-auto-patcher-trunk`. The signed JSON wrapper follows this [legacy join implementation](https://gist.github.com/kz0kz1/4bf8ae380ea03c90cf863503a69442fa).

## Distribution

Extract `Clienter.zip` completely, then open `Start Clienter.bat` or run `python Clienter.py`. The bundled Python extensions target 64-bit Python 3.15 on Windows. The ZIP includes both RCCService and RobloxPlayer, cached assets, dependencies, and Tcl/Tk resources. New local signing keys are generated on first launch.

The requested runtime rename preserves its internal layout:

```text
Clienter.py
RobloxPlayer/
  RobloxPlayer/RobloxPlayerBeta.exe
  RCCService/RCCService.exe
  manifest.json
RCCService/  (original server files)
assets/
tools/
```

The desktop UI follows the reference layout: full-width blue section bars, pale panels, white entries/logs and cyan, green and red actions over your background image. Player and World are on the left; Play together and Session notes are on the right. The layout in `launcher_view.py` scales from the 1185x1029 reference to smaller windows. Source Sans 3 and the Clienter logo are retained. Port settings open in a separate dialog. Rebuild the distribution with `python tools/build_bundle.py`.

Application dropdowns use the shared `ui_dropdown.Dropdown` control: a rounded white field, custom cyan selection/hover rows, a selected-item checkmark, keyboard arrows/Home/End/Enter, type-to-select and Escape/outside-click dismissal. The Character selector uses this control and keeps the Custom outfit actions connected. System file/color pickers retain their operating-system UI.

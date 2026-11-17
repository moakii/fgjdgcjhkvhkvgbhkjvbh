"""Clienter: local 2016 Roblox launcher. Run: python Clienter.py.

Uses workspace-local cryptography. Original executables are preserved.
Only run trusted maps: their scripts execute in the legacy game server.
"""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from xml.sax.saxutils import escape
import json
import os
import sys
import zipfile
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
import tkinter as tk
from legacy_support import DOMAIN, patch_executable, signed_join, executable_version, local_settings, local_animations, local_avatars
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from avatar_customization import AvatarEditor, Wardrobe, load_profile, validate_profile
from ui_fonts import UI_FONT, load_fonts, configure_fonts
from launcher_view import build as build_launcher_view, layout as layout_launcher_view
from roblox_assets import RobloxAssets, AssetError
from tunnel_multiplayer import Lobby, GameTunnel, PublicTunnel, HttpChannel, PROTOCOL, VERSION, parse_invite

ROOT = Path(__file__).resolve().parent
APPEARANCES = ('Bacon Hair', 'Noob', 'BillyBloxxer', 'BettyBloxxer', 'Custom')
HTTP = build_opener(ProxyHandler({}))


def setup_tk():
    # Some Python 3.15 builds ship Tcl/Tk libraries zipped but omit their paths.
    bundled = Path(sys.base_prefix) / 'tcl'
    libraries = ROOT / 'tools/tk-runtime'
    for pattern, folder, variable, init in [('libtcl*.zip', 'tcl_library', 'TCL_LIBRARY', 'init.tcl'),
                                           ('libtk*.zip', 'tk_library', 'TK_LIBRARY', 'tk.tcl')]:
        archives = sorted(bundled.glob(pattern))
        if archives and not os.environ.get(variable):
            target = libraries / folder
            if not (target / init).exists():
                with zipfile.ZipFile(archives[-1]) as archive:
                    archive.extractall(libraries)
            os.environ[variable] = str(target)


def patch_settings(path, base):
    tree = ET.parse(path)
    node = tree.getroot().find('BaseUrl')
    if node is None:
        raise ValueError(f'No BaseUrl in {path}')
    backup = path.with_suffix('.xml.original')
    if not backup.exists():
        shutil.copy2(path, backup)
    node.text = base
    temporary = path.with_suffix('.xml.tmp')
    tree.write(temporary, encoding='utf-8', xml_declaration=True)
    temporary.replace(path)


def soap(port, operation, body):
    envelope = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
                f'<soap:Body><{operation} xmlns="http://{DOMAIN}/">{body}'
                f'</{operation}></soap:Body></soap:Envelope>')
    request = Request(f'http://127.0.0.1:{port}/', envelope.encode(),
                      {'Content-Type': 'text/xml; charset=utf-8',
                       'SOAPAction': f'"http://{DOMAIN}/{operation}"'})
    try:
        with HTTP.open(request, timeout=45) as response:
            data = response.read()
    except HTTPError as error:
        raise RuntimeError(error.read().decode(errors='replace')[:3000]) from error
    document = ET.fromstring(data)
    for node in document.iter():
        if node.tag.split('}')[-1] == 'Fault':
            raise RuntimeError(' '.join(node.itertext()))
    return data


class Backend:
    def __init__(self, log):
        self.log = log
        self.http = None
        self.http_ipv6 = None
        self.rcc = None
        self.clients = []
        self.map = None
        self.job = None
        self.hosted = False
        self.config = None
        self.settings_before = {}
        self.map_copy = None
        self.game_ready = threading.Event()
        self.asset_fetcher = RobloxAssets(ROOT / 'cache/roblox-assets', log)
        self.join_sessions = {}
        self.lobby = None
        self.public_tunnel = None
        self.game_tunnels = []
        self.tunnel_lock = threading.RLock()
        self.remote_avatar = None
        compatible = ROOT / 'RobloxPlayer'
        self.runtime = compatible if (compatible / 'manifest.json').is_file() else ROOT

    def patch(self, folder):
        path = self.runtime / folder / 'AppSettings.xml'
        if path not in self.settings_before:
            self.settings_before[path] = path.read_bytes()
        patch_settings(path, self.base)

    def restore_settings(self):
        for path, original in list(self.settings_before.items()):
            path.write_bytes(original)
            del self.settings_before[path]
            self.log(f'Restored {path.parent.name}/AppSettings.xml to its pre-host settings.')

    def start_http(self, config):
        if self.http:
            if config['web'] != self.config['web']:
                raise ValueError('Stop the Python server before changing its HTTP port.')
            if self.hosted and config != self.config:
                raise ValueError('Stop the game before changing its settings.')
            if not self.hosted:
                self.config = dict(config)
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            disable_nagle_algorithm = True

            def do_POST(self):
                path = urlsplit(self.path).path.lower()
                length = int(self.headers.get('Content-Length', '0'))
                limit = 16384 if path == '/game/chatfilter.ashx' else 32 * 1024 * 1024
                if length < 0 or length > limit:
                    self.send_error(413)
                    return
                body = self.rfile.read(length)
                if path == '/game/chatfilter.ashx':
                    try:
                        text_body = body.decode('utf-8')
                        if 'json' in self.headers.get('Content-Type', '').lower() or text_body.lstrip().startswith('{'):
                            values = json.loads(text_body)
                        else:
                            values = {key: value[0] for key, value in parse_qs(text_body, keep_blank_values=True).items()}
                        values = {key.lower(): value for key, value in values.items()}
                        message = next((values[key] for key in ('text', 'message', 'chat') if key in values), None)
                        if not isinstance(message, str): raise ValueError('Chat message is missing.')
                        message = ''.join(' ' if char in '\r\n\t' else char for char in message
                                          if char.isprintable() or char in '\r\n\t').strip()[:200]
                        data = json.dumps({'success': True, 'data': {'white': message, 'black': message}}).encode()
                    except (ValueError, TypeError, AttributeError, UnicodeError):
                        self.send_error(400, 'Invalid chat request')
                        return
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if path in ('/game/machineconfiguration.ashx', '/error/dmp.ashx', '/error/grid.ashx'):
                    self.send_response(200)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                else:
                    self.send_error(404)

            def do_GET(self):
                route = urlsplit(self.path)
                path = route.path.lower().rstrip('/')
                kind = 'text/plain; charset=utf-8'
                if path == '/health':
                    data = b'ok'
                elif re.fullmatch(r'/game/players/[0-9]+', path):
                    # Native player metadata is required before chat can be
                    # delivered to a different player's chat window/bubbles.
                    data = json.dumps({'ChatFilter': 'blacklist'}).encode()
                    kind = 'application/json'
                elif path == '/game/ready':
                    if parse_qs(route.query).get('jobid') != [owner.job]:
                        self.send_error(403)
                        return
                    owner.game_ready.set()
                    data = b'ok'
                elif path == '/map.rbxl' or (path == '/asset' and
                        parse_qs(route.query).get('id') == ['1']):
                    if owner.map is None:
                        self.send_error(404, 'Select a map and host first')
                        return
                    data = owner.map.read_bytes()
                    kind = 'application/octet-stream'
                elif path in ('/asset', '/v1/asset'):
                    asset = parse_qs(route.query).get('id', [''])[0]
                    if not re.fullmatch(r'[0-9]{1,20}', asset):
                        self.send_error(400, 'Invalid asset ID')
                        return
                    cached = ROOT / 'assets/animations' / f'{asset}.rbxm'
                    if not cached.is_file():
                        for name, metadata in owner.avatar_assets.items():
                            if metadata.get('asset_id') == asset:
                                cached = ROOT / 'assets/avatars' / name
                                break
                    if not cached.is_file():
                        try:
                            data = owner.asset_fetcher.fetch(asset, parse_qs(route.query).get('version', [None])[0])
                        except AssetError as error:
                            self.send_error(error.status, str(error))
                            return
                    else:
                        data = cached.read_bytes()
                    kind = 'application/octet-stream'
                elif path in ('/join.ashx', '/game/join.ashx'):
                    token = parse_qs(route.query).get('session', [''])[0]
                    connection = owner.join_sessions.get(token) if token else None
                    if (token and connection is None) or (not token and not owner.hosted):
                        self.send_error(503, 'Game is not hosted')
                        return
                    data = owner.join_script(connection).encode()
                elif path == '/game/placelauncher.ashx':
                    data = json.dumps({'jobId': owner.job or '', 'status': 2 if owner.hosted else 1,
                                       'joinScriptUrl': owner.base + '/Game/Join.ashx?placeid=1',
                                       'authenticationUrl': owner.base + '/Login/Negotiate.ashx',
                                       'authenticationTicket': ''}).encode()
                    kind = 'application/json'
                elif path == '/login/negotiate.ashx':
                    data = b''
                elif path in ('/game/loadplaceinfo.ashx', '/game/placespecificscript.ashx'):
                    data = b'-- local place\n'
                elif path == '/':
                    data = b'2016 local backend. /health /map.rbxl /join.ashx'
                else:
                    self.send_error(404, 'Endpoint or asset not available locally')
                    return
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt, *args):
                owner.log('HTTP ' + fmt % args)

        server = ThreadingHTTPServer(('127.0.0.1', config['web']), Handler)
        server.daemon_threads = True
        # Windows resolves localhost to ::1 first. Serving only IPv4 makes
        # every native chat request wait for that connection attempt to fail.
        class IPv6LoopbackServer(ThreadingHTTPServer):
            address_family = socket.AF_INET6

            def server_bind(self):
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                super().server_bind()

        ipv6 = None
        try:
            if socket.has_ipv6:
                ipv6 = IPv6LoopbackServer(('::1', server.server_port), Handler)
                ipv6.daemon_threads = True
        except OSError as error:
            if error.errno not in (socket.EAFNOSUPPORT, socket.EADDRNOTAVAIL) and error.winerror not in (10047, 10049):
                server.server_close()
                raise RuntimeError('Cannot bind the IPv6 localhost backend port; stop the process using it.') from error
        self.http = server
        self.http_ipv6 = ipv6
        self.avatar_assets = json.loads((ROOT / 'assets/avatars/manifest.json').read_text())
        self.config = dict(config)
        self.base = f"http://{DOMAIN}" + (f":{config['web']}" if config['web'] != 80 else '')
        threading.Thread(target=server.serve_forever, daemon=True).start()
        if ipv6:
            threading.Thread(target=ipv6.serve_forever, daemon=True).start()
        self.log(f'Python server listening at {self.base}')

    def host(self, config, map_path):
        config = dict(config)
        config.setdefault('rig', 'Bacon Hair')
        config.setdefault('rig_type', 'R6')
        if config['rig'] not in APPEARANCES or config['rig_type'] not in ('R6', 'R15'):
            raise ValueError('Select a supported appearance and R6 or R15.')
        custom_payload = None
        if config['rig'] == 'Custom':
            config['rig_type'] = 'R6'
            config['custom_avatar'] = validate_profile(config.get('custom_avatar', load_profile()))
            wardrobe = Wardrobe()
            custom_payload = wardrobe.payload(config['custom_avatar'])
        if config['web'] != 80:
            raise ValueError('This legacy client requires standard HTTP port 80 for its trusted join URL.')
        if self.rcc and self.rcc.poll() is None:
            raise ValueError('Stop the current game before hosting another map.')
        selected = Path(map_path).resolve()
        if not selected.is_file() or selected.suffix.lower() not in ('.rbxl', '.rbxlx'):
            raise ValueError('Select an existing .rbxl or .rbxlx map first.')
        exe = self.runtime / 'RCCService/RCCService.exe'
        if not exe.is_file():
            raise FileNotFoundError(exe)
        player_version = executable_version(self.runtime / 'RobloxPlayer/RobloxPlayerBeta.exe')
        rcc_version = executable_version(exe)
        if player_version[:3] != rcc_version[:3]:
            raise RuntimeError(f'Player {player_version} and RCCService {rcc_version} use different versions. '
                               'Install the matched runtime using tools/setup_compatible.py.')
        local_settings(self.runtime / 'RobloxPlayer')
        local_settings(self.runtime / 'RCCService')
        local_animations(self.runtime)
        local_avatars(self.runtime)
        if custom_payload is not None: wardrobe.install(self.runtime)
        exe = patch_executable(exe)
        patch_executable(self.runtime / 'RobloxPlayer/RobloxPlayerBeta.exe')
        requested_port = config['game']
        chosen_port = None
        for candidate in range(requested_port, min(requested_port + 100, 65536)):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    probe.bind(('0.0.0.0', candidate))
                chosen_port = candidate
                break
            except OSError:
                continue
        if chosen_port is None:
            raise ValueError('No free game port found. Stop older game servers or choose another port.')
        self.log(f'Using runtime: {self.runtime}')
        # Refuse to accidentally send a job to a different running RCC instance.
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', config['soap'])) == 0:
                raise ValueError('SOAP port is already occupied. Choose a different port.')
        self.start_http(config)
        self.config['game'] = chosen_port
        if chosen_port != requested_port:
            self.log(f'Game port {requested_port} is occupied; using {chosen_port}.')
        self.job = str(uuid.uuid4())
        self.game_ready.clear()
        self.map = selected
        output = open(ROOT / 'rccservice.log', 'ab', buffering=0)
        try:
            self.patch('RCCService')
            self.rcc = subprocess.Popen([str(exe), '-console', str(config['soap'])],
                                        cwd=exe.parent, stdout=output, stderr=subprocess.STDOUT,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except Exception:
            self.restore_settings()
            raise
        finally:
            output.close()
        try:
            self.log(f'RCCService PID {self.rcc.pid}; waiting for SOAP...')
            deadline = time.monotonic() + 30
            while True:
                if self.rcc.poll() is not None:
                    raise RuntimeError('RCCService exited. See rccservice.log.')
                try:
                    with socket.create_connection(('127.0.0.1', config['soap']), timeout=.3):
                        break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError('RCCService SOAP startup timed out. See rccservice.log.')
                    time.sleep(.2)
            # Client settings are changed after RCC starts, as requested.
            self.patch('RobloxPlayer')
            script = (self.runtime / 'RCCService/gameserver.txt').read_text(encoding='utf-8-sig')
            old = "game:Load('rbxasset://temp.rbxl')"
            if old not in script:
                raise ValueError('gameserver.txt has an unrecognized map-loading command.')
            # RCC's URL trust rules can reject HTTP localhost even for its own map.
            # Use its supported content-folder asset path instead.
            self.map_copy = self.runtime / 'RCCService/content' / (f'local-map-{uuid.uuid4().hex}' + selected.suffix.lower())
            shutil.copy2(selected, self.map_copy)
            script = script.replace(old, f'game:Load("rbxasset://{self.map_copy.name}")')
            script = script.replace('player:LoadCharacter()', '''player.CharacterAdded:connect(function(character)
    spawn(function()
        wait(0.2)
        if player.Character == character then _G.PrepareLocalCharacter(player, character) end
    end)
end)
player:LoadCharacter()''')
            appearance = (ROOT / 'assets/avatars/man-body.lua').read_text(encoding='utf-8')
            appearance += '\n' + (ROOT / 'assets/avatars/robloxian2-body.lua').read_text(encoding='utf-8')
            appearance += '\n' + (ROOT / 'avatar_rigs.lua').read_text(encoding='utf-8')
            script = (appearance + '\n_G.LocalRig = ' + json.dumps(config['rig'])
                      + '\n_G.LocalRigType = ' + json.dumps(config['rig_type']) + '\n' + script)
            if custom_payload is not None:
                script = '_G.LocalCustomAvatar = game:GetService("HttpService"):JSONDecode(' + json.dumps(json.dumps(custom_payload)) + ')\n' + script
            script += f'\nstart(1, {chosen_port}, "{self.base}")\n'
            script += f'game:HttpGet("{self.base}/Game/Ready?jobid={self.job}", true)\n'
            body = (f'<job><id>{self.job}</id><expirationInSeconds>86400</expirationInSeconds>'
                    '<category>0</category><cores>1</cores></job>'
                    f'<script><name>LocalGame</name><script>{escape(script)}</script></script>')
            result = soap(config['soap'], 'OpenJobEx', body)
            self.log('SOAP ' + result.decode(errors='replace')[:1500])
            if not self.game_ready.wait(timeout=15):
                raise RuntimeError('RCC did not confirm successful map/server startup. See engine logs; client launch cancelled.')
            self.hosted = True
            self.log(f'Game ready on UDP {chosen_port}; client launch is available.')
        except Exception:
            self.stop_game()
            raise

    def join_script(self, connection=None):
        c = self.config
        connection = connection or dict(port=c['game'], username=c['username'], user_id=1, job=self.job)
        data = dict(ClientPort=0, MachineAddress='127.0.0.1', ServerPort=connection['port'],
                    PingUrl='', PingInterval=20, UserName=connection['username'], UserId=connection['user_id'],
                    SeleniumTestMode=False, SuperSafeChat=False, CharacterAppearance='',
                    ClientTicket='', GameId=connection['job'], PlaceId=1, MeasurementUrl='',
                    WaitingForCharacterGuid=str(uuid.uuid4()), BaseUrl=self.base + '/',
                    ChatStyle='ClassicAndBubble', VendorId=0, ScreenShotInfo='', VideoInfo='',
                    CreatorId=1, CreatorTypeEnum='User', MembershipType='None', AccountAge=3650,
                    CookieStoreFirstTimePlayKey='rbx_evt_ftp', CookieStoreFiveMinutePlayKey='rbx_evt_fmp',
                    CookieStoreEnabled=False, IsRobloxPlace=False, GenerateTeleportJoin=False,
                    IsUnknownOrUnder13=False, SessionId='', DataCenterId=0, UniverseId=1,
                    BrowserTrackerId=0, UsePortraitMode=False, FollowUserId=0,
                    CharacterAppearanceId=connection['user_id'])
        return signed_join(json.dumps(data, separators=(',', ':')))

    def join(self):
        if not self.hosted or not self.rcc or self.rcc.poll() is not None:
            raise ValueError('Host a game successfully before launching the client.')
        if any(client.poll() is None for client in self.clients):
            raise ValueError('Roblox is already open. Close the current client before launching again.')
        self.launch_client(dict(port=self.config['game'], username=self.config['username'], user_id=1, job=self.job))

    def share_game(self):
        if not self.hosted or not self.rcc or self.rcc.poll() is not None:
            raise ValueError('Host a map first, then click Share game.')
        if self.public_tunnel and self.public_tunnel.url and self.public_tunnel.process.poll() is None:
            self.log('Invite link: ' + self.public_tunnel.url)
            return
        if not self.lobby:
            self.lobby = Lobby(self.config['game'], self.job, self.config['username'], self.set_player_avatar, self.log)
        if self.public_tunnel: self.public_tunnel.close()
        self.public_tunnel = PublicTunnel(self.lobby, self.log)
        self.log('Starting the public tunnel...')
        try:
            invite = self.public_tunnel.start()
        except Exception:
            self.public_tunnel.close()
            self.public_tunnel = None
            raise
        self.log('Invite link: ' + invite)

    @staticmethod
    def avatar_request(config):
        rig = config.get('rig', 'Bacon Hair')
        if rig not in APPEARANCES: raise ValueError('Select a supported character.')
        avatar = {'rig': rig}
        if rig == 'Custom': avatar['custom_avatar'] = validate_profile(config.get('custom_avatar', load_profile()))
        return avatar

    def set_player_avatar(self, user_id, avatar):
        if not self.hosted or not self.rcc or self.rcc.poll() is not None:
            raise ValueError('The host game has stopped.')
        if not isinstance(avatar, dict): raise ValueError('Invalid avatar.')
        if avatar.get('rig') == 'Custom' and 'custom_avatar' not in avatar:
            raise ValueError('Custom outfit is missing.')
        request = self.avatar_request(avatar)
        profile = {'rig': request['rig'], 'rig_type': 'R6'}
        if request['rig'] == 'Custom':
            wardrobe = Wardrobe()
            profile['custom'] = wardrobe.payload(request['custom_avatar'])
            wardrobe.install(self.runtime)
        source = '_G.SetLocalPlayerProfile(' + str(int(user_id)) + ', game:GetService("HttpService"):JSONDecode(' + json.dumps(json.dumps(profile)) + '))'
        soap(self.config['soap'], 'ExecuteEx', f'<jobID>{self.job}</jobID><script><name>PlayerAvatar</name><script>{escape(source)}</script></script>')

    def join_multiplayer(self, invite, config):
        parse_invite(invite)
        if any(client.poll() is None for client in self.clients):
            raise ValueError('Close the current Roblox client before joining another game.')
        channel = HttpChannel(invite)
        tunnel, ticket = None, None
        try:
            description = channel.json('GET', 'session')
            if description.get('protocol') != PROTOCOL or description.get('version') != VERSION:
                raise ValueError('Use the same updated ZIP as the host.')
            if executable_version(self.runtime / 'RobloxPlayer/RobloxPlayerBeta.exe') != tuple(VERSION):
                raise ValueError('Install the matching player from the updated ZIP.')
            if config['web'] != 80: raise ValueError('Keep the local HTTP port at 80.')
            avatar = self.avatar_request(config)
            local_settings(self.runtime / 'RobloxPlayer')
            local_animations(self.runtime)
            local_avatars(self.runtime)
            if avatar['rig'] == 'Custom': Wardrobe().install(self.runtime)
            if not self.http: self.start_http(config)
            registration = channel.json('POST', 'join', {'protocol': PROTOCOL, 'version': VERSION,
                                        'username': config['username'], 'avatar': avatar})
            ticket = registration.get('ticket')
            user_id = registration.get('user_id')
            name = registration.get('username')
            if (registration.get('protocol') != PROTOCOL or registration.get('version') != VERSION
                    or type(user_id) is not int or not 2 <= user_id < 2**31
                    or not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9_]{1,20}', name)
                    or not isinstance(ticket, str) or not re.fullmatch('[a-f0-9]{64}', ticket)):
                raise ValueError('Host sent invalid session details.')
            job = str(uuid.UUID(registration['job']))
            tunnel = GameTunnel(invite, ticket, self.log)
            self.game_tunnels.append((invite, ticket, tunnel))
            process = self.launch_client(dict(port=tunnel.port, username=name, user_id=user_id, job=job))
            self.remote_avatar = (invite, ticket)
            def cleanup():
                process.wait()
                self.release_tunnel(invite, ticket, tunnel)
            threading.Thread(target=cleanup, daemon=True).start()
            self.log(f'Joined multiplayer as {name} through the HTTPS tunnel.')
        except Exception:
            if tunnel: self.release_tunnel(invite, ticket, tunnel)
            elif ticket:
                try: channel.json('POST', 'leave', {}, ticket)
                except Exception: pass
            raise
        finally: channel.close()

    def release_tunnel(self, invite, ticket, tunnel):
        with self.tunnel_lock:
            entry = (invite, ticket, tunnel)
            if entry not in self.game_tunnels: return
            self.game_tunnels.remove(entry)
        tunnel.close()
        if self.remote_avatar == (invite, ticket): self.remote_avatar = None
        channel = HttpChannel(invite)
        try: channel.json('POST', 'leave', {}, ticket)
        except Exception: pass
        finally: channel.close()

    def launch_client(self, connection):
        exe = patch_executable(self.runtime / 'RobloxPlayer/RobloxPlayerBeta.exe')
        token = uuid.uuid4().hex
        self.join_sessions[token] = dict(connection)
        self.patch('RobloxPlayer')
        try:
            process = subprocess.Popen([str(exe), '--play', '-a', self.base + '/Login/Negotiate.ashx',
                                        '-j', self.base + '/Game/Join.ashx?placeid=1&session=' + token, '-t', 'local'], cwd=exe.parent)
        except Exception:
            self.join_sessions.pop(token, None)
            raise
        self.clients.append(process)
        self.log(f'Patched client started, PID {process.pid}; serving signed join data.')
        def watch():
            code = process.wait()
            self.join_sessions.pop(token, None)
            self.log(f'Client PID {process.pid} exited with code {code}.')
        threading.Thread(target=watch, daemon=True).start()
        return process


    def set_rig(self, rig, rig_type=None, custom_avatar=None):
        if self.remote_avatar:
            invite, ticket = self.remote_avatar
            avatar = self.avatar_request({'rig': rig, 'custom_avatar': custom_avatar or load_profile()})
            channel = HttpChannel(invite)
            try: channel.json('POST', 'avatar', avatar, ticket)
            finally: channel.close()
            self.log(f'Applied {rig} to your multiplayer character.')
            return
        rig_type = rig_type or (self.config or {}).get('rig_type', 'R6')
        if rig not in APPEARANCES or rig_type not in ('R6', 'R15'):
            raise ValueError('Select a supported appearance and R6 or R15.')
        if not self.hosted or not self.rcc or self.rcc.poll() is not None:
            raise ValueError('Select a rig before hosting, or host a game before applying it live.')
        source = '_G.SetLocalRig(' + json.dumps(rig) + ', ' + json.dumps(rig_type) + ')'
        if rig == 'Custom':
            rig_type = 'R6'
            profile = validate_profile(custom_avatar if custom_avatar is not None else load_profile())
            wardrobe = Wardrobe()
            payload = wardrobe.payload(profile)
            wardrobe.install(self.runtime)
            source = ('_G.LocalCustomAvatar = game:GetService("HttpService"):JSONDecode('
                      + json.dumps(json.dumps(payload)) + ')\n_G.SetLocalRig("Custom", "R6")')
        soap(self.config['soap'], 'ExecuteEx', f'<jobID>{self.job}</jobID><script>'
             f'<name>SetLocalRig</name><script>{escape(source)}</script></script>')
        self.config['rig'] = rig
        self.config['rig_type'] = rig_type
        if rig == 'Custom': self.config['custom_avatar'] = profile
        self.log(f'Applied {rig} / {rig_type}; rig changes respawn the character.')

    def stop_game(self):
        self.hosted = False
        if self.public_tunnel:
            self.public_tunnel.close()
            self.public_tunnel = None
        if self.lobby:
            self.lobby.close()
            self.lobby = None
        for invite, ticket, tunnel in list(self.game_tunnels):
            self.release_tunnel(invite, ticket, tunnel)
        for process in self.clients:
            self.terminate(process)
        self.clients.clear()
        self.join_sessions.clear()
        if self.rcc:
            self.terminate(self.rcc)
            self.rcc = None
        self.job = None
        if self.map_copy:
            self.map_copy.unlink(missing_ok=True)
            self.map_copy = None
        self.restore_settings()
        self.log('Owned game and client processes stopped.')

    @staticmethod
    def terminate(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def stop(self):
        self.stop_game()
        if self.http_ipv6:
            self.http_ipv6.shutdown()
            self.http_ipv6.server_close()
            self.http_ipv6 = None
        if self.http:
            self.http.shutdown()
            self.http.server_close()
            self.http = None
        self.config = None
        self.log('Python server stopped.')


class Launcher(tk.Tk):
    def __init__(self):
        setup_tk()
        load_fonts()
        if os.name == 'nt':
            import ctypes
            # Give the launcher its own taskbar group instead of Python's icon.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Clienter.Launcher.2016')
        super().__init__()
        configure_fonts(self)
        from PIL import Image, ImageTk
        with Image.open(ROOT / 'logos/clienter_applogo.png') as source:
            icon = source.convert('RGBA')
        self.app_icons = [ImageTk.PhotoImage(icon.resize((size, size), Image.Resampling.LANCZOS), master=self)
                          for size in (16, 32, 48, 128, 256)]
        self.iconphoto(True, *self.app_icons)
        self.title('Clienter | 2016')
        self.geometry('1120x830')
        self.minsize(980, 800)
        self.configure(bg='#0b1120')
        self.events = queue.Queue()
        self.backend = Backend(self.events.put) 
        self.busy = False
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=(UI_FONT, 10), background='#eef3fb', foreground='#23334d')
        style.configure('TFrame', background='#eef3fb')
        style.configure('Card.TFrame', background='#eef3fb')
        style.configure('TLabel', background='#eef3fb', foreground='#23334d')
        style.configure('Muted.TLabel', foreground='#65758c', font=(UI_FONT, 9))
        style.configure('Title.TLabel', background='#0b1120', font=(UI_FONT, 30, 'bold'))
        style.configure('Subtitle.TLabel', background='#0b1120', foreground='#94a6c5')
        style.configure('Section.TLabel', font=(UI_FONT, 16, 'bold'))
        style.configure('Status.TLabel', foreground='#3e619f', font=(UI_FONT, 10, 'bold'))
        style.configure('TEntry', fieldbackground='#ffffff', foreground='#23334d', bordercolor='#c5d2e6', lightcolor='#c5d2e6', darkcolor='#c5d2e6', padding=8)
        style.map('TEntry', fieldbackground=[('readonly', '#e3ebf6')], foreground=[('readonly', '#52657e')])
        style.configure('TCombobox', fieldbackground='#ffffff', background='#dce6f5', foreground='#23334d', arrowcolor='#52657e', bordercolor='#c5d2e6', padding=7)
        style.map('TCombobox', fieldbackground=[('readonly', '#ffffff')], foreground=[('readonly', '#23334d')])
        style.configure('TButton', background='#dce6f5', foreground='#23334d', borderwidth=0, padding=(12, 9), font=(UI_FONT, 10))
        style.map('TButton', background=[('disabled', '#e5ecf7'), ('active', '#cbdaf0')], foreground=[('disabled', '#8b9cb5')])
        style.configure('Primary.TButton', background='#5d84cb', foreground='#ffffff', font=(UI_FONT, 10, 'bold'), padding=(12, 12))
        style.map('Primary.TButton', background=[('disabled', '#adbfdf'), ('active', '#466bad')], foreground=[('disabled', '#edf2fa'), ('!disabled', '#ffffff')])
        style.configure('Danger.TButton', foreground='#9b3e30')
        style.configure('TSeparator', background='#c5d2e6')
        self.option_add('*TCombobox*Listbox.background', '#ffffff')
        self.option_add('*TCombobox*Listbox.foreground', '#23334d')
        self.option_add('*TCombobox*Listbox.selectBackground', '#5d84cb')
        self.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')
        build_launcher_view(self, APPEARANCES, load_profile)
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.poll)

    def resize_background(self, event):
        layout_launcher_view(self, event.width, event.height)

    def paint_background(self, width, height):
        self.background_resize = None
        if self.background_source is None or width < 1 or height < 1:
            return
        fitted = self.image_ops.fit(self.background_source, (width, height))
        self.background_photo = self.image_tk.PhotoImage(fitted, master=self)
        self.backdrop.itemconfigure(self.background_item, image=self.background_photo)

    def config(self):
        result = {key: value.get().strip() for key, value in self.fields.items()}
        result['rig_type'] = 'R6'
        if result['rig'] == 'Custom': result['custom_avatar'] = validate_profile(self.custom_avatar)
        if not re.fullmatch(r'[A-Za-z0-9_]{1,20}', result['username']):
            raise ValueError('Username must contain 1–20 letters, digits, or underscores.')
        for key in ('web', 'soap', 'game'):
            result[key] = int(result[key])
            if not (key == 'web' and result[key] == 80) and not 1024 <= result[key] <= 65535:
                raise ValueError('Use HTTP port 80; other ports must be between 1024 and 65535.')
        if len({result['web'], result['soap'], result['game']}) != 3:
            raise ValueError('Choose three distinct ports.')
        return result

    def select_map(self):
        path = filedialog.askopenfilename(filetypes=[('Roblox maps', '*.rbxl *.rbxlx')])
        if path:
            self.map.set(path)

    def start(self):
        self.backend.start_http(self.config())

    def host(self):
        self.backend.host(self.config(), self.map.get())

    def join_remote(self):
        self.backend.join_multiplayer(self.join_address.get(), self.config())

    def copy_invite(self):
        if self.invite_link.get():
            self.clipboard_clear()
            self.clipboard_append(self.invite_link.get())
            self.events.put('Copied the invite link. Share it only with players you want to join.')


    def apply_rig(self):
        self.backend.set_rig(self.fields['rig'].get(), 'R6', self.custom_avatar)

    def toggle_custom_controls(self, *_):
        layout_launcher_view(self, max(980, self.backdrop.winfo_width()), max(800, self.backdrop.winfo_height()))

    def open_custom_editor(self):
        if self.avatar_editor is not None and self.avatar_editor.winfo_exists():
            self.avatar_editor.lift()
            return
        try:
            self.avatar_editor = AvatarEditor(self, self.custom_avatar, self.save_custom_avatar)
        except (ValueError, OSError) as error:
            messagebox.showerror('Customize avatar', str(error), parent=self)

    def save_custom_avatar(self, profile):
        self.custom_avatar = validate_profile(profile)
        self.fields['rig'].set('Custom')
        self.events.put('Saved custom outfit. Host a map or click Apply character to game to wear it.')

    def restore(self):
        if self.backend.http or (self.backend.rcc and self.backend.rcc.poll() is None):
            raise ValueError('Stop all servers before restoring XML.')
        for runtime in {ROOT, self.backend.runtime}:
            for folder in ('RobloxPlayer', 'RCCService'):
                path = runtime / folder / 'AppSettings.xml'
                backup = path.with_suffix('.xml.original')
                if backup.exists():
                    shutil.copy2(backup, path)
                    self.events.put(f'Restored {path}')

    def run(self, action):
        if self.busy:
            return
        # Snapshot Tk variables on the GUI thread before background work.
        try:
            if action == self.start:
                config = self.config()
                task = lambda: self.backend.start_http(config)
            elif action == self.host:
                config, map_path = self.config(), self.map.get()
                task = lambda: self.backend.host(config, map_path)
            elif action == self.join_remote:
                config, invite = self.config(), self.join_address.get()
                task = lambda: self.backend.join_multiplayer(invite, config)
            elif action == self.apply_rig:
                rig = self.fields['rig'].get()
                profile = validate_profile(self.custom_avatar)
                task = lambda: self.backend.set_rig(rig, 'R6', profile)
            else:
                task = action
        except Exception as error:
            messagebox.showerror('Settings', str(error))
            return
        self.busy = True
        for button in self.buttons:
            button.configure(state='disabled')

        def worker():
            try:
                task()
            except Exception as error:
                self.events.put('ERROR: ' + str(error))
            finally:
                self.events.put(None)
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                entry = self.events.get_nowait()
                if entry is None:
                    self.busy = False
                    for button in self.buttons:
                        button.configure(state='normal')
                else:
                    self.output.configure(state='normal')
                    tag = 'error' if entry.startswith('ERROR:') else 'success' if ('ready' in entry.lower() or 'Applied ' in entry) else ''
                    self.output.insert('end', entry + '\n', tag)
                    if entry.startswith('ERROR:'):
                        self.status.set('Something needs attention. See the notes below.')
                    elif entry.startswith('Game ready'):
                        self.status.set('Hosting your world')
                    elif entry.startswith('Patched client started'):
                        self.status.set('Roblox is open')
                    elif entry.startswith('Invite link: '):
                        self.invite_link.set(entry.split(': ', 1)[1])
                        self.status.set('Tunnel ready. Copy the invite for your friend.')
                    elif entry.startswith('Starting the public tunnel'):
                        self.status.set('Starting the tunnel...')
                    elif entry.startswith('Joined multiplayer as '):
                        self.status.set(entry)
                    elif entry.startswith('Tunnel stopped.'):
                        self.invite_link.set('')
                        self.status.set('Tunnel stopped. Click Share game to reconnect.')
                    elif entry == 'Owned game and client processes stopped.':
                        self.invite_link.set('')
                        self.status.set('Game stopped. Ready for another?')
                    elif entry == 'Python server stopped.':
                        self.status.set('All stopped. Ready when you are.')
                    self.output.see('end')
                    self.output.configure(state='disabled')
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo('Working', 'Wait for the current operation to finish, then close.')
            return
        self.backend.stop()
        self.destroy()


if __name__ == '__main__':
    Launcher().mainloop()

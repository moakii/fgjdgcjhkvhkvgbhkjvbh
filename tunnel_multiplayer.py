"""Ticketed Roblox UDP transport carried inside a persistent secure WebSocket.

Only this loopback lobby is published by cloudflared. The map, signing keys,
native RCC control port and the legacy client's local web bridge stay private.
"""
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import http.client
import ipaddress
import json
from pathlib import Path
import re
import secrets
import select
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, urlencode

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools/python-deps'))
import websocket
from wsproto import WSConnection, ConnectionType
from wsproto.events import Request as WSRequest, AcceptConnection, BytesMessage, TextMessage, Ping, CloseConnection
from wsproto.utilities import LocalProtocolError, RemoteProtocolError
VERSION = [0, 271, 1, 32426]
PROTOCOL = 3
MAX_BODY = 512 * 1024
TLS_CONTEXT = ssl.create_default_context()
CA_FILE = ROOT / 'tools/python-deps/certifi/cacert.pem'
if CA_FILE.exists():
    TLS_CONTEXT.load_verify_locations(cafile=str(CA_FILE))
DNS_CACHE = {}
DNS_LOCK = threading.Lock()


def tunnel_connection(address, timeout=20, source_address=None):
    """Preserve TLS SNI while recovering from stale/new-host DNS failures."""
    host, port = address
    try:
        return socket.create_connection(address, timeout, source_address)
    except socket.gaierror:
        if not re.fullmatch('[a-z0-9-]+\\.trycloudflare\\.com', host): raise
    with DNS_LOCK:
        cached = DNS_CACHE.get(host)
        if cached and cached[0] > time.monotonic():
            addresses = cached[1]
        else:
            resolver = http.client.HTTPSConnection('cloudflare-dns.com', timeout=10, context=TLS_CONTEXT)
            try:
                resolver.request('GET', '/dns-query?' + urlencode({'name': host, 'type': 'A'}),
                                 headers={'Accept': 'application/dns-json'})
                response = resolver.getresponse()
                raw = response.read(65537)
                if response.status != 200 or len(raw) > 65536:
                    raise OSError('Encrypted tunnel DNS lookup failed.')
                answer = json.loads(raw)
                addresses = [item['data'] for item in answer.get('Answer', []) if item.get('type') == 1
                             and ipaddress.ip_address(item['data']).is_global]
                if not addresses: raise OSError('Tunnel DNS is not ready. Retry in a moment.')
                if len(DNS_CACHE) >= 32: DNS_CACHE.pop(next(iter(DNS_CACHE)))
                DNS_CACHE[host] = (time.monotonic() + 60, addresses)
            finally: resolver.close()
    last_error = None
    for ip in addresses:
        try: return socket.create_connection((ip, port), timeout, source_address)
        except OSError as error: last_error = error
    raise last_error or OSError('Could not connect to the tunnel edge.')


def parse_invite(value):
    parsed = urlsplit(value.strip())
    try:
        loopback = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:
        loopback = False
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback)) or not parsed.hostname:
        raise ValueError('Paste the full HTTPS invite link from the host.')
    if parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query:
        raise ValueError('Invalid tunnel invite link.')
    if not re.fullmatch('[a-f0-9]{64}', parsed.fragment):
        raise ValueError('The invite is missing its access code. Copy the complete link, including # and the code.')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    if not 1 <= port <= 65535:
        raise ValueError('Invalid tunnel port.')
    return parsed.scheme, parsed.hostname, port, parsed.fragment


def pack_packets(packets):
    return b''.join(struct.pack('!H', len(packet)) + packet for packet in packets)


def unpack_packets(body):
    packets, offset = [], 0
    while offset < len(body):
        if offset + 2 > len(body): raise ValueError('Truncated game packet.')
        length = struct.unpack_from('!H', body, offset)[0]
        offset += 2
        if not 0 < length <= 65507 or offset + length > len(body): raise ValueError('Invalid game packet size.')
        packets.append(body[offset:offset + length])
        offset += length
    return packets


class HttpChannel:
    def __init__(self, invite):
        self.scheme, self.host, self.port, self.secret = parse_invite(invite)
        self.connection = None

    def close(self):
        connection, self.connection = self.connection, None
        if connection:
            connection.close()

    def request(self, method, path, body=None, ticket=None):
        if self.connection is None:
            if self.scheme == 'https':
                self.connection = http.client.HTTPSConnection(self.host, self.port, timeout=20, context=TLS_CONTEXT)
                self.connection._create_connection = tunnel_connection
            else:
                self.connection = http.client.HTTPConnection(self.host, self.port, timeout=20)
        connection = self.connection
        try:
            connection.request(method, '/clienter/' + path, body=body,
                                    headers={'Authorization': 'Bearer ' + (ticket or self.secret),
                                             'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store'})
            response = connection.getresponse()
            data = response.read(MAX_BODY + 1)
            if len(data) > MAX_BODY: raise ValueError('Tunnel response is too large.')
            if response.status != 200:
                try: reason = json.loads(data).get('error', f'HTTP {response.status}')
                except (ValueError, AttributeError): reason = f'HTTP {response.status}'
                raise ValueError('Tunnel: ' + reason)
            return data
        except Exception:
            self.close()
            raise

    def json(self, method, path, data=None, ticket=None):
        raw = self.request(method, path, json.dumps(data).encode() if data is not None else None, ticket)
        value = json.loads(raw)
        if not isinstance(value, dict): raise ValueError('Invalid tunnel response.')
        return value


class Lobby:
    def __init__(self, game_port, job, host_name, register, log):
        self.game_port, self.job, self.host_name = game_port, job, host_name
        self.register, self.log = register, log
        self.secret = secrets.token_hex(32)
        self.lock = threading.RLock()
        self.sessions = {}
        self.pending = 0
        self.next_id = 2
        self.names = {host_name.casefold()}
        self.closed = threading.Event()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler())
        self.server.daemon_threads = True
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self.reap, daemon=True).start()

    @property
    def local_invite(self):
        return f'http://127.0.0.1:{self.port}/#{self.secret}'

    def handler(self):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            disable_nagle_algorithm = True

            def setup(self):
                super().setup()
                self.connection.settimeout(25)

            def reply(self, data, status=200, binary=False):
                raw = data if binary else json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/octet-stream' if binary else 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(raw)

            def handle(self):
                try:
                    super().handle()
                except (ConnectionResetError, BrokenPipeError, TimeoutError):
                    self.close_connection = True

            def dispatch(self, method):
                try:
                    path = urlsplit(self.path).path
                    allowed = {'GET': {'/clienter/session', '/clienter/receive', '/clienter/stream'},
                               'POST': {'/clienter/join', '/clienter/send', '/clienter/avatar', '/clienter/leave'}}
                    if path not in allowed[method]:
                        self.close_connection = True
                        self.reply({'error': 'Unknown tunnel endpoint.'}, 404)
                        return
                    token = self.headers.get('Authorization', '').removeprefix('Bearer ')
                    if path in ('/clienter/session', '/clienter/join'):
                        if not secrets.compare_digest(token, owner.secret):
                            self.close_connection = True
                            self.reply({'error': 'Invalid invite access code.'}, 403)
                            return
                        session = None
                    else:
                        with owner.lock: session = owner.sessions.get(token)
                        if session is None:
                            self.close_connection = True
                            self.reply({'error': 'Session expired. Join again.'}, 403)
                            return
                        session['last'] = time.monotonic()
                    length = int(self.headers.get('Content-Length', '0'))
                    limit = MAX_BODY if path == '/clienter/send' else 65536
                    if not 0 <= length <= limit: raise ValueError('Request is too large.')
                    body = self.rfile.read(length) if length else b''
                    if len(body) != length: raise ValueError('Truncated request.')
                    if path == '/clienter/session':
                        self.reply({'protocol': PROTOCOL, 'version': VERSION, 'host': owner.host_name, 'transport': 'websocket'})
                    elif path == '/clienter/join':
                        self.reply(owner.join(json.loads(body)))
                    elif path == '/clienter/send':
                        for packet in unpack_packets(body): session['udp'].send(packet)
                        self.reply(b'', binary=True)
                    elif path == '/clienter/stream':
                        owner.stream(self, session)
                    elif path == '/clienter/receive':
                        with session['condition']:
                            if not session['queue'] and not session['closed'].is_set():
                                session['condition'].wait(.25)
                            packets, size = [], 0
                            while session['queue'] and size + len(session['queue'][0]) + 2 <= MAX_BODY:
                                packet = session['queue'].popleft()
                                packets.append(packet)
                                size += len(packet) + 2
                        self.reply(pack_packets(packets), binary=True)
                    elif path == '/clienter/avatar':
                        owner.register(session['id'], json.loads(body))
                        self.reply({'ok': True})
                    else:
                        owner.release(token)
                        self.reply({'ok': True})
                except (ValueError, TypeError, KeyError) as error:
                    self.close_connection = True
                    self.reply({'error': str(error)}, 400)
                except (OSError, TimeoutError):
                    self.close_connection = True
                except Exception:
                    self.close_connection = True
                    self.reply({'error': 'Host could not complete the request. Check its log.'}, 503)

            def do_GET(self): self.dispatch('GET')
            def do_POST(self): self.dispatch('POST')
            def log_message(self, *_): pass
        return Handler

    def join(self, data):
        if not isinstance(data, dict) or data.get('protocol') != PROTOCOL or data.get('version') != VERSION:
            raise ValueError('Use the same updated Clienter ZIP as the host.')
        name = data.get('username', '')
        if not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9_]{1,20}', name):
            raise ValueError('Username must contain 1-20 letters, digits or underscores.')
        with self.lock:
            if self.closed.is_set(): raise ValueError('Host has stopped.')
            if len(self.sessions) + self.pending >= 15: raise ValueError('This game is full.')
            self.pending += 1
            user_id = self.next_id
            self.next_id += 1
            # IDs also disambiguate simultaneous duplicate-name joins.
            original = name
            while name.casefold() in self.names:
                suffix = '_' + str(user_id)
                name = original[:20-len(suffix)] + suffix
                user_id = self.next_id
                self.next_id += 1
            self.names.add(name.casefold())
        udp = None
        try:
            self.register(user_id, data.get('avatar'))
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256*1024)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256*1024)
            udp.bind(('127.0.0.1', 0))
            udp.connect(('127.0.0.1', self.game_port))
            udp.settimeout(.5)
            token = secrets.token_hex(32)
            session = {'id': user_id, 'name': name, 'udp': udp, 'queue': deque(maxlen=128),
                       'condition': threading.Condition(), 'last': time.monotonic(), 'closed': threading.Event(), 'stream': None}
            with self.lock:
                if self.closed.is_set(): raise ValueError('Host has stopped.')
                self.sessions[token] = session
            threading.Thread(target=self.return_packets, args=(session,), daemon=True).start()
            return {'protocol': PROTOCOL, 'version': VERSION, 'user_id': user_id, 'username': name,
                    'ticket': token, 'job': self.job}
        except Exception:
            if udp: udp.close()
            with self.lock: self.names.discard(name.casefold())
            raise
        finally:
            with self.lock: self.pending -= 1

    def return_packets(self, session):
        while not session['closed'].is_set():
            try: packet = session['udp'].recv(65535)
            except socket.timeout: continue
            except OSError: return
            with session['condition']:
                session['queue'].append(packet)
                session['condition'].notify()

    def stream(self, handler, session):
        """Upgrade the authenticated connection and relay without per-batch RTTs."""
        codec = WSConnection(ConnectionType.SERVER)
        headers = handler.requestline + '\r\n' + ''.join(f'{key}: {value}\r\n' for key, value in handler.headers.items()) + '\r\n'
        try:
            codec.receive_data(headers.encode('latin1'))
            if not any(isinstance(event, WSRequest) for event in codec.events()):
                raise ValueError('Invalid WebSocket handshake.')
        except (LocalProtocolError, RemoteProtocolError) as error:
            raise ValueError('Invalid WebSocket handshake.') from error
        with self.lock:
            if session['stream'] is not None:
                handler.reply({'error': 'This session already has a game connection.'}, 409)
                return
            session['stream'] = handler.connection
        stopping = threading.Event()
        codec_lock, write_lock = threading.Lock(), threading.Lock()
        def send(event):
            with write_lock:
                with codec_lock: payload = codec.send(event)
                handler.connection.sendall(payload)
        try:
            handler.close_connection = True
            handler.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            send(AcceptConnection())
            def write_packets():
                try:
                    while not stopping.is_set() and not session['closed'].is_set():
                        with session['condition']:
                            if not session['queue']: session['condition'].wait(.25)
                            packets, size = [], 0
                            while session['queue'] and size+len(session['queue'][0])+2 <= MAX_BODY:
                                packet = session['queue'].popleft()
                                packets.append(packet)
                                size += len(packet)+2
                        if packets: send(BytesMessage(data=pack_packets(packets)))
                except (OSError, LocalProtocolError):
                    stopping.set()
                    try: handler.connection.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
            threading.Thread(target=write_packets, daemon=True).start()
            pending = bytearray()
            while not stopping.is_set() and not session['closed'].is_set():
                raw = handler.rfile.read1(65536)
                if not raw: break
                with codec_lock:
                    codec.receive_data(raw)
                    events = list(codec.events())
                session['last'] = time.monotonic()
                for event in events:
                    if isinstance(event, BytesMessage):
                        pending.extend(event.data)
                        if len(pending) > MAX_BODY: raise ValueError('Game message too large.')
                        if event.message_finished:
                            for packet in unpack_packets(pending): session['udp'].send(packet)
                            pending.clear()
                    elif isinstance(event, Ping):
                        send(event.response())
                    elif isinstance(event, CloseConnection):
                        send(event.response())
                        stopping.set()
                    elif isinstance(event, TextMessage):
                        raise ValueError('Binary game messages required.')
        except (OSError, ValueError, LocalProtocolError, RemoteProtocolError):
            pass
        finally:
            stopping.set()
            with session['condition']: session['condition'].notify_all()
            with self.lock:
                if session['stream'] is handler.connection: session['stream'] = None

    def release(self, token):
        with self.lock: session = self.sessions.pop(token, None)
        if session:
            with self.lock: self.names.discard(session['name'].casefold())
            session['closed'].set()
            session['udp'].close()
            if session['stream']:
                try: session['stream'].shutdown(socket.SHUT_RDWR)
                except OSError: pass
            with session['condition']: session['condition'].notify_all()

    def reap(self):
        while not self.closed.wait(5):
            with self.lock: expired = [t for t, s in self.sessions.items() if time.monotonic() - s['last'] > 45]
            for token in expired: self.release(token)

    def close(self):
        self.closed.set()
        with self.lock: tokens = list(self.sessions)
        for token in tokens: self.release(token)
        self.server.shutdown()
        self.server.server_close()


def open_websocket(invite, ticket):
    scheme, host, port, _ = parse_invite(invite)
    raw = tunnel_connection((host, port), 20) if scheme == 'https' else socket.create_connection((host, port), 20)
    try:
        raw.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if scheme == 'https':
            raw = TLS_CONTEXT.wrap_socket(raw, server_hostname=host)
        authority = '[' + host + ']' if ':' in host else host
        url = ('wss' if scheme == 'https' else 'ws') + '://' + authority + ':' + str(port) + '/clienter/stream'
        stream = websocket.create_connection(url, socket=raw, timeout=20, enable_multithread=True,
                    header={'Authorization': 'Bearer ' + ticket}, suppress_origin=True, redirect_limit=0)
        stream.settimeout(.5)
        return stream
    except Exception:
        raw.close()
        raise


class GameTunnel:
    def __init__(self, invite, ticket, log):
        if not re.fullmatch('[a-f0-9]{64}', ticket): raise ValueError('Invalid tunnel session ticket.')
        self.invite, self.ticket, self.log = invite, ticket, log
        self.closed = threading.Event()
        self.local_peer = None
        self.stream_lock = threading.RLock()
        self.stream = None
        self.local = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.local.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 256*1024)
        self.local.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 256*1024)
        self.local.bind(('127.0.0.1', 0))
        self.local.settimeout(.1)
        self.port = self.local.getsockname()[1]
        try:
            self.stream = open_websocket(invite, ticket)
        except Exception:
            self.local.close()
            raise
        self.last_ping = 0
        self.last_report = 0
        self.log('Game tunnel connected in low-latency WebSocket mode.')
        threading.Thread(target=self.outgoing, daemon=True).start()
        threading.Thread(target=self.incoming, daemon=True).start()

    def ensure_stream(self):
        with self.stream_lock:
            if self.closed.is_set(): raise OSError('Game tunnel is closed.')
            if self.stream is None: self.stream = open_websocket(self.invite, self.ticket)
            return self.stream

    def drop_stream(self, stream):
        with self.stream_lock:
            if self.stream is not stream: return
            self.stream = None
            stream.abort()
            stream.shutdown()

    def outgoing(self):
        while not self.closed.is_set():
            stream = None
            try:
                packet, peer = self.local.recvfrom(65535)
                if self.local_peer and self.local_peer != peer: continue
                self.local_peer = peer
                packets = [packet]
                for _ in range(7):
                    if not select.select([self.local], [], [], 0)[0]: break
                    extra, sender = self.local.recvfrom(65535)
                    if sender == peer: packets.append(extra)
                stream = self.ensure_stream()
                stream.send_binary(pack_packets(packets))
            except socket.timeout: continue
            except (OSError, ValueError, websocket.WebSocketException):
                if stream: self.drop_stream(stream)
                self.closed.wait(.1)

    def incoming(self):
        failures = 0
        while not self.closed.is_set():
            stream = None
            try:
                stream = self.ensure_stream()
                if time.monotonic()-self.last_ping >= 10:
                    stream.ping(struct.pack('!d', time.monotonic()))
                    self.last_ping = time.monotonic()
                opcode, body = stream.recv_data(control_frame=True)
                if opcode == websocket.ABNF.OPCODE_CLOSE: raise OSError('Host closed the game stream.')
                failures = 0
                if opcode == websocket.ABNF.OPCODE_BINARY:
                    for packet in unpack_packets(body):
                        if self.local_peer: self.local.sendto(packet, self.local_peer)
                elif opcode == websocket.ABNF.OPCODE_PONG and len(body) == 8:
                    latency = (time.monotonic()-struct.unpack('!d',body)[0])*1000
                    if time.monotonic()-self.last_report >= 30:
                        self.log(f'Tunnel network round trip: {latency:.0f} ms.')
                        self.last_report = time.monotonic()
            except websocket.WebSocketTimeoutException:
                continue
            except (OSError, ValueError, websocket.WebSocketException):
                if stream: self.drop_stream(stream)
                failures += 1
                if failures == 3: self.log('Tunnel connection interrupted. Reconnecting...')
                if failures >= 20:
                    self.close()
                    return
                self.closed.wait(min(2, .1*failures))

    def close(self):
        self.closed.set()
        self.local.close()
        with self.stream_lock:
            stream, self.stream = self.stream, None
        if stream:
            stream.abort()
            stream.shutdown()


class PublicTunnel:
    def __init__(self, lobby, log):
        self.lobby, self.log = lobby, log
        self.process = None
        self.url = None
        self.ready = threading.Event()
        self.diagnostics = deque(maxlen=12)
        self.stopping = False

    def start(self):
        folder = ROOT / 'tools/tunnel'
        exe = folder / 'cloudflared.exe'
        manifest = json.loads((folder / 'manifest.json').read_text())
        if hashlib.sha256(exe.read_bytes()).hexdigest() != manifest['sha256']:
            raise RuntimeError('Tunnel helper checksum mismatch. Re-extract the updated ZIP.')
        args = [str(exe), 'tunnel', '--no-autoupdate', '--url', f'http://127.0.0.1:{self.lobby.port}',
                '--protocol', 'http2', '--edge-ip-version', '4']
        self.process = subprocess.Popen(args, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding='utf-8', errors='replace',
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        def read_output():
            for line in self.process.stdout:
                self.diagnostics.append(line.strip())
                match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
                if match:
                    self.url = match.group() + '/#' + self.lobby.secret
                    self.ready.set()
            self.ready.set()
            if self.url and not self.stopping and not self.lobby.closed.is_set():
                self.log('Tunnel stopped. Restart Share game to create a new invite.')
        threading.Thread(target=read_output, daemon=True).start()
        if not self.ready.wait(60) or not self.url or self.process.poll() is not None:
            self.close()
            raise RuntimeError('Could not start the public tunnel. Check internet access to Cloudflare, then retry Share game.')
        # A printed URL can precede route activation. Verify an authenticated
        # request through the public edge before showing a working invite.
        deadline = time.monotonic() + 45
        last_error = ''
        while time.monotonic() < deadline and self.process.poll() is None:
            channel = HttpChannel(self.url)
            try:
                description = channel.json('GET', 'session')
                if description.get('protocol') == PROTOCOL:
                    self.log('Tunnel ready. Copy the invite link for your friend.')
                    return self.url
            except (OSError, ValueError, http.client.HTTPException) as error:
                last_error = str(error)
                time.sleep(1)
            finally: channel.close()
        details = ' | '.join(line for line in self.diagnostics if ' ERR ' in line)
        self.close()
        if details: self.log('Tunnel diagnostic: ' + details)
        raise RuntimeError('The public tunnel route could not be reached: ' + last_error + '. Retry Share game after checking the connection.')

    def close(self):
        self.stopping = True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.url = None

"""Fetch publicly accessible Roblox assets over HTTPS for the legacy client."""
from collections import OrderedDict
import gzip
from http.client import HTTPException
import io
from pathlib import Path
import re
import socket
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid
import zlib

MAX_BYTES = 64 * 1024 * 1024


class AssetError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def trusted_url(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower()
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not any(host == domain or host.endswith('.' + domain) for domain in ('roblox.com', 'rbxcdn.com'))):
        raise AssetError(502, 'Roblox returned an unsupported asset download location.')
    return url


class AssetRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        trusted_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


HTTP = build_opener(ProxyHandler({}), AssetRedirects())


def numeric_id(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,19}', value) or not 0 < int(value) < 2**63:
        raise AssetError(400, f'Invalid {label}.')
    return str(int(value))


class RobloxAssets:
    def __init__(self, directory, log):
        self.directory = Path(directory)
        self.log = log
        self.locks = [threading.Lock() for _ in range(32)]
        self.failures = OrderedDict()
        self.failure_lock = threading.Lock()
        self.download_slots = threading.BoundedSemaphore(4)

    def fetch(self, asset, version=None):
        asset = numeric_id(asset, 'asset ID')
        version = numeric_id(version, 'asset version') if version is not None else None
        key = asset + ('-v' + version if version else '-latest')
        path = self.directory / (key + '.bin')
        with self.locks[hash(key) % len(self.locks)]:
            if path.is_file():
                if path.stat().st_size <= MAX_BYTES:
                    return path.read_bytes()
                raise AssetError(413, 'Cached asset exceeds the download size limit.')
            with self.failure_lock:
                failure = self.failures.get(key)
                if failure and time.monotonic() < failure[0]:
                    raise AssetError(failure[1], failure[2])
            try:
                with self.download_slots:
                    data = self.download(asset, version)
            except AssetError as error:
                with self.failure_lock:
                    self.failures[key] = (time.monotonic() + 15, error.status, str(error))
                    self.failures.move_to_end(key)
                    while len(self.failures) > 256:
                        self.failures.popitem(last=False)
                self.log(str(error))
                raise
            temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                temporary.write_bytes(data)
                temporary.replace(path)
            except OSError:
                self.log(f'Asset {asset} downloaded, but could not be cached on disk.')
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self.log(f'Downloaded Roblox asset {asset}' + (f' version {version}' if version else '') + f' ({len(data)} bytes).')
            return data

    def download(self, asset, version):
        query = {'id': asset}
        if version:
            query['version'] = version
        url = 'https://assetdelivery.roblox.com/v1/asset/?' + urlencode(query)
        request = Request(url, headers={'User-Agent': 'Clienter/2016', 'Accept-Encoding': 'identity'})
        try:
            with HTTP.open(request, timeout=20) as response:
                trusted_url(response.geturl())
                if response.headers.get_content_type() in ('application/json', 'text/html'):
                    raise AssetError(502, f'Roblox returned a non-asset response for {asset}.')
                data = response.read(MAX_BYTES + 1)
            if data.startswith(b'\x1f\x8b'):
                if len(data) > MAX_BYTES:
                    raise AssetError(413, f'Asset {asset} exceeds the download size limit.')
                with gzip.GzipFile(fileobj=io.BytesIO(data)) as zipped:
                    data = zipped.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise AssetError(413, f'Asset {asset} exceeds the download size limit.')
            if not data:
                raise AssetError(502, f'Roblox returned an empty asset for {asset}.')
            return data
        except HTTPError as error:
            if error.code in (401, 403):
                raise AssetError(403, f'Roblox asset {asset} requires authorization or is restricted.') from error
            if error.code == 404:
                raise AssetError(404, f'Roblox asset {asset} was not found.') from error
            if error.code == 429:
                raise AssetError(429, 'Roblox is rate-limiting asset downloads; try again shortly.') from error
            raise AssetError(502, f'Roblox could not deliver asset {asset} (HTTP {error.code}).') from error
        except (URLError, TimeoutError, socket.timeout) as error:
            raise AssetError(504, f'Cannot reach Roblox to download asset {asset}. Check the internet connection.') from error
        except (OSError, EOFError, zlib.error, HTTPException) as error:
            raise AssetError(502, f'Roblox asset {asset} download was incomplete or invalid.') from error

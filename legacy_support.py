"""Local domain/key patching, based on worships/roblox-auto-patcher (Apache-2.0).

Original executables are read only. Patched copies keep RSA verification enabled.
"""
from pathlib import Path
import base64
import re
import struct
import sys
import json
import hashlib
import shutil

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'tools/python-deps'))
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

DOMAIN = 'localhost.'  # Fixed-width ten-byte legacy URL identifier.


def executable_version(path):
    data = Path(path).read_bytes()
    offset = data.find(bytes.fromhex('bd04effe00000100'))
    if offset < 0:
        raise RuntimeError(f'No fixed file version in {path}')
    high, low = struct.unpack_from('<II', data, offset + 8)
    return high >> 16, high & 65535, low >> 16, low & 65535


def local_settings(folder):
    directory = Path(folder) / 'ClientSettings'
    directory.mkdir(exist_ok=True)
    path = directory / 'ClientAppSettings.json'
    data = json.loads(path.read_text()) if path.exists() else {}
    # Both peers must use the same local-development packet layout.
    data['FFlagDebugLocalRccServerConnection'] = True
    data['FFlagNewColor3Functions'] = True
    data['FFlagUseUserListMenu'] = True
    data['DFFlagDontUseInsertServiceOnAnimLoad'] = True
    data['DFFlagUrlReconstructToAssetGame'] = True
    data['FFlagSoundServiceGameConfigurerConfigureRunServiceRun'] = True
    data['FFlagUsePreferredSoundDevice'] = True
    path.write_text(json.dumps(data, indent=2))
    # This bundled SettingsHub initializes PlayersPage, but its initial switch
    # refers to the nonexistent singular PlayerPage when the user-list flag is on.
    hub = Path(folder) / 'content/scripts/Modules/Settings/SettingsHub.lua'
    if hub.is_file():
        before = hub.read_text(encoding='utf-8-sig')
        after = before.replace('this:SwitchToPage(this.PlayerPage, true, 1)',
                               'this:SwitchToPage(this.PlayersPage, true, 1)')
        if after != before:
            hub.write_text(after, encoding='utf-8')


def local_animations(runtime):
    cache = ROOT / 'assets/animations'
    manifest = json.loads((cache / 'manifest.json').read_text())
    for folder in ('RobloxPlayer', 'RCCService'):
        content = Path(runtime) / folder / 'content'
        destination = content / 'animations'
        destination.mkdir(exist_ok=True)
        for asset, metadata in manifest.items():
            source = cache / f'{asset}.rbxm'
            if hashlib.sha256(source.read_bytes()).hexdigest() != metadata['sha256']:
                raise RuntimeError(f'Animation cache integrity check failed for {asset}')
            target = destination / source.name
            if not target.exists() or target.read_bytes() != source.read_bytes():
                shutil.copy2(source, target)
        for path in (content / 'fonts').glob('humanoidAnimate*.rbxm'):
            backup = path.with_suffix('.rbxm.animation-original')
            original = backup.read_bytes() if backup.exists() else path.read_bytes()
            def replace(match):
                asset = match.group(1).decode()
                if asset in manifest:
                    return f'http://{DOMAIN}/asset/?id={asset}'.encode()
                return match.group()
            updated = re.sub(rb'https?://www\.roblox\.com/asset/\?id=(\d+)', replace, original,
                             flags=re.IGNORECASE)
            if updated != original:
                if not backup.exists():
                    backup.write_bytes(original)
                if path.read_bytes() != updated:
                    path.write_bytes(updated)


def local_avatars(runtime):
    cache = ROOT / 'assets/avatars'
    manifest = json.loads((cache / 'manifest.json').read_text())
    for folder in ('RobloxPlayer', 'RCCService'):
        destination = Path(runtime) / folder / 'content/avatars'
        destination.mkdir(exist_ok=True)
        for name, metadata in manifest.items():
            source = cache / name
            if hashlib.sha256(source.read_bytes()).hexdigest() != metadata['sha256']:
                raise RuntimeError(f'Avatar asset integrity check failed for {name}')
            target = destination / name
            if not target.exists() or target.read_bytes() != source.read_bytes():
                shutil.copy2(source, target)


def private_key():
    directory = ROOT / 'local-keys'
    directory.mkdir(exist_ok=True)
    path = directory / 'rbxsig_private.pem'
    if not path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                         serialization.PrivateFormat.TraditionalOpenSSL,
                         serialization.NoEncryption()))
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def patch_chat_metadata(original, patched):
    """Route this exact 2016 build's player metadata formatter to localhost.

    Its normal URL builder returns an empty URL without the retired bootstrap
    configuration. Keep the native chat/filter events; change only this URL.
    The existing push operand retains its PE relocation, and the replacement
    call uses the engine's own std::string::substr return-value constructor.
    """
    import pefile
    allowed = {'057cdde2e9efb2b22df8f6118663982edeaae36e0126d9dd1e3c45d78dad9317'}
    if hashlib.sha256(original).hexdigest() not in allowed:
        raise RuntimeError('Unrecognized engine build: refusing the chat metadata URL patch')
    pe = pefile.PE(data=original, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_BASERELOC']])
    base = pe.OPTIONAL_HEADER.ImageBase
    path = b'/game/players/%d\0'
    position = original.find(path)
    address = base + pe.get_rva_from_offset(position)
    references = [m.start() for m in re.finditer(re.escape(b'\x68' + struct.pack('<I', address)), original)]
    if len(references) != 1: raise RuntimeError('Unrecognized player metadata formatter')
    reference = references[0]
    pattern = (rb'\x8b\x75\x08\x68....\xff\x75\x14\xc6\x45\xfc\x01\x50\x8d\x45\xd8'
               rb'\x50\xff\x75\x0c\x56\xe8....\x83\xc4\x24')
    match = re.search(pattern, original[reference:reference + 100], re.DOTALL)
    if match is None: raise RuntimeError('Player metadata URL call did not match')
    start, end = reference + match.start(), reference + match.end()
    call = end - 8
    builder = base + pe.get_rva_from_offset(call) + 5 + struct.unpack_from('<i', original, call + 1)[0]
    builder_offset = pe.get_offset_from_rva(builder - base)
    constructor = re.search(rb'\x6a\x00\x8d\x45.\x50\x8b\xce\xe8(.{4})',
                            original[builder_offset:builder_offset + 400], re.DOTALL)
    if constructor is None: raise RuntimeError('Native URL string constructor did not match')
    call_offset = builder_offset + constructor.start() + 8
    substring = base + pe.get_rva_from_offset(call_offset) + 5 + struct.unpack_from('<i', original, call_offset + 1)[0]
    local_url = b'http://' + DOMAIN.encode() + b'/game/players/%d\0'
    section = next((s for s in pe.sections if s.Name.rstrip(b'\0') == b'.rdata'
                    and s.SizeOfRawData - s.Misc_VirtualSize >= len(local_url)), None)
    if section is None: raise RuntimeError('No reserved metadata URL storage in this build')
    storage = section.PointerToRawData + section.Misc_VirtualSize
    if any(original[storage:storage + len(local_url)]): raise RuntimeError('Metadata URL padding is not empty')
    output = bytearray(patched)
    output[storage:storage + len(local_url)] = local_url
    struct.pack_into('<I', output, section.get_file_offset() + 8, section.Misc_VirtualSize + len(local_url))
    local_address = base + section.VirtualAddress + section.Misc_VirtualSize
    struct.pack_into('<I', output, reference + 1, local_address)
    prefix = b'\x8b\xc8\x8b\x75\x08\xc6\x45\xfc\x01\x6a\xff\x6a\x00\x56'
    call_address = base + pe.get_rva_from_offset(start) + len(prefix)
    code = prefix + b'\xe8' + struct.pack('<i', substring - call_address - 5) + b'\x83\xc4\x0c'
    if len(code) > end - start: raise RuntimeError('Metadata URL patch exceeds its instruction slot')
    output[start:end] = code.ljust(end - start, b'\x90')
    # The old "https" push had an absolute-address relocation inside this
    # instruction slot. Remove that now-unused relocation so ASLR cannot alter
    # the new relative-call instructions. Keep the format-string relocation.
    removed = 0
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if base + pe.get_rva_from_offset(start) <= base + entry.rva < base + pe.get_rva_from_offset(end):
                if entry.type != 3: raise RuntimeError('Unexpected metadata instruction relocation')
                struct.pack_into('<H', output, entry.struct.get_file_offset(), entry.rva & 0xfff)
                removed += 1
    if removed != 1: raise RuntimeError('Metadata URL relocation did not match')
    # The newer native Chat service has its own moderation URL builder; the
    # legacy Players:SetChatFilterUrl setter does not initialize that builder.
    # Return a local absolute URL through the engine's existing string formatter.
    name_offset = original.find(b'\0ModerationFilterTextUrlV1\0') + 1
    name_address = base + pe.get_rva_from_offset(name_offset)
    names = [m.start() for m in re.finditer(re.escape(b'\x68' + struct.pack('<I', name_address)), original)]
    if len(names) != 1 or original[names[0] - 5] != 0x68:
        raise RuntimeError('Native moderation URL setting did not match')
    url_variable = original[names[0] - 4:names[0]]
    moderation_pattern = (rb'\x68....\x56\x8b\x75\x08\x68' + re.escape(url_variable)
                          + rb'\x8d\x45\xd8\x50\xff\x75\x0c\xc7\x45\xfc\x00\x00\x00\x00'
                          rb'\x56\xe8....\x83\xc4\x18')
    moderation = list(re.finditer(moderation_pattern, original, re.DOTALL))
    if len(moderation) != 1: raise RuntimeError('Native moderation URL formatter did not match')
    mod_start, mod_end = moderation[0].span()
    filter_url = b'http://' + DOMAIN.encode() + b'/Game/ChatFilter.ashx\0'
    filter_storage = storage + len(local_url)
    if filter_storage + len(filter_url) > section.PointerToRawData + section.SizeOfRawData:
        raise RuntimeError('No reserved moderation URL storage')
    if any(original[filter_storage:filter_storage + len(filter_url)]):
        raise RuntimeError('Moderation URL padding is not empty')
    output[filter_storage:filter_storage + len(filter_url)] = filter_url
    struct.pack_into('<I', output, section.get_file_offset() + 8,
                     section.Misc_VirtualSize + len(local_url) + len(filter_url))
    filter_address = local_address + len(local_url)
    # Reuse the printf-style std::string constructor called just before the
    # player metadata formatter, with a literal URL and no format arguments.
    format_call = original.rfind(b'\xe8', reference, start)
    formatter = base + pe.get_rva_from_offset(format_call) + 5 + struct.unpack_from('<i', original, format_call + 1)[0]
    prefix = b'\x68' + struct.pack('<I', filter_address) + b'\x8b\x75\x08\xc7\x45\xfc\x00\x00\x00\x00\x56'
    code = prefix + b'\xe8' + struct.pack('<i', formatter - (base + pe.get_rva_from_offset(mod_start) + len(prefix) + 5)) + b'\x83\xc4\x08'
    if len(code) > mod_end - mod_start: raise RuntimeError('Moderation URL instruction slot is too small')
    output[mod_start:mod_end] = code.ljust(mod_end - mod_start, b'\x90')
    removed = 0
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if pe.get_rva_from_offset(mod_start) <= entry.rva < pe.get_rva_from_offset(mod_end):
                if entry.rva == pe.get_rva_from_offset(mod_start) + 1: continue
                if entry.type != 3: raise RuntimeError('Unexpected moderation URL relocation')
                struct.pack_into('<H', output, entry.struct.get_file_offset(), entry.rva & 0xfff)
                removed += 1
    if removed != 1: raise RuntimeError('Moderation URL relocation did not match')
    # Use the engine's v1 moderation protocol implemented by the local endpoint.
    # The v2 service depends on the retired bootstrap/API configuration.
    flag_offset = original.find(b'\0UseModerationFilterTextV2\0') + 1
    flag_address = base + pe.get_rva_from_offset(flag_offset)
    refs = list(re.finditer(re.escape(b'\x68' + struct.pack('<I', flag_address)), original))
    if len(refs) != 1: raise RuntimeError('Moderation version flag did not match')
    ref = refs[0].start()
    slot = ref + 13
    if original[ref - 5] != 0x68 or original[slot:slot + 1] != b'\xa3' or original[slot + 5:slot + 8] != b'\xc3\xcc\xcc':
        raise RuntimeError('Moderation version initializer did not match')
    output[slot:slot + 8] = b'\xc6\x05' + original[ref - 4:ref] + b'\x00\xc3'
    relocated = 0
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if entry.rva == pe.get_rva_from_offset(slot) + 1:
                if entry.type != 3 or (entry.rva & 0xfff) == 0xfff:
                    raise RuntimeError('Moderation flag relocation did not match')
                struct.pack_into('<H', output, entry.struct.get_file_offset(), 0x3000 | ((entry.rva + 1) & 0xfff))
                relocated += 1
    if relocated != 1: raise RuntimeError('Moderation flag relocation was not found')
    return bytes(output)


def patch_executable(original):
    original = Path(original)
    data = original.read_bytes()
    numbers = private_key().public_key().public_numbers()
    blob = struct.pack('<BBHIIII', 6, 2, 0, 0x2400, 0x31415352, 1024, numbers.e)
    blob += numbers.n.to_bytes(128, 'little')
    public = base64.b64encode(blob)
    matches = set(re.findall(rb'BgIAAACkAABSU0ExAAQAA[A-Za-z0-9+/=]+', data))
    if not matches or any(len(match) != len(public) for match in matches):
        raise RuntimeError(f'Unrecognized legacy signing key in {original.name}')
    def replace_literal(match):
        before = match.group()
        after = before.replace(b'roblox.com', DOMAIN.encode())
        return after.ljust(len(before), b'\0')
    patched = re.sub(rb'[\x20-\x7e]*roblox\.com[\x20-\x7e]*\x00', replace_literal, data)
    def replace_wide(match):
        before = match.group()
        after = before.replace('roblox.com'.encode('utf-16-le'), DOMAIN.encode('utf-16-le'))
        return after.ljust(len(before), b'\0')
    patched = re.sub(rb'(?:[\x20-\x7e]\x00)*r\x00o\x00b\x00l\x00o\x00x\x00\.\x00c\x00o\x00m\x00(?:[\x20-\x7e]\x00)*\x00\x00', replace_wide, patched)
    for match in matches:
        patched = patched.replace(match, public)
    if original.name == 'RCCService.exe' and executable_version(original) == (0, 271, 1, 32426):
        expected = '057cdde2e9efb2b22df8f6118663982edeaae36e0126d9dd1e3c45d78dad9317'
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('Unrecognized RCC build: refusing the local-development flag patch')
        # Initialize the engine's DebugLocalRccServerConnection flag to true.
        # This exact startup call was disassembled and checked for this build.
        pe = struct.unpack_from('<I', data, 0x3c)[0]
        count, optional = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
        offset = None
        for index in range(count):
            section = pe + 24 + optional + 40 * index
            virtual_size, rva, raw_size, raw = struct.unpack_from('<IIII', data, section + 8)
            if rva <= 0xaca766 < rva + max(virtual_size, raw_size):
                offset = raw + 0xaca766 - rva
        if offset is None or data[offset:offset + 8] != bytes.fromhex('a3e4f98201c3cccc'):
            raise RuntimeError('Local-development flag instruction did not match')
        # RegisterFastFlag returns AL=1. Preserve the absolute-address operand's
        # existing PE relocation position while storing that byte in the flag.
        patched = patched[:offset] + bytes.fromhex('a2ecf88201c3cccc') + patched[offset + 8:]
        sections = []
        for index in range(count):
            section = pe + 24 + optional + 40 * index
            size, rva, raw_size, raw = struct.unpack_from('<IIII', data, section + 8)
            sections.append((rva, raw, max(size, raw_size)))
        image_base = struct.unpack_from('<I', data, pe + 24 + 28)[0]
        for flag in ('DontUseInsertServiceOnAnimLoad', 'UrlReconstructToAssetGame'):
            string_offset = data.find(b'\0' + flag.encode() + b'\0') + 1
            address = None
            for rva, raw, size in sections:
                if raw <= string_offset < raw + size:
                    address = image_base + rva + string_offset - raw
                    break
            if address is None:
                raise RuntimeError(f'Flag name not found: {flag}')
            pattern = struct.pack('<I', address)
            candidates = []
            for match in re.finditer(re.escape(pattern), data):
                ref = match.start()
                if (data[ref - 6] == 0x68 and data[ref - 1] == 0x68
                        and data[ref + 4] == 0xe8
                        and data[ref + 9:ref + 13] == bytes.fromhex('83c410a3')
                        and data[ref + 17] == 0xc3):
                    candidates.append(ref)
            if len(candidates) != 1:
                raise RuntimeError(f'Unrecognized flag initializer: {flag}')
            ref = candidates[0]
            position = ref + 12
            instruction = b'\xa2' + data[ref - 5:ref - 1] + b'\xc3'
            patched = patched[:position] + instruction + patched[position + 6:]
    if original.name == 'RCCService.exe' and executable_version(original) == (0, 271, 1, 32426):
        patched = patch_chat_metadata(data, patched)
    if len(patched) != len(data):
        raise RuntimeError('Executable patch changed file length')
    revision = hashlib.sha256(patched).hexdigest()[:12]
    target = original.with_name(original.stem + f'_local_{revision}.exe')
    if not target.exists() or target.read_bytes() != patched:
        target.write_bytes(patched)
    return target


def signed_join(data):
    payload = b'\r\n' + data.encode('utf-8')
    signature = private_key().sign(payload, padding.PKCS1v15(), hashes.SHA1())
    return '--rbxsig%' + base64.b64encode(signature).decode() + '%' + payload.decode()

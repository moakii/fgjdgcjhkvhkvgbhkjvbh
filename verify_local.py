"""Integration smoke test: starts owned test processes, then cleans them up."""
import json
import time
from pathlib import Path
import Clienter as patcher
from legacy_support import private_key
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64
import xml.etree.ElementTree as ET
import sys
import socket
from xml.sax.saxutils import escape

messages = []
def log(text):
    messages.append(text)
    print(text, flush=True)
backend = patcher.Backend(log)
maps = sorted((patcher.ROOT / 'RCCService/content').glob('local-map-*.rbxl'))
map_path = patcher.ROOT / 'RCCService/content/temp.rbxl'
if '--selected' in sys.argv and maps:
    map_path = max(maps, key=lambda path: path.stat().st_size)
log_directory = Path.home() / 'AppData/Local/Roblox/logs'
logs_before = set(log_directory.glob('*.txt'))


def player_state():
    result = patcher.soap(64998, 'ExecuteEx', f'<jobID>{backend.job}</jobID><script><name>VerifyPlayer</name>'
                         '<script>local p=game:GetService("Players"):GetPlayers(); '
                         'return #p, p[1] and p[1].Name or "none", '
                         'p[1] and p[1].Character ~= nil or false, '
                         'settings():GetFFlag("DebugLocalRccServerConnection")</script></script>')
    return [node.text for node in ET.fromstring(result).iter() if node.tag.endswith('}value')]


def execute(script):
    result = patcher.soap(64998, 'ExecuteEx', f'<jobID>{backend.job}</jobID><script><name>VerifyAnimations</name>'
                         f'<script>{escape(script)}</script></script>')
    return [node.text for node in ET.fromstring(result).iter() if node.tag.endswith('}value')]


try:
    occupied = None
    if '--occupied' in sys.argv:
        occupied = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        occupied.bind(('0.0.0.0', 53649))
    backend.host(dict(username='Player', web=80, soap=64998, game=53649), str(map_path))
    if occupied:
        assert backend.config['game'] != 53649, 'Occupied game port was reused'
    join = backend.join_script()
    prefix, signature, payload = join.split('%', 2)
    assert prefix == '--rbxsig'
    private_key().public_key().verify(base64.b64decode(signature), payload.encode(),
                                     padding.PKCS1v15(), hashes.SHA1())
    assert json.loads(payload)['UserName'] == 'Player'
    backend.join()
    time.sleep(12)
    state = player_state()
    print('PLAYER_STATE', state, flush=True)
    assert state == ['1', 'Player', 'true', 'true'], 'Player did not join and spawn'
    if '--sound' in sys.argv:
        print('CHARACTER_SOUNDS', execute('''
local c=game:GetService("Players"):GetPlayers()[1].Character
local result={}
local function scan(parent)
 for _,child in ipairs(parent:GetChildren()) do
  if child:IsA("Sound") then table.insert(result,child.Name.."="..child.SoundId..";volume="..child.Volume) end
  scan(child)
 end
end
scan(c)
return table.concat(result," | ")
'''), flush=True)
        execute('''
local event=Instance.new("RemoteEvent",workspace)
event.Name="LocalSoundProbe"
event.OnServerEvent:connect(function(player,result) _G.SoundProbe=result end)
local probe=Instance.new("LocalScript")
probe.Source=[=[
local sound=Instance.new("Sound",game:GetService("SoundService"))
sound.SoundId="rbxasset://sounds/action_jump.mp3"
sound.Volume=0.5
sound.Looped=true
sound:Play()
for attempt=1,80 do if sound.TimeLength>0 then break end wait(0.1) end
local before=sound.TimePosition
wait(0.15)
local result=tostring(sound.TimeLength)..":"..tostring(sound.IsPlaying)..":"..tostring(before)..":"..tostring(sound.TimePosition)
sound:Destroy()
local character=game:GetService("Players").LocalPlayer.Character
character:WaitForChild("Humanoid").Jump=true
wait(0.15)
local jumping=character.Head:WaitForChild("Jumping")
workspace.LocalSoundProbe:FireServer(result..":"..tostring(jumping.TimeLength)..":"..tostring(jumping.TimePosition))
]=]
probe.Parent=game:GetService("Players"):GetPlayers()[1]:WaitForChild("PlayerGui")
''')
        time.sleep(10)
        sound_report = execute('return _G.SoundProbe or "No sound probe response"')[0]
        print('CLIENT_SOUND', sound_report, flush=True)
        fields = sound_report.split(':')
        assert len(fields) == 6, 'Client sound probe did not complete'
        assert float(fields[0]) > 0 and fields[1] == 'true', 'Local sound did not decode/play'
        assert abs(float(fields[3]) - float(fields[2])) > 0.005, 'Audio playback is stuck'
        assert float(fields[4]) > 0 and float(fields[5]) > 0, 'Character jump sound did not play'
    if '--rigs' in sys.argv:
        def mesh_count():
            return int(execute('''local count=0
for _,item in ipairs(game:GetService("Players"):GetPlayers()[1].Character:GetChildren()) do
 if item:IsA("CharacterMesh") then count=count+1 end
end
return count''')[0])
        def rig_state():
            return execute('''local c=game:GetService("Players"):GetPlayers()[1].Character
local colors
for _,item in ipairs(c:GetChildren()) do if item:IsA("BodyColors") then colors=item end end
return _G.LocalRig,c:FindFirstChild("Pal Hair") ~= nil,c:FindFirstChild("Shirt") ~= nil,
colors.HeadColor.Number,colors.TorsoColor.Number,colors.LeftLegColor.Number,c:FindFirstChild("Animate") ~= nil''')
        bacon = rig_state()
        print('BACON_RIG', bacon, flush=True)
        assert bacon[:3] == ['Bacon Hair', 'true', 'true'] and bacon[-1] == 'true'
        assert mesh_count() == 5, 'Bacon Hair is missing the Man body bundle'
        backend.set_rig('Noob')
        assert rig_state() == ['Noob', 'false', 'false', '24', '23', '119', 'true']
        assert mesh_count() == 0, 'Noob should keep the normal block body'
        execute('game:GetService("Players"):GetPlayers()[1]:LoadCharacter()')
        time.sleep(3)
        assert rig_state() == ['Noob', 'false', 'false', '24', '23', '119', 'true']
        assert mesh_count() == 0
        backend.set_rig('Bacon Hair')
        time.sleep(2)
        assert rig_state() == bacon
        assert mesh_count() == 5
        print('PASS: Bacon Hair default, live Noob switch, respawn persistence, switch back.', flush=True)
    if '--animations' in sys.argv:
        report = execute('''
local h=game:GetService("Players"):GetPlayers()[1].Character:FindFirstChild("Humanoid")
local tracks=h:GetPlayingAnimationTracks()
local descriptions={}
for _,track in ipairs(tracks) do
 table.insert(descriptions,track.Name..":"..tostring(track.Length)..":"..tostring(track.TimePosition))
end
return #tracks,table.concat(descriptions,",")
''')
        print('ANIMATION_STATE', report, flush=True)
        assert int(report[0]) > 0, 'No animation tracks are playing on the spawned character'
        execute('''
_G.AnimationChecks={}
local event=Instance.new("RemoteEvent",workspace)
event.Name="LocalAnimationProbe"
event.OnServerEvent:connect(function(player,phase,count,length)
 _G.AnimationChecks[phase]={count=count,length=length}
end)
local probe=Instance.new("LocalScript")
probe.Source=[=[
local player=game:GetService("Players").LocalPlayer
local h=player.Character:WaitForChild("Humanoid")
local event=workspace:WaitForChild("LocalAnimationProbe")
local tracks=h:GetPlayingAnimationTracks()
local length=0
for attempt=1,80 do
 tracks=h:GetPlayingAnimationTracks()
 for _,track in ipairs(tracks) do length=math.max(length,track.Length) end
 if length>0 then break end
 wait(0.1)
end
event:FireServer("idle",#tracks,length)
for _,clip in ipairs({{"walk","180426354"},{"jump","125750702"}}) do
 local animation=Instance.new("Animation")
 animation.AnimationId="http://localhost./asset/?id="..clip[2]
 local track=h:LoadAnimation(animation)
 track:Play()
 for attempt=1,80 do
  if track.Length>0 then break end
  wait(0.1)
 end
 track:Play()
 wait(0.05)
 event:FireServer(clip[1],track.IsPlaying and 1 or 0,track.Length)
 track:Stop()
 animation:Destroy()
end
]=]
probe.Parent=game:GetService("Players"):GetPlayers()[1]:WaitForChild("PlayerGui")
''')
        time.sleep(27)
        clips = execute('''local result={}
for _,phase in ipairs({"idle","walk","jump"}) do
 local value=_G.AnimationChecks[phase] or {count=0,length=0}
 table.insert(result,phase..":"..value.count..":"..value.length)
end
return table.concat(result,",")''')[0]
        print('CLIENT_ANIMATIONS', clips, flush=True)
        for clip in clips.split(','):
            phase, count, length = clip.split(':')
            assert int(count) > 0 and float(length) > 0, f'{phase} animation did not load/play'
    if '--ui' in sys.argv:
        from tools.capture_client import capture
        capture(backend.clients[0].pid, patcher.ROOT / 'tools/client-verification.png')
        print('Client screenshot saved for visual verification.', flush=True)
    time.sleep(10)
    assert player_state() == state, 'Player disconnected during the stability check'
    logs = '\n'.join(path.read_text(errors='replace') for path in set(log_directory.glob('*.txt')) - logs_before)
    assert 'ROBLOX version is out of date' not in logs
    assert "Can't create default object of type Players" not in logs
    assert 'Color3.fromRGB is not yet enabled' not in logs
    assert 'Failure to Start CoreScript' not in logs
    if '--animations' in sys.argv:
        assert 'Animation failed to load' not in logs
    assert 'GameJoin%5FSuccess' in '\n'.join(messages), 'No successful game-join event'
    print('CLIENT_RUNNING', backend.clients[0].poll() is None, flush=True)
    assert backend.clients[0].poll() is None, 'Client exited during startup'
finally:
    backend.stop()
    if occupied:
        occupied.close()
app = patcher.Launcher()
app.withdraw()
app.update()
assert app.config()['web'] == 80
app.destroy()
print('PASS: signed join, connected player, spawned character, stable connection, '
      'no outdated-client/default-Players errors, cleanup and Tk GUI', flush=True)

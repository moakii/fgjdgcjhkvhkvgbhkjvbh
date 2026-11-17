-- Offline appearances and legacy R6/R15 character switching.
local Players = game:GetService("Players")
_G.LocalPlayerProfiles = {}
local function playerProfile(player)
    return player and _G.LocalPlayerProfiles[player.UserId]
        or {rig=_G.LocalRig or "Bacon Hair", rig_type=_G.LocalRigType or "R6", custom=_G.LocalCustomAvatar}
end

local function applyAppearance(character, profile)
    profile = profile or playerProfile(Players:GetPlayerFromCharacter(character))
    local head = character:WaitForChild("Head")
    local humanoid = character:WaitForChild("Humanoid")
    local isR15 = humanoid.RigType == Enum.HumanoidRigType.R15
    local rig = profile.rig
    local custom = profile.custom
    for _, item in ipairs(character:GetChildren()) do
        if item:IsA("Hat") or item:IsA("Accessory") or item:IsA("Shirt")
            or item:IsA("Pants") or item:IsA("ShirtGraphic") or item:IsA("BodyColors")
            or item:IsA("CharacterMesh") then
            item:Destroy()
        end
    end
    local skin = BrickColor.new(rig == "BillyBloxxer" and 1 or rig == "BettyBloxxer" and 208 or "Light orange")
    local colors = Instance.new("BodyColors")
    colors.HeadColor = rig == "Noob" and BrickColor.new(24) or skin
    colors.LeftArmColor = colors.HeadColor
    colors.RightArmColor = colors.HeadColor
    colors.TorsoColor = rig == "Noob" and BrickColor.new(23)
        or rig == "BillyBloxxer" and BrickColor.new(194) or rig == "BettyBloxxer" and BrickColor.new(26) or skin
    colors.LeftLegColor = rig == "Noob" and BrickColor.new(119)
        or (rig == "BillyBloxxer" or rig == "BettyBloxxer") and BrickColor.new(102) or skin
    colors.RightLegColor = colors.LeftLegColor
    if rig == "Custom" then
        assert(custom, "No custom outfit selected")
        for part, rgb in pairs(custom.colors) do
            colors[part .. "Color"] = BrickColor.new(Color3.new(rgb[1], rgb[2], rgb[3]))
        end
    end
    colors.Parent = character
    if isR15 then
        for _, part in ipairs(character:GetChildren()) do
            if part:IsA("BasePart") and part.Name ~= "HumanoidRootPart" then
                part.BrickColor = part.Name == "Head" and colors.HeadColor
                    or part.Name:find("Torso") and colors.TorsoColor
                    or (part.Name:find("Leg") or part.Name:find("Foot")) and colors.LeftLegColor
                    or colors.LeftArmColor
            end
        end
    end
    local face = head:FindFirstChild("face")
    if not face then
        face = Instance.new("Decal")
        face.Name = "face"
        face.Face = Enum.NormalId.Front
        face.Parent = head
    end
    face.Texture = "rbxasset://textures/face.png"
    if rig == "Bacon Hair" then
        local bodyParts = {Enum.BodyPart.Torso, Enum.BodyPart.LeftArm, Enum.BodyPart.RightArm,
                           Enum.BodyPart.LeftLeg, Enum.BodyPart.RightLeg}
        for _, part in ipairs(isR15 and {} or _G.ManBodyMeshes) do
            local bodyMesh = Instance.new("CharacterMesh")
            bodyMesh.Name = "ManBody" .. part.BodyPart
            bodyMesh.BodyPart = bodyParts[part.BodyPart]
            bodyMesh.MeshId = part.MeshId
            bodyMesh.BaseTextureId = part.BaseTextureId
            bodyMesh.OverlayTextureId = part.OverlayTextureId
            bodyMesh.Parent = character
        end
        local shirt = Instance.new("Shirt")
        shirt.Name = "Shirt"
        shirt.ShirtTemplate = "rbxasset://avatars/bacon-shirt.png"
        shirt.Parent = character
        local pants = Instance.new("Pants")
        pants.Name = "Pants"
        pants.PantsTemplate = "rbxasset://avatars/bacon-pants.png"
        pants.Parent = character
        local hair = Instance.new("Hat")
        hair.Name = "Pal Hair"
        hair.AttachmentPoint = CFrame.new(0, 0.25, 0.25)
        local handle = Instance.new("Part")
        handle.Name = "Handle"
        handle.Size = Vector3.new(1, 1, 1)
        handle.CanCollide = false
        handle.TopSurface = Enum.SurfaceType.Smooth
        handle.BottomSurface = Enum.SurfaceType.Smooth
        local mesh = Instance.new("SpecialMesh")
        mesh.MeshType = Enum.MeshType.FileMesh
        mesh.MeshId = "rbxasset://avatars/bacon-hair.mesh"
        mesh.TextureId = "rbxasset://avatars/bacon-hair.png"
        mesh.Scale = Vector3.new(1, 1.1, 1)
        mesh.Parent = handle
        handle.CFrame = head.CFrame * CFrame.new(0, 0.5, 0) * hair.AttachmentPoint:inverse()
        handle.Parent = hair
        hair.Parent = character
        local weld = handle:FindFirstChild("HeadWeld")
        if not weld then
            weld = Instance.new("Weld")
            weld.Name = "HeadWeld"
            weld.Part0 = head
            weld.Part1 = handle
            weld.C0 = CFrame.new(0, 0.5, 0)
            weld.C1 = hair.AttachmentPoint
            weld.Parent = handle
        end
    elseif rig == "Custom" then
        local bodyParts = {Enum.BodyPart.Torso, Enum.BodyPart.LeftArm, Enum.BodyPart.RightArm,
                           Enum.BodyPart.LeftLeg, Enum.BodyPart.RightLeg}
        for _, part in ipairs(custom.body_meshes or {}) do
            local mesh = Instance.new("CharacterMesh")
            mesh.Name = "CustomBody" .. part.BodyPart
            mesh.BodyPart = bodyParts[part.BodyPart]
            mesh.MeshId = part.MeshId
            mesh.BaseTextureId = part.BaseTextureId
            mesh.OverlayTextureId = part.OverlayTextureId
            mesh.Parent = character
        end
        if custom.shirt then
            local shirt = Instance.new("Shirt", character)
            shirt.Name = "Shirt"
            shirt.ShirtTemplate = "rbxasset://wardrobe/" .. custom.shirt
        end
        if custom.pants then
            local pants = Instance.new("Pants", character)
            pants.Name = "Pants"
            pants.PantsTemplate = "rbxasset://wardrobe/" .. custom.pants
        end
        for _, file in ipairs(custom.hats) do
            local hat = game:GetObjects("rbxasset://wardrobe/" .. file)[1]
            local handle = hat:FindFirstChild("Handle")
            handle.CanCollide = false
            handle.CFrame = head.CFrame * CFrame.new(0, 0.5, 0) * hat.AttachmentPoint:inverse()
            hat.Parent = character
            local weld = handle:FindFirstChild("HeadWeld") or Instance.new("Weld", handle)
            weld.Name, weld.Part0, weld.Part1 = "HeadWeld", head, handle
            weld.C0, weld.C1 = CFrame.new(0, 0.5, 0), hat.AttachmentPoint
        end
    elseif rig == "BillyBloxxer" or rig == "BettyBloxxer" then
        if not isR15 then
            local bodyParts = {Enum.BodyPart.Torso, Enum.BodyPart.LeftArm, Enum.BodyPart.RightArm,
                               Enum.BodyPart.LeftLeg, Enum.BodyPart.RightLeg}
            for _, part in ipairs(_G.Robloxian2BodyMeshes) do
                local mesh = Instance.new("CharacterMesh")
                mesh.Name = "Robloxian2Body" .. part.BodyPart
                mesh.BodyPart = bodyParts[part.BodyPart]
                mesh.MeshId = part.MeshId
                mesh.Parent = character
            end
        end
        local shirt = Instance.new("Shirt", character)
        shirt.Name = "Shirt"
        shirt.ShirtTemplate = "rbxasset://avatars/guest-shirt.png"
        local pants = Instance.new("Pants", character)
        pants.Name = "Pants"
        pants.PantsTemplate = "rbxasset://avatars/guest-pants.png"
        local file = rig == "BillyBloxxer" and "billy-hair.rbxm" or "betty-hair.rbxm"
        local hair = game:GetObjects("rbxasset://avatars/" .. file)[1]
        hair.Name = rig == "BillyBloxxer" and "True Blue Hair" or "Lavender Updo"
        local handle = hair:FindFirstChild("Handle")
        handle.CanCollide = false
        handle.CFrame = head.CFrame * CFrame.new(0, 0.5, 0) * hair.AttachmentPoint:inverse()
        hair.Parent = character
        local weld = handle:FindFirstChild("HeadWeld") or Instance.new("Weld", handle)
        weld.Name, weld.Part0, weld.Part1 = "HeadWeld", head, handle
        weld.C0, weld.C1 = CFrame.new(0, 0.5, 0), hair.AttachmentPoint
    end
end

_G.ApplyLocalAppearance = applyAppearance
local joints = {
    {"HumanoidRootPart","LowerTorso","Root"}, {"LowerTorso","UpperTorso","Waist"},
    {"UpperTorso","Head","Neck"}, {"UpperTorso","LeftUpperArm","LeftShoulder"},
    {"LeftUpperArm","LeftLowerArm","LeftElbow"}, {"LeftLowerArm","LeftHand","LeftWrist"},
    {"UpperTorso","RightUpperArm","RightShoulder"}, {"RightUpperArm","RightLowerArm","RightElbow"},
    {"RightLowerArm","RightHand","RightWrist"}, {"LowerTorso","LeftUpperLeg","LeftHip"},
    {"LeftUpperLeg","LeftLowerLeg","LeftKnee"}, {"LeftLowerLeg","LeftFoot","LeftAnkle"},
    {"LowerTorso","RightUpperLeg","RightHip"}, {"RightUpperLeg","RightLowerLeg","RightKnee"},
    {"RightLowerLeg","RightFoot","RightAnkle"}
}

_G.PrepareLocalCharacter = function(player, character)
    if player.Character ~= character then return end
    local profile = playerProfile(player)
    if profile.rig_type == "R15" and not character:FindFirstChild("LocalR15Character") then
        local file = profile.rig == "Bacon Hair" and "avatars/man-r15.rbxm"
            or profile.rig == "Noob" and "avatars/noob-r15.rbxm" or "avatars/robloxian2-r15.rbxm"
        local replacement = game:GetObjects("rbxasset://" .. file)[1]
        Instance.new("BoolValue", character).Name = "LocalR15Character"
        -- Preserve the engine-owned character, humanoid and root. Replacing the
        -- Character property directly loses client ownership in this RCC build.
        local root = character:FindFirstChild("HumanoidRootPart")
        for _, child in ipairs(character:GetChildren()) do
            if (child:IsA("BasePart") and child ~= root) or child.Name == "Animate" then child:Destroy() end
        end
        for _, child in ipairs(root:GetChildren()) do
            if child:IsA("JointInstance") then child:Destroy() end
        end
        for _, child in ipairs(replacement:GetChildren()) do
            if child:IsA("BasePart") and child.Name ~= "HumanoidRootPart" then child.Parent = character end
        end
        local rootAttachment = replacement.HumanoidRootPart:FindFirstChild("RootRigAttachment")
        if root:FindFirstChild("RootRigAttachment") then root.RootRigAttachment:Destroy() end
        rootAttachment:Clone().Parent = root
        character.Humanoid.RigType = Enum.HumanoidRigType.R15
        character.Humanoid.HipHeight = replacement.Humanoid.HipHeight
        for _, link in ipairs(joints) do
            local a, b = character[link[1]], character[link[2]]
            local attachment = link[3] .. "RigAttachment"
            local motor = Instance.new("Motor6D")
            motor.Name, motor.Part0, motor.Part1 = link[3], a, b
            motor.C0, motor.C1 = a[attachment].CFrame, b[attachment].CFrame
            b.CFrame = a.CFrame * motor.C0 * motor.C1:inverse()
            motor.Parent = b
        end
        local animate = game:GetObjects("rbxasset://fonts/humanoidAnimateR15_3.rbxm")[1]
        animate.Name = "Animate"
        animate.Source = 'script.Parent:WaitForChild("Humanoid").RigType = Enum.HumanoidRigType.R15\n' .. animate.Source
        animate.Parent = character
        replacement:Destroy()
    end
    applyAppearance(character, profile)
end

_G.SetLocalPlayerProfile = function(userId, profile)
    local rig, rigType = profile.rig, profile.rig_type
    assert(rig == "Bacon Hair" or rig == "Noob" or rig == "BillyBloxxer" or rig == "BettyBloxxer" or rig == "Custom", "Unknown appearance")
    assert(rigType == "R6" or rigType == "R15", "Unknown rig type")
    local previous = _G.LocalPlayerProfiles[userId] or {rig=_G.LocalRig, rig_type=_G.LocalRigType}
    local respawn = rigType ~= previous.rig_type or (rigType == "R15" and rig ~= previous.rig)
    _G.LocalPlayerProfiles[userId] = profile
    for _, player in ipairs(Players:GetPlayers()) do
        if player.UserId == userId and player.Character then
            if respawn then player:LoadCharacter() else applyAppearance(player.Character, profile) end
        end
    end
end

_G.SetLocalRig = function(rig, rigType)
    rigType = rigType or _G.LocalRigType or "R6"
    _G.SetLocalPlayerProfile(1, {rig=rig, rig_type=rigType, custom=_G.LocalCustomAvatar})
    _G.LocalRig, _G.LocalRigType = rig, rigType
end

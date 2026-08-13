import json
import math
import queue
import socket
import threading
import time

import unreal


HOST = "127.0.0.1"
PORT = 8765

STATE_QUEUE = queue.Queue()
AVATAR = {
    "state": "idle",
    "emotion": "neutral",
    "phase": 0.0,
    "actors": [],
    "named": {},
    "materials": {},
    "tick": None,
    "speech_text": "",
    "speech_started": 0.0,
    "speech_duration": 1.2,
    "last_blink": 0.0,
}


def log(message):
    unreal.log("[Teraps Unreal] " + str(message))


def asset(path):
    return unreal.load_asset(path)


def make_material(name, color, opacity=0.55, metallic=0.0, roughness=0.08):
    package = f"/Game/Teraps/Materials/{name}"
    if unreal.EditorAssetLibrary.does_asset_exist(package):
        return unreal.load_asset(package)
    mat = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name,
        "/Game/Teraps/Materials",
        unreal.Material,
        unreal.MaterialFactoryNew(),
    )
    mat.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    mat.set_editor_property("shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    mat.set_editor_property("two_sided", True)
    mat.set_editor_property("use_emissive_for_dynamic_area_lighting", True)
    unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionParticleColor, -420, -120)
    emissive = unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionVectorParameter, -240, -140)
    emissive.set_editor_property("parameter_name", "GlowColor")
    emissive.set_editor_property("default_value", color)
    opacity_expr = unreal.MaterialEditingLibrary.create_material_expression(mat, unreal.MaterialExpressionScalarParameter, -240, 40)
    opacity_expr.set_editor_property("parameter_name", "Opacity")
    opacity_expr.set_editor_property("default_value", opacity)
    unreal.MaterialEditingLibrary.connect_material_property(emissive, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    unreal.MaterialEditingLibrary.connect_material_property(opacity_expr, "", unreal.MaterialProperty.MP_OPACITY)
    unreal.MaterialEditingLibrary.layout_material_expressions(mat)
    unreal.EditorAssetLibrary.save_asset(package, only_if_is_dirty=False)
    return mat


def spawn_mesh(name, mesh_path, location, scale, material):
    mesh = asset(mesh_path)
    actor = unreal.EditorLevelLibrary.spawn_actor_from_object(mesh, unreal.Vector(*location), unreal.Rotator(0, 0, 0))
    actor.set_actor_label(name)
    actor.set_actor_scale3d(unreal.Vector(*scale))
    comp = actor.static_mesh_component
    comp.set_material(0, material)
    comp.set_editor_property("cast_shadow", False)
    AVATAR["actors"].append(actor)
    AVATAR["named"][name] = actor
    return actor


def ensure_folders():
    for folder in ["/Game/Teraps", "/Game/Teraps/Materials", "/Game/Teraps/Maps"]:
        if not unreal.EditorAssetLibrary.does_directory_exist(folder):
            unreal.EditorAssetLibrary.make_directory(folder)


def clear_scene():
    actors = unreal.EditorLevelLibrary.get_all_level_actors()
    for actor in actors:
        if actor.get_actor_label().startswith("TERAPS_"):
            unreal.EditorLevelLibrary.destroy_actor(actor)
    AVATAR["actors"] = []
    AVATAR["named"] = {}


def build_scene():
    ensure_folders()
    world = unreal.EditorLevelLibrary.get_editor_world()
    clear_scene()

    cyan = unreal.LinearColor(0.05, 0.95, 1.0, 1.0)
    pale = unreal.LinearColor(0.65, 1.0, 1.0, 1.0)
    champagne = unreal.LinearColor(1.0, 0.78, 0.42, 1.0)
    skin = unreal.LinearColor(0.28, 0.92, 1.0, 1.0)
    iris = unreal.LinearColor(0.1, 0.8, 1.0, 1.0)
    mouth_color = unreal.LinearColor(1.0, 0.18, 0.72, 1.0)

    AVATAR["materials"]["body"] = make_material("M_Teraps_Body", skin, 0.42)
    AVATAR["materials"]["glow"] = make_material("M_Teraps_CyanGlow", cyan, 0.72)
    AVATAR["materials"]["pale"] = make_material("M_Teraps_PaleFace", pale, 0.48)
    AVATAR["materials"]["gold"] = make_material("M_Teraps_Champagne", champagne, 0.62)
    AVATAR["materials"]["iris"] = make_material("M_Teraps_Iris", iris, 0.88)
    AVATAR["materials"]["mouth"] = make_material("M_Teraps_Mouth", mouth_color, 0.86)

    # Camera and lights.
    camera = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.CineCameraActor,
        unreal.Vector(-560, 0, 185),
        unreal.Rotator(0, 0, 0),
    )
    camera.set_actor_label("TERAPS_Camera")
    camera.set_actor_rotation(unreal.Rotator(-4, 0, 0), False)
    unreal.EditorLevelLibrary.get_level_viewport_camera_info()

    light = unreal.EditorLevelLibrary.spawn_actor_from_class(
        unreal.PointLight,
        unreal.Vector(-120, 0, 280),
        unreal.Rotator(0, 0, 0),
    )
    light.set_actor_label("TERAPS_Cyan_KeyLight")
    light.light_component.set_editor_property("intensity", 6500.0)
    light.light_component.set_editor_property("light_color", unreal.Color(88, 240, 255, 255))

    # Stylized holographic female avatar made from native meshes.
    body = AVATAR["materials"]["body"]
    glow = AVATAR["materials"]["glow"]
    pale = AVATAR["materials"]["pale"]
    gold = AVATAR["materials"]["gold"]
    iris_mat = AVATAR["materials"]["iris"]
    mouth_mat = AVATAR["materials"]["mouth"]
    sphere = "/Engine/BasicShapes/Sphere.Sphere"
    cube = "/Engine/BasicShapes/Cube.Cube"
    cone = "/Engine/BasicShapes/Cone.Cone"
    cylinder = "/Engine/BasicShapes/Cylinder.Cylinder"

    spawn_mesh("TERAPS_Torso", sphere, (0, 0, 135), (0.58, 0.26, 0.92), body)
    spawn_mesh("TERAPS_Head", sphere, (0, 0, 245), (0.34, 0.28, 0.38), pale)
    spawn_mesh("TERAPS_LeftEye", sphere, (-12, -25, 252), (0.045, 0.018, 0.027), iris_mat)
    spawn_mesh("TERAPS_RightEye", sphere, (12, -25, 252), (0.045, 0.018, 0.027), iris_mat)
    spawn_mesh("TERAPS_LeftPupil", sphere, (-12, -28, 252), (0.018, 0.008, 0.018), glow)
    spawn_mesh("TERAPS_RightPupil", sphere, (12, -28, 252), (0.018, 0.008, 0.018), glow)
    spawn_mesh("TERAPS_Mouth", sphere, (0, -28, 231), (0.085, 0.012, 0.018), mouth_mat)
    spawn_mesh("TERAPS_Neck", cylinder, (0, 0, 200), (0.13, 0.13, 0.35), body)
    spawn_mesh("TERAPS_HairHalo", sphere, (5, 0, 257), (0.42, 0.32, 0.45), glow)
    spawn_mesh("TERAPS_LeftArm", cylinder, (-47, 0, 152), (0.08, 0.08, 0.88), glow).set_actor_rotation(unreal.Rotator(18, -8, 22), False)
    spawn_mesh("TERAPS_RightArm", cylinder, (52, 0, 176), (0.08, 0.08, 0.98), glow).set_actor_rotation(unreal.Rotator(-44, -12, -44), False)
    spawn_mesh("TERAPS_LeftHand", sphere, (-76, -4, 108), (0.12, 0.08, 0.12), pale)
    spawn_mesh("TERAPS_RightHand", sphere, (88, -8, 212), (0.15, 0.09, 0.15), pale)
    spawn_mesh("TERAPS_Hips", sphere, (0, 0, 76), (0.42, 0.24, 0.32), body)
    spawn_mesh("TERAPS_LeftLeg", cylinder, (-24, 0, 22), (0.08, 0.08, 0.92), glow).set_actor_rotation(unreal.Rotator(4, 0, -6), False)
    spawn_mesh("TERAPS_RightLeg", cylinder, (24, 0, 22), (0.08, 0.08, 0.92), glow).set_actor_rotation(unreal.Rotator(4, 0, 6), False)
    spawn_mesh("TERAPS_LeftFoot", sphere, (-31, -8, -40), (0.18, 0.09, 0.06), gold)
    spawn_mesh("TERAPS_RightFoot", sphere, (31, -8, -40), (0.18, 0.09, 0.06), gold)

    for i in range(3):
        ring = spawn_mesh(f"TERAPS_Orbit_{i}", cylinder, (0, 0, 96 + i * 34), (1.45 + i * 0.18, 1.45 + i * 0.18, 0.006), glow)
        ring.set_actor_rotation(unreal.Rotator(90, i * 31, 0), False)

    panel = spawn_mesh("TERAPS_AirPanel", cube, (118, -20, 220), (0.72, 0.025, 0.42), glow)
    panel.set_actor_rotation(unreal.Rotator(0, 0, 0), False)

    for i in range(18):
        angle = math.tau * i / 18
        radius = 120 + (i % 3) * 24
        z = 30 + (i * 17) % 230
        spawn_mesh(
            f"TERAPS_Particle_{i}",
            sphere,
            (math.cos(angle) * radius, math.sin(angle) * radius, z),
            (0.025, 0.025, 0.025),
            gold if i % 4 == 0 else glow,
        )

    log("Cena holografica 3D criada.")


def apply_state(payload):
    data = payload.get("data", payload)
    AVATAR["state"] = data.get("state", "idle")
    AVATAR["emotion"] = data.get("emotion", "neutral")
    metadata = data.get("metadata") or {}
    if AVATAR["state"] == "speaking":
        AVATAR["speech_text"] = str(metadata.get("text") or "")
        AVATAR["speech_started"] = time.time()
        AVATAR["speech_duration"] = max(0.8, float(metadata.get("duration_ms") or 1200) / 1000.0)
    log(f"Estado recebido: {AVATAR['state']} / {AVATAR['emotion']}")


def speech_energy():
    text = AVATAR.get("speech_text") or ""
    if AVATAR["state"] != "speaking":
        return 0.04
    elapsed = max(0.0, time.time() - float(AVATAR.get("speech_started") or time.time()))
    duration = max(0.8, float(AVATAR.get("speech_duration") or 1.2))
    if elapsed > duration:
        return 0.04
    if not text:
        return 0.45 + abs(math.sin(AVATAR["phase"] * 8.0)) * 0.32
    idx = min(len(text) - 1, int((elapsed / duration) * len(text)))
    char = text[idx].lower()
    if char in ".,;:!? ":
        weight = 0.08
    elif char in "aeiouáàâãéêíóôõú":
        weight = 0.92
    elif char in "bmp":
        weight = 0.18
    elif char in "fvszx":
        weight = 0.38
    else:
        weight = 0.58
    wave = abs(math.sin(AVATAR["phase"] * 9.2 + idx * 0.37)) * 0.28
    return max(0.04, min(1.0, weight * 0.72 + wave))


def apply_face_animation(phase, state):
    mouth = AVATAR["named"].get("TERAPS_Mouth")
    left_eye = AVATAR["named"].get("TERAPS_LeftEye")
    right_eye = AVATAR["named"].get("TERAPS_RightEye")
    left_pupil = AVATAR["named"].get("TERAPS_LeftPupil")
    right_pupil = AVATAR["named"].get("TERAPS_RightPupil")
    head = AVATAR["named"].get("TERAPS_Head")
    hair = AVATAR["named"].get("TERAPS_HairHalo")

    energy = speech_energy()
    blink = 1.0
    blink_wave = math.sin(phase * 2.35)
    if blink_wave > 0.985:
        blink = 0.12

    if mouth:
        loc = unreal.Vector(0, -28.5, 231)
        mouth.set_actor_location(loc, False, False)
        if state == "speaking":
            mouth.set_actor_scale3d(unreal.Vector(0.075 + energy * 0.045, 0.012, 0.012 + energy * 0.058))
        else:
            mouth.set_actor_scale3d(unreal.Vector(0.085, 0.012, 0.016))

    eye_z = 252
    pupil_offset = math.sin(phase * 0.75) * 1.2
    for eye, x in [(left_eye, -12), (right_eye, 12)]:
        if eye:
            eye.set_actor_location(unreal.Vector(x, -25, eye_z), False, False)
            eye.set_actor_scale3d(unreal.Vector(0.045, 0.018, 0.027 * blink))
    for pupil, x in [(left_pupil, -12), (right_pupil, 12)]:
        if pupil:
            pupil.set_actor_location(unreal.Vector(x + pupil_offset, -28.5, eye_z), False, False)
            pupil.set_actor_scale3d(unreal.Vector(0.018, 0.008, 0.018 * blink))

    if head:
        yaw = math.sin(phase * 0.55) * 2.0
        pitch = -2.8 if state == "listening" else math.sin(phase * 0.42) * 1.2
        if state == "thinking":
            yaw += math.sin(phase * 1.2) * 1.8
        head.set_actor_rotation(unreal.Rotator(pitch, yaw, 0), False)
    if hair:
        hair.set_actor_rotation(unreal.Rotator(math.sin(phase * 0.65) * 1.8, math.sin(phase * 0.4) * 2.5, 0), False)


def update_scene(delta_seconds):
    AVATAR["phase"] += float(delta_seconds or 0.016)
    phase = AVATAR["phase"]
    state = AVATAR["state"]
    intensity = 1.0
    if state == "speaking":
        intensity = 1.24 + math.sin(phase * 8.0) * 0.12
    elif state == "thinking":
        intensity = 1.4 + math.sin(phase * 5.0) * 0.18
    elif state == "listening":
        intensity = 1.18 + math.sin(phase * 3.0) * 0.08

    for actor in AVATAR["actors"]:
        label = actor.get_actor_label()
        loc = actor.get_actor_location()
        if label.startswith("TERAPS_Particle"):
            angle = phase * 0.55 + hash(label) % 100
            loc.x += math.sin(angle) * 0.08
            loc.z += math.sin(phase * 1.8 + hash(label) % 17) * 0.03
            actor.set_actor_location(loc, False, False)
        elif label.startswith("TERAPS_Orbit"):
            rot = actor.get_actor_rotation()
            rot.yaw += 8.0 * delta_seconds * intensity
            actor.set_actor_rotation(rot, False)
        elif label == "TERAPS_RightHand" and state in ("speaking", "thinking"):
            base_z = 212
            loc.z = base_z + math.sin(phase * 4.4) * 8.0
            loc.x = 88 + math.sin(phase * 2.0) * 3.0
            actor.set_actor_location(loc, False, False)
        elif label == "TERAPS_AirPanel":
            if state in ("thinking", "speaking"):
                actor.set_actor_scale3d(unreal.Vector(0.72, 0.025, 0.42 + math.sin(phase * 3.0) * 0.02))
            else:
                actor.set_actor_scale3d(unreal.Vector(0.56, 0.018, 0.28))
        elif label == "TERAPS_Torso":
            loc.z = 135 + math.sin(phase * 1.2) * 1.7
            actor.set_actor_location(loc, False, False)

    apply_face_animation(phase, state)


def start_server():
    def worker():
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(5)
        log(f"Ponte TCP ativa em {HOST}:{PORT}")
        while True:
            client, _addr = server.accept()
            with client:
                raw = client.recv(8192)
                if not raw:
                    continue
                try:
                    payload = json.loads(raw.decode("utf-8", errors="ignore"))
                    STATE_QUEUE.put(payload)
                except Exception as exc:
                    log(f"Payload invalido: {exc}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def tick(delta_seconds):
    while not STATE_QUEUE.empty():
        apply_state(STATE_QUEUE.get_nowait())
    update_scene(delta_seconds)
    return True


def main():
    build_scene()
    start_server()
    if AVATAR["tick"] is None:
        AVATAR["tick"] = unreal.register_slate_post_tick_callback(tick)
    log("Renderizador Unreal do Teraps pronto.")


main()

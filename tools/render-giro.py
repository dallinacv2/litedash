#!/usr/bin/env python3
"""Renderiza el giro de un auto (cuadros PNG con fondo transparente, proporción 1.9:1).

Sirve con el módulo `bpy` (pip install bpy) o con Blender sin interfaz:
  python render-giro.py auto.blend salida/ [--cuadros 48] [--muestras 48] [--solo N]
  blender -b auto.blend -P render-giro.py -- auto.blend salida/ --solo 0

Los cuadros salen como salida/00.png … 47.png; después se empaquetan con
  tools/armar-paquete.py paquete --cuadros salida/ --id … --url-base …

Se oculta el objeto del piso (nombre con "piso"/"floor"/"ground") y se gira el auto
sobre su centro con la cámara fija. El cuadro 00 deja el frente a 3/4 (35° del
costado). Ojo: se parte de que los faros ("faro"/"headlight"/"light") están
en el frente del auto; si el auto no los tiene, se usa el eje X positivo.
"""
import argparse
import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Vector

ASPECT = 1.9
SIN_PISO = ("piso", "floor", "ground", "suelo", "asfalto")
FAROS = ("faro", "headlight", "head_light", "light_front")


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("blend")
    p.add_argument("salida")
    p.add_argument("--cuadros", type=int, default=48)
    p.add_argument("--ancho", type=int, default=1140)
    p.add_argument("--muestras", type=int, default=48)
    p.add_argument("--elevacion", type=float, default=12.0, help="grados sobre el horizonte")
    p.add_argument("--solo", type=int, help="renderiza solo ese cuadro (prueba)")
    return p.parse_args(argv)


def world_bbox(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def main():
    a = args()
    bpy.context.preferences.filepaths.use_scripts_auto_execute = False  # no correr scripts del archivo
    bpy.ops.wm.open_mainfile(filepath=a.blend, load_ui=False)
    sc = bpy.context.scene

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    piso = [o for o in meshes if any(k in o.name.lower() for k in SIN_PISO)]
    auto = [o for o in meshes if o not in piso]
    for o in piso:
        o.hide_render = True
        o.hide_viewport = True
    lo, hi = world_bbox(auto)
    centro = (lo + hi) / 2

    # Hacia dónde mira el auto: de su centro a sus faros (si no, +X).
    faros = [o for o in auto if any(k in o.name.lower() for k in FAROS)]
    if faros:
        f = sum((o.matrix_world.translation for o in faros), Vector()) / len(faros) - centro
    else:
        f = Vector((1, 0, 0))
    ang_frente = math.atan2(f.y, f.x)
    giro0 = math.radians(-90 + 35) - ang_frente  # frente a 3/4 hacia la cámara en el cuadro 00

    # El auto cuelga de un vacío en su centro: girar el vacío gira todo.
    pivote = bpy.data.objects.new("pivote_giro", None)
    sc.collection.objects.link(pivote)
    pivote.location = centro
    bpy.context.view_layer.update()
    for o in auto:
        if o.parent is None:
            o.parent = pivote
            o.matrix_parent_inverse = pivote.matrix_world.inverted()

    # Cámara fija, perspectiva suave, a distancia para que el auto quepa en cualquier ángulo.
    ancho_m = math.hypot(hi.x - lo.x, hi.y - lo.y) * 1.08
    cam_data = bpy.data.cameras.new("cam_giro")
    cam_data.lens, cam_data.sensor_width = 50, 36
    fov = 2 * math.atan(18 / 50)
    dist = (ancho_m / 2) / math.tan(fov / 2)
    el = math.radians(a.elevacion)
    cam = bpy.data.objects.new("cam_giro", cam_data)
    sc.collection.objects.link(cam)
    cam.location = centro + Vector((0, -dist * math.cos(el), dist * math.sin(el)))
    mira = (centro - cam.location).to_track_quat("-Z", "Y")
    cam.rotation_euler = mira.to_euler()
    sc.camera = cam

    alto = round(a.ancho / ASPECT)
    r = sc.render
    r.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = a.muestras
    sc.cycles.use_denoising = True
    r.resolution_x, r.resolution_y, r.resolution_percentage = a.ancho, alto, 100
    r.film_transparent = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGBA"

    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)
    indices = [a.solo] if a.solo is not None else range(a.cuadros)
    for i in indices:
        pivote.rotation_euler = Euler((0, 0, giro0 + i * 2 * math.pi / a.cuadros))
        r.filepath = str(out / f"{i:02d}.png")
        bpy.ops.render.render(write_still=True)
        print(f"cuadro {i:02d}/{a.cuadros} -> {r.filepath}", flush=True)


main()

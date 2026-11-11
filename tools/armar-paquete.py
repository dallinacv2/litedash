#!/usr/bin/env python3
"""Arma un paquete de auto para LiteDash (para la copia personal) y su catalogo.json.

Un paquete es un .zip con `auto.json` y la carpeta `giro/` con los cuadros 00.webp, 01.webp…
(el auto girando, con fondo transparente, en proporción 1.9:1). Las capas opcionales
(-pintura, -sombra, -reflejo, planta, wheels…) no hacen falta: sin "-pintura" el auto se
ve tal cual, sin teñirse con el color elegido.

Uso:
  # 1) Quitar el fondo liso de una captura (Blender, estudio) → PNG transparente 1.9:1
  tools/armar-paquete.py recortar captura.png recorte.png

  # 2a) Prueba estática: un solo recorte repetido en los N cuadros (no gira)
  tools/armar-paquete.py paquete --estatico recorte.png --id hyundai-sonata-2012 \
      --nombre "Sonata" --marca Hyundai --anio 2012 --salida salida/ --url-base URL/

  # 2b) Giro real: carpeta con cuadros 00.png…47.png (p. ej. de tools/render-giro.py)
  tools/armar-paquete.py paquete --cuadros carpeta/ --id ... (igual que arriba)

Deja en --salida: <id>.zip, <id>.webp (miniatura) y catalogo.json. Con --mezclar URL se
suman al catálogo las entradas de otro catalogo.json (el del proyecto original) para no
perder sus autos; con --mezclar se vuelve a correr cuando el original agregue autos.
"""
import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

ASPECT = 1.9          # CAR_ASPECT de la app
FRAME_W = 1140        # ancho de cada cuadro
FRAME_H = round(FRAME_W / ASPECT)
THUMB_W = 480
FRAMES = 48           # el giro de la app: 48 cuadros


def recortar(src: Path, dst: Path, tol: int = 16) -> None:
    """Quita el fondo liso que toca los bordes y centra el auto en un cuadro de 1.9:1."""
    im = Image.open(src).convert("RGB")
    a = np.asarray(im).astype(int)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    bg = np.median(border, axis=0)
    like_bg = np.abs(a - bg).max(axis=2) <= tol
    labels, _ = ndimage.label(like_bg)
    edge_labels = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))) - {0}
    background = np.isin(labels, list(edge_labels))
    car = ndimage.binary_fill_holes(~background)
    car = ndimage.binary_opening(car, iterations=2)
    car = ndimage.binary_erosion(car, iterations=1)  # quita el halo del fondo en el borde
    alpha = Image.fromarray((car * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.9))
    rgba = im.convert("RGBA")
    rgba.putalpha(alpha)
    box = rgba.getbbox()
    if box is None:
        sys.exit("No encontré el auto: revisa que el fondo sea liso.")
    rgba = rgba.crop(box)
    # Cabe en el cuadro 1.9:1 con un margen, centrado.
    inner_w, inner_h = FRAME_W * 0.94, FRAME_H * 0.90
    scale = min(inner_w / rgba.width, inner_h / rgba.height)
    rgba = rgba.resize((round(rgba.width * scale), round(rgba.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGBA", (FRAME_W, FRAME_H), (0, 0, 0, 0))
    canvas.paste(rgba, ((FRAME_W - rgba.width) // 2, (FRAME_H - rgba.height) // 2), rgba)
    canvas.save(dst)
    print(f"{dst}: {canvas.size[0]}x{canvas.size[1]}")


def webp_bytes(im: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=6)
    return buf.getvalue()


def paquete(a: argparse.Namespace) -> None:
    out = Path(a.salida)
    out.mkdir(parents=True, exist_ok=True)
    if a.estatico:
        base = Image.open(a.estatico).convert("RGBA")
        frames = [base] * FRAMES
    else:
        files = sorted(Path(a.cuadros).glob("*.png")) or sorted(Path(a.cuadros).glob("*.webp"))
        if len(files) < 2:
            sys.exit("Faltan cuadros: carpeta con 00.png, 01.png…")
        frames = [Image.open(f).convert("RGBA") for f in files]
    n = len(frames)

    info = {"id": a.id, "nombre": a.nombre, "marca": a.marca, "anio": a.anio,
            "autor": a.autor, "licencia": a.licencia, "fuente": a.fuente, "giro": n}
    zpath = out / f"{a.id}.zip"
    cache: dict[int, bytes] = {}
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:  # .webp ya viene comprimido
        z.writestr("auto.json", json.dumps(info, ensure_ascii=False, indent=2))
        for i, fr in enumerate(frames):
            key = id(fr)
            if key not in cache:
                cache[key] = webp_bytes(fr)
            z.writestr(f"giro/{i:02d}.webp", cache[key])

    thumb = frames[0].resize((THUMB_W, round(THUMB_W * frames[0].height / frames[0].width)), Image.LANCZOS)
    (out / f"{a.id}.webp").write_bytes(webp_bytes(thumb, 80))

    data = zpath.read_bytes()
    entry = {**{k: info[k] for k in ("id", "nombre", "marca", "anio", "autor", "licencia")},
             "url": f"{a.url_base}{a.id}.zip", "bytes": len(data),
             "sha256": hashlib.sha256(data).hexdigest(),
             "miniatura": f"{a.url_base}{a.id}.webp"}
    autos = [entry]
    if a.mezclar:
        with urllib.request.urlopen(a.mezclar, timeout=60) as r:
            autos += [c for c in json.load(r)["autos"] if c.get("id") != a.id]
    (out / "catalogo.json").write_text(json.dumps({"autos": autos}, ensure_ascii=False, indent=2))
    print(f"{zpath}: {len(data) / 1e6:.1f} MB, {n} cuadros; catalogo.json con {len(autos)} auto(s)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("recortar")
    r.add_argument("origen", type=Path)
    r.add_argument("destino", type=Path)
    r.add_argument("--tolerancia", type=int, default=16)
    k = s.add_parser("paquete")
    g = k.add_mutually_exclusive_group(required=True)
    g.add_argument("--estatico", type=Path)
    g.add_argument("--cuadros", type=Path)
    k.add_argument("--id", required=True)
    k.add_argument("--nombre", required=True)
    k.add_argument("--marca", required=True)
    k.add_argument("--anio", type=int, required=True)
    k.add_argument("--autor", default="Personal")
    k.add_argument("--licencia", default="Uso personal")
    k.add_argument("--fuente", default="")
    k.add_argument("--salida", default="salida")
    k.add_argument("--url-base", required=True, help="URL (con / al final) donde se publican el zip y la miniatura")
    k.add_argument("--mezclar", help="URL de otro catalogo.json cuyos autos se suman")
    a = p.parse_args()
    if a.cmd == "recortar":
        recortar(a.origen, a.destino, a.tolerancia)
    else:
        paquete(a)


if __name__ == "__main__":
    main()

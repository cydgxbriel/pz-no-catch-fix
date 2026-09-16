#!/usr/bin/env python3
"""
Gera as imagens do mod:

  preview.png  1280x720  vitrine da pagina na Oficina Steam (a vitrine e
                         larga; imagem quadrada fica com tarja preta e
                         encolhida no meio)
  poster.png    512x512  imagem grande na lista de mods do jogo (quadrada)
  icon.png       64x64   icone pequeno na lista de mods do jogo

Uso:  .venv/bin/python tools/make_images.py
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
import paths

WORKSHOP = paths.workshop_stage()

BG_TOP = (18, 26, 33)
BG_BOT = (10, 15, 20)
WATER = (34, 74, 88)
WATER_HI = (58, 120, 138)
LINE = (208, 214, 218)
ACCENT = (226, 168, 74)
TEXT = (238, 241, 243)
MUTED = (132, 148, 158)
BOBBER_RED = (214, 74, 62)

FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

MARGIN = 44          # poster: mesma folga na esquerda e na direita
MARGIN_PREVIEW = 92  # preview


def fit_font(d, text, path, size, max_width):
    """Maior corpo ate `size` que cabe em max_width.

    As legendas ja vazaram pela direita do poster por ficarem em corpo
    fixo; aqui elas encolhem em vez de escapar da margem.
    """
    while size > 8 and d.textlength(text, font=ImageFont.truetype(path, size)) > max_width:
        size -= 1
    return ImageFont.truetype(path, size)


def fit_block(d, lines, path, size, max_width):
    """Um unico corpo para o bloco: linhas vizinhas em corpos diferentes
    denunciam o ajuste automatico."""
    return min((fit_font(d, line, path, size, max_width) for line in lines),
               key=lambda f: f.size)


def write(d, xy, text, font, fill, edges):
    """Escreve anotando a borda direita, para a checagem de margem."""
    d.text(xy, text, font=font, fill=fill)
    edges.append((text, xy[0] + d.textlength(text, font=font)))


def write_spaced(d, xy, text, font, fill, extra, edges):
    """PIL nao tem letter-spacing; desenha caractere a caractere.

    O y e o meio da linha (anchor lm), para alinhar com o selo ao lado.
    """
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=font, fill=fill, anchor="lm")
        x += d.textlength(ch, font=font) + extra
    edges.append((text, x - extra))


def check_margins(name, edges, limit):
    """Quebra o build em vez de deixar publicar arte com texto cortado."""
    over = [(t, round(r)) for t, r in edges if r > limit]
    if over:
        raise SystemExit(f"{name}: texto passa da margem (limite {limit}px): "
                         + "; ".join(f"{t!r} termina em {r}" for t, r in over))


def draw_bobber(d, cx, cy, r, outline_w=3, detail=True):
    """Boia classica: vermelha em cima, branca embaixo.

    Em PIL o angulo cresce no sentido horario a partir das 3h e o eixo Y
    aponta para baixo, entao 0-180 e a metade de BAIXO.
    """
    box = [cx - r, cy - r, cx + r, cy + r]
    d.ellipse(box, fill=BOBBER_RED, outline=LINE, width=int(outline_w))
    d.pieslice(box, start=0, end=180, fill=TEXT)
    d.line([(cx - r, cy), (cx + r, cy)], fill=(30, 36, 42),
           width=max(1, int(r // 8)))
    if detail:  # o miolo suja a leitura em tamanho de icone
        rr = max(1, r // 4)
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(30, 36, 42))


def draw_scene(d, W, H, water_top, bobber, line_from, ripples):
    """Fundo em gradiente, agua ondulada, linha de pesca e boia."""
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT)))

    for y in range(water_top, H):
        t = (y - water_top) / max(1, H - water_top)
        d.line([(0, y), (W, y)],
               fill=tuple(int(a + (b - a) * t) for a, b in zip(WATER, BG_BOT)))

    wave_gap = max(18, (H - water_top) // 8)
    for i, y in enumerate(range(water_top + wave_gap // 2, H, wave_gap)):
        amp, phase = 4 + i, i * 0.9
        pts = [(x, y + amp * math.sin(x / 42 + phase)) for x in range(0, W + 8, 8)]
        d.line(pts, fill=WATER_HI, width=2)

    bx, by, br = bobber
    d.line([line_from, ((bx + line_from[0]) / 2 - 30, (by + line_from[1]) / 2),
            (bx, by)], fill=LINE, width=3)
    for r in ripples:
        d.arc([bx - r, by - r // 3, bx + r, by + r // 3],
              start=0, end=360, fill=WATER_HI, width=2)
    draw_bobber(d, bx, by, br)


def make_preview(W=1280, H=720):
    """Formato largo: preenche a vitrine da Oficina sem tarja preta."""
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    draw_scene(d, W, H, water_top=566,
               bobber=(900, 612, 30), line_from=(1200, 132),
               ripples=(56, 84, 116))

    m = MARGIN_PREVIEW
    edges, usable = [], W - 2 * m
    f_big = ImageFont.truetype(FONT_B, 108)
    f_tag = ImageFont.truetype(FONT_B, 34)
    f_kicker = ImageFont.truetype(FONT_B, 28)

    write(d, (m, 104), "NO CATCH", f_big, TEXT, edges)
    write(d, (m, 218), "FIX", f_big, ACCENT, edges)

    by = 356
    tw = d.textlength("B42.20", font=f_tag)
    d.rounded_rectangle([m, by, m + tw + 36, by + 54], radius=10,
                        outline=ACCENT, width=3)
    d.text((m + 18, by + 10), "B42.20", font=f_tag, fill=ACCENT)
    edges.append(("selo B42.20", m + tw + 36))
    write_spaced(d, (m + tw + 58, by + 28), "MP FISHING", f_kicker, MUTED, 4,
                 edges)

    subs = (("the bait stops vanishing mid-catch", 436, MUTED),
            ("no javaagent, no client-side install", 476, MUTED),
            ("server-side  -  no balance changes", 514, ACCENT))
    f_sub = fit_block(d, [t for t, _, _ in subs], FONT_R, 31, usable)
    for line, y, fill in subs:
        write(d, (m, y), line, f_sub, fill, edges)

    check_margins("preview", edges, W - m)
    return img


def make_poster(size=512):
    """Quadrado: e o formato do painel de mods do jogo."""
    W = H = size
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    draw_scene(d, W, H, water_top=348,
               bobber=(362, 372, 17), line_from=(486, 96),
               ripples=(30, 46, 64))

    # a coluna das legendas e mais estreita que a margem: no quadrado o
    # texto encostado na borda fica sufocado
    edges, usable = [], W - 2 * MARGIN - 24
    f_big = ImageFont.truetype(FONT_B, 62)
    f_tag = ImageFont.truetype(FONT_B, 26)
    f_kicker = ImageFont.truetype(FONT_B, 20)

    write(d, (MARGIN, 74), "NO CATCH", f_big, TEXT, edges)
    write(d, (MARGIN, 140), "FIX", f_big, ACCENT, edges)

    by = 220
    tw = d.textlength("B42.20", font=f_tag)
    d.rounded_rectangle([MARGIN, by, MARGIN + tw + 28, by + 42], radius=8,
                        outline=ACCENT, width=2)
    d.text((MARGIN + 14, by + 8), "B42.20", font=f_tag, fill=ACCENT)
    edges.append(("selo B42.20", MARGIN + tw + 28))
    write_spaced(d, (MARGIN + tw + 44, by + 22), "MP FISHING", f_kicker, MUTED,
                 3, edges)

    subs = (("the bait stops vanishing mid-catch", 278),
            ("server-side  -  no balance changes", 308))
    f_sub = fit_block(d, [t for t, _ in subs], FONT_R, 23, usable)
    for line, y in subs:
        write(d, (MARGIN, y), line, f_sub, MUTED, edges)

    check_margins("poster", edges, W - MARGIN)
    return img


def make_icon(size=64):
    """Desenhado em 8x e reduzido, para as bordas ficarem limpas."""
    S = size * 8
    img = Image.new("RGB", (S, S), BG_TOP)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=S // 5, fill=(16, 24, 30))
    draw_bobber(d, S * 0.5, S * 0.5, S * 0.36,
                outline_w=max(2, S // 32), detail=False)
    return img.resize((size, size), Image.LANCZOS)


def main():
    poster, icon = make_poster(), make_icon()

    targets = [REPO, REPO / "42"]
    if WORKSHOP.exists():
        staged = WORKSHOP / "Contents/mods/FishingMPFix"
        targets += [staged, staged / "42"]
        preview = make_preview()
        preview.save(WORKSHOP / "preview.png")
        print(f"preview.png {preview.size} -> {WORKSHOP}")

    for t in targets:
        t.mkdir(parents=True, exist_ok=True)
        poster.save(t / "poster.png")
        icon.save(t / "icon.png")
        print(f"poster.png {poster.size} + icon.png {icon.size} -> {t}")


if __name__ == "__main__":
    main()

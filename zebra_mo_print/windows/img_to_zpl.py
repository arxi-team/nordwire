import sys
from PIL import Image

src = "/home/rodrigoadelino/Downloads/Logo SK.png"
target_width = 480  # dots

img = Image.open(src)
if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
    img = img.convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    img = Image.alpha_composite(bg, img).convert("RGB")
else:
    img = img.convert("RGB")

img = img.convert("L")
ratio = target_width / img.width
new_size = (target_width, max(1, int(img.height * ratio)))
img = img.resize(new_size, Image.LANCZOS)

# Remap + dither: texto denso (preto solido), fundo vazio (branco), folhas esparsas (claras)
def remap(p):
    if p < 100:
        return 255   # texto original escuro -> alta densidade apos dither -> impresso solido
    if p > 250:
        return 0     # fundo original branco -> baixa densidade -> nao impresso
    return 50        # folhas -> densidade baixa/esparsa -> impressas claras

bw = img.point(remap).convert("1", dither=Image.FLOYDSTEINBERG)

width, height = bw.size
bytes_per_row = (width + 7) // 8
pixels = bw.load()

rows_hex = []
for y in range(height):
    row_bits = []
    for x in range(width):
        row_bits.append("1" if pixels[x, y] else "0")
    while len(row_bits) % 8 != 0:
        row_bits.append("0")
    row_bytes = []
    for i in range(0, len(row_bits), 8):
        byte = int("".join(row_bits[i:i+8]), 2)
        row_bytes.append("%02X" % byte)
    rows_hex.append("".join(row_bytes))

data_hex = "".join(rows_hex)
total_bytes = bytes_per_row * height

zpl_field = "^GFA,%d,%d,%d,%s" % (total_bytes, total_bytes, bytes_per_row, data_hex)

print("WIDTH=%d HEIGHT=%d BYTES_PER_ROW=%d TOTAL_BYTES=%d" % (width, height, bytes_per_row, total_bytes), file=sys.stderr)

with open("/tmp/claude-1001/-home-rodrigoadelino-Desktop-PROJETO-HOME/e4094a8f-192c-403f-ba94-1c841991826c/scratchpad/logo.zpl.txt", "w") as f:
    f.write(zpl_field)

print("done, field length:", len(zpl_field), file=sys.stderr)

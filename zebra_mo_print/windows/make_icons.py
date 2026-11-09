from PIL import Image, ImageDraw

SIZE = 40

def to_zpl_graphic(img):
    img = img.convert("1")
    width, height = img.size
    bytes_per_row = (width + 7) // 8
    pixels = img.load()
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
    return "^GFA,%d,%d,%d,%s" % (total_bytes, total_bytes, bytes_per_row, data_hex)


# --- Phone icon (classic receiver, drawn as a thick "S" curve with rounded ends) ---
phone = Image.new("L", (SIZE, SIZE), 255)
d = ImageDraw.Draw(phone)
d.rounded_rectangle([12, 3, 28, 37], radius=7, outline=0, width=4)
d.ellipse([17, 29, 23, 35], fill=0)
bw = phone.point(lambda p: 0 if p < 128 else 255).convert("1")
phone_field = to_zpl_graphic(bw)

# --- Envelope icon ---
env = Image.new("L", (SIZE, SIZE), 255)
d = ImageDraw.Draw(env)
d.rectangle([2, 8, 37, 32], outline=0, width=3)
d.line([(2, 8), (19, 22)], fill=0, width=3)
d.line([(37, 8), (20, 22)], fill=0, width=3)
bw2 = env.point(lambda p: 0 if p < 128 else 255).convert("1")
env_field = to_zpl_graphic(bw2)

with open("/tmp/claude-1001/-home-rodrigoadelino-Desktop-PROJETO-HOME/e4094a8f-192c-403f-ba94-1c841991826c/scratchpad/icon_phone.zpl.txt", "w") as f:
    f.write(phone_field)
with open("/tmp/claude-1001/-home-rodrigoadelino-Desktop-PROJETO-HOME/e4094a8f-192c-403f-ba94-1c841991826c/scratchpad/icon_envelope.zpl.txt", "w") as f:
    f.write(env_field)

# save previews
bw.resize((bw.width*4, bw.height*4), Image.NEAREST).save("/tmp/claude-1001/-home-rodrigoadelino-Desktop-PROJETO-HOME/e4094a8f-192c-403f-ba94-1c841991826c/scratchpad/icon_phone_preview.png")
bw2.resize((bw2.width*4, bw2.height*4), Image.NEAREST).save("/tmp/claude-1001/-home-rodrigoadelino-Desktop-PROJETO-HOME/e4094a8f-192c-403f-ba94-1c841991826c/scratchpad/icon_envelope_preview.png")
print("done")

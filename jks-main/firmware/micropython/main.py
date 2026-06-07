from machine import Pin, I2C
import sys
import time
from ssd1306_min import SH1106, blink_probe


SDA = 4
SCL = 5
ADDR = 0x3C
WIDTH = 128
HEIGHT = 64
VISIBLE_X = 30
VISIBLE_Y = 12


i2c = I2C(0, sda=Pin(SDA), scl=Pin(SCL), freq=100000)
display = SH1106(WIDTH, HEIGHT, i2c, ADDR, col_offset=2)
current_emotion = "happy"
current_text = "JKS READY"


# frame: left_eye, right_eye, mouth, fallback_label, x_offset, y_offset
FACE_FRAMES = {
    "neutral": [
        ("dot", "dot", "flat", "READY", 0, 0),
        ("blink", "blink", "flat", "READY", 0, 1),
        ("dot", "dot", "flat", "READY", 0, 0),
        ("dot", "dot", "small", "READY", 0, -1),
    ],
    "happy": [
        ("happy", "happy", "smile", "YAY", 0, 0),
        ("happy", "happy", "smile", "^_^", -1, -1),
        ("blink", "blink", "smile", "YAY", 1, -1),
        ("happy", "happy", "open", "yay!", 0, 0),
        ("happy", "happy", "smile", "DONE", 0, 1),
    ],
    "thinking": [
        ("side", "dot", "small", "WAIT", 0, 0),
        ("dot", "side", "small", "hmm?", 1, 0),
        ("side", "side", "flat", "..", -1, 0),
        ("dot", "dot", "small", "...", 0, -1),
        ("dot", "dot", "flat", "...", 0, 0),
    ],
    "speaking": [
        ("dot", "dot", "talk1", "TALK", 0, 0),
        ("happy", "happy", "talk2", "talk", -1, 0),
        ("dot", "dot", "open", "TALK!", 1, 0),
        ("happy", "dot", "small", "mm", 0, -1),
        ("dot", "happy", "talk1", "TALK", 0, 0),
    ],
    "listening": [
        ("wide", "wide", "small", "HEAR", 0, 0),
        ("dot", "wide", "small", "o_o", -1, 0),
        ("wide", "dot", "small", "...", 1, 0),
        ("wide", "wide", "flat", "hear", 0, -1),
        ("dot", "dot", "small", "...", 0, 1),
    ],
    "surprised": [
        ("wide", "wide", "open", "WOW", 0, 0),
        ("wide", "wide", "small", "O_O", 0, -1),
        ("dot", "dot", "open", "!!", -1, 0),
        ("wide", "dot", "open", "WOW!", 1, 0),
        ("wide", "wide", "open", "WOW", 0, 1),
    ],
    "sleepy": [
        ("sleepy", "sleepy", "flat", "zzz", 0, 1),
        ("blink", "blink", "small", "-_-", 0, 1),
        ("sleepy", "sleepy", "flat", "Zzz", 0, 0),
        ("sleepy", "blink", "flat", "zz", 0, 2),
    ],
    "sad": [
        ("sad", "sad", "sad", "oh", 0, 0),
        ("sad", "sad", "sad", "T_T", 0, 1),
        ("blink", "sad", "sad", "...", 0, 0),
        ("sad", "blink", "small", "...", -1, 1),
    ],
    "angry": [
        ("angry", "angry", "flat", "HEY", -1, 0),
        ("angry", "angry", "open", ">_<", 1, 0),
        ("angry", "angry", "flat", "!!", 0, 0),
        ("angry", "dot", "open", "HEY", -2, 0),
    ],
    "error": [
        ("cross", "cross", "flat", "OOPS", -2, 0),
        ("cross", "cross", "open", "! !", 2, 0),
        ("cross", "dot", "flat", "ERR", -1, 0),
        ("dot", "dot", "flat", "READY", 0, 0),
    ],
}

ALIASES = {
    "smile": "happy",
    "joy": "happy",
    "think": "thinking",
    "talk": "speaking",
    "sleep": "sleepy",
    "wow": "surprised",
}


def ack(status, detail):
    print('{"status":"%s","detail":"%s"}' % (status, str(detail).replace('"', "")))


def clean(text, limit=14):
    out = ""
    for ch in str(text):
        if " " <= ch <= "~":
            out += ch
        if len(out) >= limit:
            break
    return out


def clamp_duration(raw, default=900):
    try:
        value = int(raw)
    except Exception:
        return default
    if value < 200:
        return 200
    if value > 5000:
        return 5000
    return value


def clamp_intensity(raw):
    value = str(raw)
    if value in ("soft", "normal", "high"):
        return value
    return "normal"


def normalize_emotion(name):
    value = str(name)
    value = ALIASES.get(value, value)
    if value in FACE_FRAMES:
        return value
    return "neutral"


def draw_eye(x, y, style):
    if style == "blink":
        display.hline(x, y + 6, 14, 1)
    elif style == "happy":
        display.hline(x + 1, y + 7, 12, 1)
        display.pixel(x + 2, y + 6, 1)
        display.pixel(x + 11, y + 6, 1)
    elif style == "wide":
        display.rect(x, y, 14, 12, 1)
        display.fill_rect(x + 5, y + 4, 4, 4, 1)
    elif style == "side":
        display.rect(x, y + 2, 14, 8, 1)
        display.fill_rect(x + 2, y + 5, 4, 2, 1)
    elif style == "sleepy":
        display.hline(x, y + 5, 12, 1)
        display.hline(x + 2, y + 7, 8, 1)
    elif style == "sad":
        display.hline(x + 1, y + 8, 12, 1)
        display.pixel(x + 2, y + 9, 1)
        display.pixel(x + 11, y + 7, 1)
    elif style == "angry":
        display.hline(x, y + 3, 12, 1)
        display.fill_rect(x + 4, y + 6, 6, 4, 1)
    elif style == "cross":
        display.hline(x + 2, y + 3, 10, 1)
        display.hline(x + 2, y + 9, 10, 1)
        display.vline(x + 3, y + 4, 5, 1)
        display.vline(x + 10, y + 4, 5, 1)
    else:
        display.rect(x, y + 2, 14, 8, 1)
        display.fill_rect(x + 5, y + 5, 4, 2, 1)


def draw_mouth(style):
    if style == "smile":
        display.hline(56, 40, 16, 1)
        display.pixel(55, 39, 1)
        display.pixel(72, 39, 1)
    elif style == "small":
        display.hline(60, 40, 8, 1)
    elif style == "open":
        display.rect(56, 36, 16, 10, 1)
        display.fill_rect(61, 40, 6, 3, 1)
    elif style == "talk1":
        display.hline(57, 38, 14, 1)
        display.hline(59, 42, 10, 1)
    elif style == "talk2":
        display.rect(58, 37, 12, 8, 1)
    elif style == "sad":
        display.hline(56, 43, 16, 1)
        display.pixel(55, 44, 1)
        display.pixel(72, 44, 1)
    else:
        display.hline(56, 40, 16, 1)


def draw_frame(frame, label):
    left_eye, right_eye, mouth, fallback_label, dx, dy = frame
    display.fill(0)
    display.rect(0, 0, WIDTH, HEIGHT, 1)
    display.fill_rect(4, 4, 3, 3, 1)
    display.fill_rect(WIDTH - 7, 4, 3, 3, 1)
    draw_eye(34 + dx, 18 + dy, left_eye)
    draw_eye(80 + dx, 18 + dy, right_eye)
    draw_mouth(mouth)
    display.text(clean(label or fallback_label, 16), 8, 50, 1)
    display.show()


def draw(emotion=None, text=None, duration_ms=900, intensity="normal"):
    global current_emotion, current_text
    if emotion is not None:
        current_emotion = normalize_emotion(emotion)
    if text is not None:
        current_text = clean(text, 16)

    frames = FACE_FRAMES.get(current_emotion, FACE_FRAMES["neutral"])
    duration = clamp_duration(duration_ms)
    delay = duration // len(frames)
    intensity = clamp_intensity(intensity)
    if intensity == "high":
        delay = max(70, delay // 2)
    elif intensity == "soft":
        delay = min(900, delay + 120)

    for frame in frames:
        draw_frame(frame, current_text)
        time.sleep_ms(delay)


def clear():
    display.fill(0)
    display.show()


def probe():
    for _ in range(2):
        display.fill(1)
        display.show()
        time.sleep_ms(300)
        display.fill(0)
        display.show()
        time.sleep_ms(200)

    display.fill(0)
    display.rect(0, 0, WIDTH, HEIGHT, 1)
    display.rect(VISIBLE_X, VISIBLE_Y, 72, 40, 1)
    display.fill_rect(0, 0, 12, 12, 1)
    display.fill_rect(WIDTH - 12, 0, 12, 12, 1)
    display.fill_rect(0, HEIGHT - 12, 12, 12, 1)
    display.fill_rect(WIDTH - 12, HEIGHT - 12, 12, 12, 1)
    display.text("JKS", VISIBLE_X + 8, VISIBLE_Y + 8, 1)
    display.text("OLED", VISIBLE_X + 8, VISIBLE_Y + 24, 1)
    display.show()


def handle(line):
    line = line.strip()
    if not line:
        return
    if line.lower() == "clear":
        clear()
        ack("ok", "clear")
        return
    if line.lower() == "probe":
        probe()
        ack("ok", "probe")
        return
    if line.startswith("{"):
        try:
            import json

            data = json.loads(line)
            cmd = data.get("cmd") or data.get("type")
            if cmd == "clear":
                clear()
                ack("ok", "clear")
            elif cmd == "probe":
                probe()
                ack("ok", "probe")
            elif cmd == "text":
                draw("neutral", data.get("text", ""), 500, "soft")
                ack("ok", "text")
            elif cmd in ("emotion", "face"):
                name = normalize_emotion(data.get("name", data.get("emotion", "neutral")))
                label = data.get("display_text", data.get("text", name))
                duration_ms = clamp_duration(data.get("duration_ms", 900))
                intensity = clamp_intensity(data.get("intensity", "normal"))
                draw(name, label, duration_ms, intensity)
                ack("ok", name)
            else:
                ack("error", "unknown")
        except Exception as exc:
            ack("error", str(exc))
        return
    draw("neutral", line, 500, "soft")
    ack("ok", "text")


def boot():
    print("JKS MicroPython OLED controller boot")
    print("i2c scan", [hex(x) for x in i2c.scan()])
    blink_probe(display)
    draw(current_emotion, current_text, 700, "soft")
    ack("ok", "boot")


boot()

while True:
    line = sys.stdin.readline()
    handle(line)
    time.sleep_ms(10)

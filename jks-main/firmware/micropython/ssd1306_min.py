from micropython import const
import framebuf
import time


SET_CONTRAST = const(0x81)
SET_ENTIRE_ON = const(0xA4)
SET_NORM_INV = const(0xA6)
SET_DISP = const(0xAE)
SET_MEM_ADDR = const(0x20)
SET_COL_ADDR = const(0x21)
SET_PAGE_ADDR = const(0x22)
SET_DISP_START_LINE = const(0x40)
SET_SEG_REMAP = const(0xA0)
SET_MUX_RATIO = const(0xA8)
SET_COM_OUT_DIR = const(0xC0)
SET_DISP_OFFSET = const(0xD3)
SET_COM_PIN_CFG = const(0xDA)
SET_DISP_CLK_DIV = const(0xD5)
SET_PRECHARGE = const(0xD9)
SET_VCOM_DESEL = const(0xDB)
SET_CHARGE_PUMP = const(0x8D)


class SSD1306:
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.external_vcc = external_vcc
        self.pages = self.height // 8
        self.buffer = bytearray(self.pages * self.width)
        self.framebuf = framebuf.FrameBuffer(
            self.buffer, self.width, self.height, framebuf.MONO_VLSB
        )
        self.poweron()
        self.init_display()

    def write_cmd(self, cmd):
        self.i2c.writeto(self.addr, b"\x80" + bytes([cmd]))

    def write_data(self, buf):
        self.i2c.writeto(self.addr, b"\x40" + buf)

    def init_display(self):
        for cmd in (
            SET_DISP | 0x00,
            SET_MEM_ADDR,
            0x00,
            SET_DISP_START_LINE | 0x00,
            SET_SEG_REMAP | 0x01,
            SET_MUX_RATIO,
            self.height - 1,
            SET_COM_OUT_DIR | 0x08,
            SET_DISP_OFFSET,
            0x00,
            SET_COM_PIN_CFG,
            0x12 if self.height > 32 else 0x02,
            SET_DISP_CLK_DIV,
            0x80,
            SET_PRECHARGE,
            0x22 if self.external_vcc else 0xF1,
            SET_VCOM_DESEL,
            0x30,
            SET_CONTRAST,
            0xFF,
            SET_ENTIRE_ON,
            SET_NORM_INV,
            SET_CHARGE_PUMP,
            0x10 if self.external_vcc else 0x14,
            SET_DISP | 0x01,
        ):
            self.write_cmd(cmd)
        self.fill(0)
        self.show()

    def poweroff(self):
        self.write_cmd(SET_DISP | 0x00)

    def poweron(self):
        self.write_cmd(SET_DISP | 0x01)

    def contrast(self, contrast):
        self.write_cmd(SET_CONTRAST)
        self.write_cmd(contrast)

    def invert(self, invert):
        self.write_cmd(SET_NORM_INV | (invert & 1))

    def show(self):
        for page in range(self.pages):
            start = page * self.width
            end = start + self.width
            self.write_cmd(SET_COL_ADDR)
            self.write_cmd(0)
            self.write_cmd(self.width - 1)
            self.write_cmd(SET_PAGE_ADDR)
            self.write_cmd(page)
            self.write_cmd(page)
            self.write_data(self.buffer[start:end])

    def fill(self, color):
        self.framebuf.fill(color)

    def pixel(self, x, y, color):
        self.framebuf.pixel(x, y, color)

    def text(self, text, x, y, color=1):
        self.framebuf.text(text, x, y, color)

    def rect(self, x, y, w, h, color):
        self.framebuf.rect(x, y, w, h, color)

    def fill_rect(self, x, y, w, h, color):
        self.framebuf.fill_rect(x, y, w, h, color)

    def hline(self, x, y, w, color):
        self.framebuf.hline(x, y, w, color)

    def vline(self, x, y, h, color):
        self.framebuf.vline(x, y, h, color)


def blink_probe(display):
    display.fill(1)
    display.show()
    time.sleep_ms(350)
    display.fill(0)
    display.show()
    time.sleep_ms(150)


class SH1106:
    def __init__(self, width, height, i2c, addr=0x3C, external_vcc=False, col_offset=2):
        self.width = width
        self.height = height
        self.i2c = i2c
        self.addr = addr
        self.external_vcc = external_vcc
        self.col_offset = col_offset
        self.pages = self.height // 8
        self.buffer = bytearray(self.pages * self.width)
        self.framebuf = framebuf.FrameBuffer(
            self.buffer, self.width, self.height, framebuf.MONO_VLSB
        )
        self.init_display()

    def write_cmd(self, cmd):
        self.i2c.writeto(self.addr, b"\x80" + bytes([cmd]))

    def write_data(self, buf):
        self.i2c.writeto(self.addr, b"\x40" + buf)

    def init_display(self):
        for cmd in (
            0xAE,
            0xD5,
            0x80,
            0xA8,
            self.height - 1,
            0xD3,
            0x00,
            0x40,
            0xAD,
            0x8B,
            0xA1,
            0xC8,
            0xDA,
            0x12 if self.height > 32 else 0x02,
            0x81,
            0xFF,
            0xD9,
            0x1F,
            0xDB,
            0x40,
            0xA4,
            0xA6,
            0xAF,
        ):
            self.write_cmd(cmd)
        self.fill(0)
        self.show()

    def show(self):
        for page in range(self.pages):
            column = self.col_offset
            start = page * self.width
            end = start + self.width
            self.write_cmd(0xB0 | page)
            self.write_cmd(0x00 | (column & 0x0F))
            self.write_cmd(0x10 | ((column >> 4) & 0x0F))
            self.write_data(self.buffer[start:end])

    def fill(self, color):
        self.framebuf.fill(color)

    def pixel(self, x, y, color):
        self.framebuf.pixel(x, y, color)

    def text(self, text, x, y, color=1):
        self.framebuf.text(text, x, y, color)

    def rect(self, x, y, w, h, color):
        self.framebuf.rect(x, y, w, h, color)

    def fill_rect(self, x, y, w, h, color):
        self.framebuf.fill_rect(x, y, w, h, color)

    def hline(self, x, y, w, color):
        self.framebuf.hline(x, y, w, color)

    def vline(self, x, y, h, color):
        self.framebuf.vline(x, y, h, color)

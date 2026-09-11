"""Генерация карточки профиля: шаблон + аватар пользователя в кружке + ID/Роль в полях."""
import os
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(__file__)
TEMPLATE_PATH = os.path.join(BASE_DIR, "assets", "profile_template.png")
FONT_PATH = os.path.join(BASE_DIR, "assets", "fonts", "DejaVuSans-Bold.ttf")

# Координаты подобраны под шаблон 1774x887 (assets/profile_template.png).
AVATAR_CENTER = (374, 418)
AVATAR_RADIUS = 190

ID_BOX = (1100, 296, 1590, 394)     # (left, top, right, bottom)
ROLE_BOX = (1100, 493, 1590, 590)

# Прямоугольники декоративных прочерков-заглушек в шаблоне (их нужно стереть перед текстом).
ID_DASH_RECT = (1075, 333, 1235, 363)
ROLE_DASH_RECT = (1160, 522, 1310, 558)

TEXT_COLOR = (210, 255, 245)
SUPERSAMPLE = 4  # для сглаженного круга аватарки


def _erase_rect(image: Image.Image, rect: tuple, margin: int = 4):
    """Замазать прямоугольник (например, декоративный прочерк) цветом фона,
    беря его слева и справа от прямоугольника и линейно интерполируя —
    так заплатка остаётся незаметной на градиентной заливке плашки."""
    x0, y0, x1, y1 = rect
    left_color = image.getpixel((x0 - margin, (y0 + y1) // 2))[:3]
    right_color = image.getpixel((x1 + margin, (y0 + y1) // 2))[:3]
    px = image.load()
    width = max(1, x1 - x0)
    for x in range(x0, x1 + 1):
        t = (x - x0) / width
        color = tuple(int(left_color[i] + (right_color[i] - left_color[i]) * t) for i in range(3))
        for y in range(y0, y1 + 1):
            px[x, y] = (*color, 255)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, max_height: int,
              start_size: int = 64, min_size: int = 18) -> ImageFont.FreeTypeFont:
    """Подобрать наибольший размер шрифта, при котором текст помещается в бокс."""
    size = start_size
    while size > min_size:
        font = _load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        if w <= max_width and h <= max_height:
            return font
        size -= 2
    return _load_font(min_size)


def _draw_centered_text(draw: ImageDraw.ImageDraw, box: tuple, text: str, padding: int = 24):
    left, top, right, bottom = box
    font = _fit_font(draw, text, right - left - padding * 2, bottom - top)
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = left + (right - left - w) / 2 - bbox[0]
    y = top + (bottom - top - h) / 2 - bbox[1]
    draw.text((x, y), text, font=font, fill=TEXT_COLOR)


def _make_circular_avatar(avatar_bytes: bytes, diameter: int) -> Image.Image:
    """Обрезать аватарку по центру в квадрат, вписать в круг со сглаженными краями."""
    hi_res = diameter * SUPERSAMPLE
    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGB")

    # Center-crop до квадрата.
    w, h = avatar.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    avatar = avatar.crop((left, top, left + side, top + side))
    avatar = avatar.resize((hi_res, hi_res), Image.LANCZOS)

    mask = Image.new("L", (hi_res, hi_res), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, hi_res, hi_res), fill=255)

    circular = Image.new("RGBA", (hi_res, hi_res))
    circular.paste(avatar, (0, 0), mask=mask)
    circular = circular.resize((diameter, diameter), Image.LANCZOS)
    return circular


def build_profile_card(display_id, role_label: str, avatar_bytes: bytes | None = None) -> bytes:
    """Собрать PNG-карточку профиля с ID, ролью и (опционально) аватаркой пользователя."""
    template = Image.open(TEMPLATE_PATH).convert("RGBA")
    _erase_rect(template, ID_DASH_RECT)
    _erase_rect(template, ROLE_DASH_RECT)
    draw = ImageDraw.Draw(template)

    if avatar_bytes:
        diameter = AVATAR_RADIUS * 2
        try:
            avatar = _make_circular_avatar(avatar_bytes, diameter)
            paste_x = AVATAR_CENTER[0] - AVATAR_RADIUS
            paste_y = AVATAR_CENTER[1] - AVATAR_RADIUS
            template.paste(avatar, (paste_x, paste_y), mask=avatar)
        except Exception as e:
            print(f"[profile_card] avatar paste failed: {e}")

    _draw_centered_text(draw, ID_BOX, str(display_id))
    _draw_centered_text(draw, ROLE_BOX, role_label)

    buf = BytesIO()
    template.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf.read()


async def get_avatar_bytes(bot, user_id: int) -> bytes | None:
    """Скачать самую качественную доступную аватарку пользователя из Telegram, если есть."""
    try:
        photos = await bot.get_user_profile_photos(user_id, limit=1)
        if not photos or not photos.photos:
            return None
        best = photos.photos[0][-1]  # последний = самое высокое разрешение
        file = await bot.get_file(best.file_id)
        buf = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        buf.seek(0)
        return buf.read()
    except Exception as e:
        print(f"[profile_card] get_avatar_bytes failed for {user_id}: {e}")
        return None

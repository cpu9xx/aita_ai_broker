import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

import userConfig


FAILURE_LOG = Path(__file__).with_name("feishu_failures.log")


class _FeishuRequestError(RuntimeError):
    def __init__(self, stage, error, **receipt):
        super().__init__(f"{stage}: {error}")
        self.receipt = {"stage": stage, "error": error, **receipt}


def _post_feishu(stage, url, result_path=(), **kwargs):
    secrets = (
        (kwargs.get("json") or {}).get("app_secret"),
        (kwargs.get("headers") or {}).get("Authorization", "").removeprefix("Bearer "),
        url.rsplit("/", 1)[-1] if stage == "send_webhook" else None,
    )
    try:
        response = requests.post(url, **kwargs)
    except requests.RequestException as exc:
        detail = re.sub(r"https?://\S+", "[url]", str(exc))
        for secret in secrets:
            if secret:
                detail = detail.replace(secret, "[redacted]")
        raise _FeishuRequestError(stage, type(exc).__name__, detail=detail[:500]) from None

    receipt = {
        "http_status": response.status_code,
        "request_id": response.headers.get("X-Tt-Logid") or response.headers.get("X-Request-Id"),
    }
    try:
        payload = response.json()
    except ValueError:
        raise _FeishuRequestError(stage, "invalid_json", content_type=response.headers.get("Content-Type"), **receipt) from None
    if not isinstance(payload, dict):
        raise _FeishuRequestError(stage, "unexpected_response_type", **receipt)

    result = payload
    for key in result_path:
        result = result.get(key) if isinstance(result, dict) else None
    code = payload.get("code", 0 if result_path else None)
    if response.status_code != 200 or code != 0 or (result_path and not result):
        message = str(payload.get("msg") or payload.get("message") or "")
        for secret in (*secrets, payload.get("tenant_access_token")):
            if isinstance(secret, str) and secret:
                message = message.replace(secret, "[redacted]")
        error_info = payload.get("error")
        if isinstance(error_info, dict) and not receipt["request_id"]:
            receipt["request_id"] = error_info.get("log_id")
        raise _FeishuRequestError(stage, "api_failure", feishu_code=payload.get("code"), feishu_message=message[:500], **receipt)
    return result


# ===============================
# 辅助工具：移除 ANSI 颜色代码
# ===============================
def strip_ansi(text):
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m|\[[0-9;]*m')
    return ansi_escape.sub('', text)


# =====================================================
# 获取 tenant_access_token
# =====================================================
def _get_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    return _post_feishu("get_token", url, ("tenant_access_token",), json={
        "app_id": userConfig.feishu_app_id,
        "app_secret": userConfig.feishu_app_secret,
    })


# =====================================================
# 文字转图片 (带 ANSI 颜色解析 & 浅色主题)
# =====================================================
def text_to_image(text, title="Feishu Message"):
    # --- 配置 (新版浅色主题) ---
    background_color = (255, 255, 255)
    default_text_color = (40, 44, 52)
    title_color = (0, 86, 179)
    border_color = (210, 214, 220)

    padding_x = 40
    padding_y = 40
    line_spacing = 8
    font_size = 20
    title_font_size = 28

    color_map = {
        '31': (255, 0, 0),
        '32': (40, 167, 69),
        '33': (180, 120, 0),
        '34': (0, 123, 255),
        '35': (111, 66, 193),
        '36': (23, 162, 184),
        '0': default_text_color,
    }

    # --- 字体加载 ---
    fonts_to_try = [
        "C:\\Windows\\Fonts\\msyh.ttc",
        "C:\\Windows\\Fonts\\simhei.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]
    font = None
    title_font = None
    for f_path in fonts_to_try:
        if os.path.exists(f_path):
            try:
                font = ImageFont.truetype(f_path, font_size)
                title_font = ImageFont.truetype(f_path, title_font_size)
                break
            except Exception:
                continue
    if not font:
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

    def get_text_width(t, f):
        if not t:
            return 0
        try:
            if hasattr(f, 'getlength'):
                return f.getlength(t)
            bbox = draw_test.textbbox((0, 0), t, font=f)
            return bbox[2] - bbox[0]
        except Exception:
            w = 0
            for char in t:
                if ord(char) < 128:
                    w += font_size * 0.6
                else:
                    w += font_size * 1.1
            return w

    text = text.expandtabs(4)
    raw_lines = text.split('\n')
    ansi_pattern = re.compile(r'\x1b\[(\d+)m|\[(\d+)m')
    max_text_width = 1000

    draw_test = ImageDraw.Draw(Image.new('RGB', (1, 1)))

    wrapped_parsed_lines = []

    for line in raw_lines:
        segments = []
        last_idx = 0
        current_color = default_text_color
        for match in ansi_pattern.finditer(line):
            part = line[last_idx:match.start()]
            if part:
                segments.append((part, current_color))
            code = match.group(1) or match.group(2)
            current_color = color_map.get(code, current_color)
            last_idx = match.end()
        if last_idx < len(line):
            segments.append((line[last_idx:], current_color))

        if not segments:
            wrapped_parsed_lines.append([])
            continue

        current_display_line = []
        current_line_w = 0

        for txt, color in segments:
            for char in txt:
                char_w = get_text_width(char, font)
                if current_line_w + char_w > max_text_width:
                    if current_display_line:
                        wrapped_parsed_lines.append(current_display_line)
                    prefix = "  + "
                    prefix_color = (220, 53, 69)
                    current_display_line = [(prefix, prefix_color), (char, color)]
                    current_line_w = get_text_width(prefix, font) + char_w
                else:
                    if current_display_line and current_display_line[-1][1] == color:
                        prev_txt, prev_clr = current_display_line[-1]
                        current_display_line[-1] = (prev_txt + char, prev_clr)
                    else:
                        current_display_line.append((char, color))
                    current_line_w += char_w

        if current_display_line:
            wrapped_parsed_lines.append(current_display_line)

    parsed_lines = wrapped_parsed_lines

    # --- 计算尺寸 ---
    max_line_width = 0
    for line_segs in parsed_lines:
        line_w = 0
        for txt, _ in line_segs:
            line_w += get_text_width(txt, font)
        max_line_width = max(max_line_width, line_w)

    title_w = get_text_width(title, title_font)

    img_width = max(max_line_width, title_w) + (padding_x * 2) + 40
    img_width = min(max(img_width, 600), max_text_width + padding_x * 2 + 150)

    line_height = font_size + line_spacing
    img_height = (len(parsed_lines) * line_height) + (padding_y * 2) + 80

    # --- 绘图 ---
    img = Image.new('RGB', (int(img_width), int(img_height)), color=background_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, img_width - 1, img_height - 1], outline=border_color, width=1)
    draw.text((padding_x, padding_y), title, font=title_font, fill=title_color)
    draw.line([padding_x, padding_y + 45, img_width - padding_x, padding_y + 45], fill=border_color, width=1)

    curr_y = padding_y + 80
    for line_segs in parsed_lines:
        curr_x = padding_x
        for txt, color in line_segs:
            if not txt:
                continue
            draw.text((curr_x, curr_y), txt, font=font, fill=color)
            curr_x += get_text_width(txt, font)
        curr_y += line_height

    temp_path = "temp_text_img.png"
    img.save(temp_path)
    return temp_path


# =====================================================
# 上传图片
# =====================================================
def _upload_image(token, image_path):
    url = "https://open.feishu.cn/open-apis/im/v1/images"
    headers = {"Authorization": f"Bearer {token}"}
    with open(image_path, "rb") as image_file:
        files = {"image_type": (None, "message"), "image": (os.path.basename(image_path), image_file, "image/png")}
        return _post_feishu("upload_image", url, ("data", "image_key"), headers=headers, files=files)


# =====================================================
# App方式发送（支持图文）
# =====================================================
def _send_app_message(title, msg_text, image_paths):
    token = _get_token()
    content_lines = []
    for line in msg_text.split("\n"):
        if line.strip():
            content_lines.append([{"tag": "text", "text": line}])
    for img in image_paths:
        image_key = _upload_image(token, img)
        content_lines.append([{"tag": "img", "image_key": image_key}])

    content = {"zh_cn": {"title": title, "content": content_lines}}

    url = "https://open.feishu.cn/open-apis/im/v1/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = {
        "receive_id": userConfig.feishu_chat_id,
        "msg_type": "post",
        "content": json.dumps(content),
    }
    params = {"receive_id_type": "chat_id"}

    _post_feishu("send_app", url, headers=headers, params=params, json=data)
    print("Feishu: message sent via App")


# =====================================================
# Webhook发送（文本）
# =====================================================
def _send_webhook(title, msg_text):
    content_lines = []
    for line in msg_text.split('\n'):
        if line.strip():
            content_lines.append([{"tag": "text", "text": line}])
    data = {
        "msg_type": "post",
        "content": {
            "post": {"zh_cn": {"title": title, "content": content_lines}},
        },
    }
    _post_feishu("send_webhook", userConfig.feishu_webhook_url, json=data)
    print("Feishu: message sent via Webhook")


# =====================================================
# ⭐ 对外统一接口
# =====================================================
def send_feishu(msg_text, title='Error', image_paths=None, mode='image'):
    if image_paths is None:
        image_paths = []
    for attempt in range(1, 61):
        try:
            if mode == 'text':
                clean_text = strip_ansi(msg_text)
                if image_paths:
                    _send_app_message(title, clean_text, image_paths)
                else:
                    # webhook for plain text
                    _send_webhook(title, clean_text)
            else:
                text_img_path = text_to_image(msg_text, title=title)
                all_images = [text_img_path] + (image_paths or [])
                _send_app_message(title, "", all_images)
                if os.path.exists(text_img_path):
                    os.remove(text_img_path)
            return True
        except Exception as exc:
            failure = exc.receipt if isinstance(exc, _FeishuRequestError) else {"stage": "local", "error": type(exc).__name__}
            entry = {"time": datetime.now().astimezone().isoformat(timespec="seconds"), "title": title, "mode": mode, "attempt": attempt, **failure}
            try:
                with FAILURE_LOG.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except OSError as log_error:
                print(f"Feishu could not write {FAILURE_LOG}: {log_error}", flush=True)
            print(f"Feishu attempt {attempt}/60 failed: {failure}", flush=True)
            time.sleep(2)
    return False

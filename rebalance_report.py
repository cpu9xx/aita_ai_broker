import datetime as dt
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import userConfig


def format_rebalance_report(
    order_file,
    account,
    trade_date,
    trade_time,
    account_state,
    position_rows,
    trades=None,
):
    trades = trades or []
    total_market_value = sum(row["market_value_usd"] for row in position_rows)
    total_target_value = sum(row["target_value_usd"] for row in position_rows)
    total_order_value = sum(abs(trade.get("order_value_usd", 0)) for trade in trades)

    lines = []
    lines.append("Rebalance Report")
    lines.append(f"Generated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Order file: {order_file}")
    lines.append(f"Account: {account}")
    lines.append(f"Trade date: {trade_date}")
    lines.append(f"Trade time: {trade_time}")
    lines.append("")
    lines.append("Account Summary")
    for key, value in account_state.items():
        lines.append(f"{key}: {value}")
    lines.append(f"Total position market value USD: {total_market_value:,.2f}")
    lines.append(f"Total target value USD: {total_target_value:,.2f}")
    lines.append(f"Total order value USD: {total_order_value:,.2f}")
    lines.append("")
    lines.append("Position Plan")
    lines.append("Symbol | Price | Current Qty | Current Value | Current Wgt | Target Wgt | Target Value | Target Qty | Diff Qty")
    for row in position_rows:
        lines.append(
            f"{row['symbol']} | "
            f"{row['price']:.2f} | "
            f"{row['current_qty']:g} | "
            f"{row['market_value_usd']:,.2f} | "
            f"{row['current_weight']:.2f}% | "
            f"{row['target_weight']:.2f}% | "
            f"{row['target_value_usd']:,.2f} | "
            f"{row['target_qty']:g} | "
            f"{row['diff_qty']:g}"
        )
    lines.append("")
    lines.append("Orders")
    if trades:
        lines.append("Symbol | Action | Qty | Price | Order Value | Status")
        for trade in trades:
            lines.append(
                f"{trade.get('symbol', '')} | "
                f"{trade.get('action', '')} | "
                f"{trade.get('quantity', '')} | "
                f"{trade.get('price', '')} | "
                f"{trade.get('order_value_usd', 0):,.2f} | "
                f"{trade.get('status', '')}"
            )
    else:
        lines.append("No orders")
    return "\n".join(lines)


def save_report_image(text, title="AITA Rebalance Report", output_dir=None):
    output_dir = Path(output_dir or userConfig.report_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"rebalance_report_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

    font, title_font = load_fonts()
    padding_x = 36
    padding_y = 32
    line_height = 30
    title_height = 44
    lines = text.splitlines()

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    max_width = max([measure.textlength(title, font=title_font)] + [measure.textlength(line, font=font) for line in lines])
    width = int(min(max(max_width + padding_x * 2, 900), 1800))
    height = padding_y * 2 + title_height + max(len(lines), 1) * line_height

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(210, 214, 220), width=1)
    draw.text((padding_x, padding_y), title, font=title_font, fill=(0, 86, 179))
    draw.line([padding_x, padding_y + title_height - 8, width - padding_x, padding_y + title_height - 8], fill=(210, 214, 220), width=1)

    y = padding_y + title_height
    for line in lines:
        fill = (40, 44, 52)
        if "BUY" in line:
            fill = (40, 120, 40)
        elif "SELL" in line:
            fill = (190, 40, 40)
        draw.text((padding_x, y), line, font=font, fill=fill)
        y += line_height

    image.save(path)
    return path


def save_rebalance_report_image(
    order_file,
    account,
    trade_date,
    trade_time,
    account_state,
    position_rows,
    trades=None,
    title="AITA Rebalance Report",
    output_dir=None,
):
    trades = trades or []
    output_dir = Path(output_dir or userConfig.report_output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"rebalance_report_{dt.datetime.now().strftime('%Y%m%d')}.png"

    font, title_font = load_fonts()
    small_font = font
    padding_x = 36
    padding_y = 32
    section_gap = 22
    line_height = 30
    cell_pad_x = 12
    cell_pad_y = 8
    row_height = 38

    total_market_value = sum(row["market_value_usd"] for row in position_rows)
    total_target_value = sum(row["target_value_usd"] for row in position_rows)
    total_order_value = sum(abs(trade.get("order_value_usd", 0)) for trade in trades)

    summary_lines = [
        f"Generated: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Order file: {order_file}",
        f"Account: {account}",
        f"Trade date: {trade_date}",
        f"Trade time: {trade_time}",
    ]
    for key, value in account_state.items():
        if key == "Daily PnL":
            continue
        summary_lines.append(f"{key}: {value}")
    summary_lines.extend(
        [
            f"Total position market value USD: {total_market_value:,.2f}",
            f"Total target value USD: {total_target_value:,.2f}",
            f"Total order value USD: {total_order_value:,.2f}",
        ]
    )

    daily_pnl_line = account_state.get("Daily PnL")

    position_table = [
        ["Symbol", "Price", "Current Qty", "Current Value", "Current Wgt", "Target Wgt", "Target Value", "Target Qty", "Diff Qty"]
    ]
    for row in position_rows:
        position_table.append(
            [
                row["symbol"],
                f"{row['price']:.2f}",
                f"{row['current_qty']:g}",
                f"{row['market_value_usd']:,.2f}",
                f"{row['current_weight']:.2f}%",
                f"{row['target_weight']:.2f}%",
                f"{row['target_value_usd']:,.2f}",
                f"{row['target_qty']:g}",
                f"{row['diff_qty']:g}",
            ]
        )

    order_table = [["Symbol", "Action", "Qty", "Price", "Order Value", "Status"]]
    if trades:
        for trade in trades:
            order_table.append(
                [
                    trade.get("symbol", ""),
                    trade.get("action", ""),
                    f"{trade.get('quantity', '')}",
                    f"{trade.get('price', '')}",
                    f"{trade.get('order_value_usd', 0):,.2f}",
                    trade.get("status", ""),
                ]
            )
    else:
        order_table.append(["", "No orders", "", "", "", ""])

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_width = text_width(measure, title, title_font)
    summary_width = max(text_width(measure, line, small_font) for line in summary_lines)
    pnl_width = text_width(measure, f"Daily PnL: {daily_pnl_line}", font) if daily_pnl_line else 0
    position_widths = table_col_widths(measure, position_table, small_font, cell_pad_x)
    order_widths = table_col_widths(measure, order_table, small_font, cell_pad_x)
    position_table_width = sum(position_widths)
    order_table_width = sum(order_widths)

    width = int(max(title_width, summary_width, pnl_width, position_table_width, order_table_width) + padding_x * 2)
    width = max(width, 900)

    y = padding_y
    y += 44
    y += len(summary_lines) * line_height + section_gap
    if daily_pnl_line:
        y += line_height + section_gap
    y += line_height + len(position_table) * row_height + section_gap
    y += line_height + len(order_table) * row_height
    height = int(y + padding_y)

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, width - 1, height - 1], outline=(210, 214, 220), width=1)

    y = padding_y
    draw.text((padding_x, y), title, font=title_font, fill=(0, 86, 179))
    y += 44
    draw.line([padding_x, y - 8, width - padding_x, y - 8], fill=(210, 214, 220), width=1)

    for line in summary_lines:
        draw.text((padding_x, y), line, font=small_font, fill=(40, 44, 52))
        y += line_height
    y += section_gap

    if daily_pnl_line:
        draw.text((padding_x, y), f"Daily PnL: {daily_pnl_line}", font=font, fill=(40, 44, 52))
        y += line_height + section_gap

    draw.text((padding_x, y), "Position Plan", font=small_font, fill=(40, 44, 52))
    y += line_height
    draw_table(draw, position_table, padding_x, y, position_widths, row_height, small_font, cell_pad_x, cell_pad_y)
    y += len(position_table) * row_height + section_gap

    draw.text((padding_x, y), "Orders", font=small_font, fill=(40, 44, 52))
    y += line_height
    draw_table(draw, order_table, padding_x, y, order_widths, row_height, small_font, cell_pad_x, cell_pad_y)

    image.save(path)
    return path


def table_col_widths(draw, rows, font, cell_pad_x):
    widths = []
    for col_idx in range(len(rows[0])):
        max_width = max(text_width(draw, str(row[col_idx]), font) for row in rows)
        widths.append(int(max_width + cell_pad_x * 2))
    return widths


def draw_table(draw, rows, x, y, col_widths, row_height, font, cell_pad_x, cell_pad_y):
    border = (210, 214, 220)
    header_bg = (241, 245, 249)
    text = (40, 44, 52)
    buy = (40, 120, 40)
    sell = (190, 40, 40)
    numeric_cols = set(range(1, len(rows[0]) - 1))

    table_width = sum(col_widths)
    for row_idx, row in enumerate(rows):
        row_y = y + row_idx * row_height
        if row_idx == 0:
            draw.rectangle([x, row_y, x + table_width, row_y + row_height], fill=header_bg)
        cur_x = x
        row_color = text
        if "BUY" in row:
            row_color = buy
        elif "SELL" in row:
            row_color = sell
        for col_idx, cell in enumerate(row):
            cell = str(cell)
            draw.rectangle([cur_x, row_y, cur_x + col_widths[col_idx], row_y + row_height], outline=border, width=1)
            fill = text if row_idx == 0 else row_color
            if row_idx > 0 and col_idx in numeric_cols:
                cell_width = text_width(draw, cell, font)
                text_x = cur_x + col_widths[col_idx] - cell_pad_x - cell_width
            else:
                text_x = cur_x + cell_pad_x
            draw.text((text_x, row_y + cell_pad_y), cell, font=font, fill=fill)
            cur_x += col_widths[col_idx]


def text_width(draw, text, font):
    if hasattr(font, "getlength"):
        return font.getlength(str(text))
    bbox = draw.textbbox((0, 0), str(text), font=font)
    return bbox[2] - bbox[0]


def send_rebalance_report(text, image_path, chart_path=None):
    from feishu_sender import send_feishu

    account = userConfig.account
    image_paths = [str(image_path)]
    if chart_path:
        image_paths.append(str(chart_path))

    send_feishu(
        "Rebalance report image attached.",
        title=f"{account} Rebalance Report",
        image_paths=image_paths,
        mode="text",
    )


def load_fonts():
    font_paths = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for font_path in font_paths:
        path = Path(font_path)
        if path.exists():
            return ImageFont.truetype(str(path), 20), ImageFont.truetype(str(path), 28)
    return ImageFont.load_default(), ImageFont.load_default()

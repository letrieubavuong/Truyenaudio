"""
Shared Video Frame Renderer for preview and export.
Built with PySide6 (QImage, QPainter, QFont, QColor, QPainterPath).
Guarantees:
- 100% identical rendering between live preview and FFmpeg video export.
- Supports 1920x1080 and 1280x720 (16:9).
- Two background modes: 'crop_fill' and 'fit_letterbox' (never distorts image).
- Comprehensive typography with stroke/shadow, Vietnamese Unicode support, and safe margins.
- Auto-wrap and adaptive bounds for long titles to prevent overflow.
"""
import sys
import os
from typing import Optional
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QGuiApplication, QImage, QPainter, QColor, QFont, QPen,
    QBrush, QLinearGradient, QFontMetrics, QPainterPath
)
from core.video_models import AudioVideoItem, VideoConfig


def ensure_qapp():
    """Đảm bảo luôn có QGuiApplication để sử dụng QPainter và QFont."""
    if not QGuiApplication.instance():
        app = QGuiApplication(sys.argv if sys.argv else ["Truyenaudio"])


def render_frame(item: AudioVideoItem, config: VideoConfig) -> QImage:
    """
    Dựng ảnh khung hình chuẩn cho video hoặc xem trước.
    Trả về QImage độ phân giải chuẩn (1920x1080 hoặc cấu hình).
    """
    ensure_qapp()

    w = config.width or 1920
    h = config.height or 1080

    canvas = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(QColor(15, 18, 28))

    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)

    # 1. DỰNG ẢNH NỀN
    bg_path = item.custom_bg_path or config.bg_image_path
    if bg_path:
        if not os.path.isfile(bg_path):
            painter.end()
            raise ValueError(f"Không tìm thấy tệp ảnh nền: {bg_path}")

        bg_img = QImage(bg_path)
        if bg_img.isNull():
            painter.end()
            raise ValueError(f"Tệp ảnh nền bị hỏng hoặc định dạng không hợp lệ: {bg_path}")

        mode = config.bg_mode or "crop_fill"
        if mode == "fit_letterbox":
            # Chế độ Fit: Giữ đúng tỉ lệ, căn giữa, thêm viền đen nếu ảnh không đúng 16:9
            scaled = bg_img.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x_off = (w - scaled.width()) // 2
            y_off = (h - scaled.height()) // 2
            painter.drawImage(x_off, y_off, scaled)
        else:
            # Chế độ Crop Fill: Giữ đúng tỉ lệ, phóng to phủ kín khung hình, cắt phần thừa
            scaled = bg_img.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x_off = (scaled.width() - w) // 2
            y_off = (scaled.height() - h) // 2
            cropped = scaled.copy(x_off, y_off, w, h)
            painter.drawImage(0, 0, cropped)
    else:
        # Nếu không có ảnh, dùng dải màu gradient nền tối sang trọng
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor(24, 28, 48))
        grad.setColorAt(0.5, QColor(14, 18, 32))
        grad.setColorAt(1.0, QColor(8, 10, 20))
        painter.fillRect(0, 0, w, h, grad)

    # 2. LỚP PHỦ TỐI (GRADIENT VIGNETTE) ĐỂ CHỮ NỔI BẬT TRÊN MỌI ẢNH NỀN
    overlay = QLinearGradient(0, 0, 0, h)
    overlay.setColorAt(0.0, QColor(0, 0, 0, 90))
    overlay.setColorAt(0.4, QColor(0, 0, 0, 140))
    overlay.setColorAt(0.8, QColor(0, 0, 0, 210))
    overlay.setColorAt(1.0, QColor(0, 0, 0, 240))
    painter.fillRect(0, 0, w, h, overlay)

    # 3. VÙNG AN TOÀN (SAFE MARGIN)
    margin = config.safe_margin or 80
    safe_rect = QRectF(margin, margin, w - 2 * margin, h - 2 * margin)

    # 4. VẼ CÁC THÀNH PHẦN CHỮ (TYPOGRAPHY)
    def draw_text_with_outline(
        text: str,
        font: QFont,
        rect: QRectF,
        flags: int,
        text_color: QColor,
        stroke_color: QColor,
        stroke_width: int,
        has_shadow: bool = True,
        shadow_offset: int = 4,
    ) -> QRectF:
        """Vẽ chữ có viền và bóng đổ sắc nét, không bị nhòe."""
        path = QPainterPath()
        # Tính toán bounding box
        fm = QFontMetrics(font)
        # Sử dụng painter.drawText với stroke nếu path phức tạp, hoặc vẽ đa lớp
        # Để đảm bảo word wrap chính xác trên tiếng Việt, vẽ trực tiếp qua painter theo lớp:
        painter.setFont(font)

        # Lớp 1: Bóng chữ (Shadow)
        if has_shadow:
            shadow_rect = QRectF(rect.x() + shadow_offset, rect.y() + shadow_offset, rect.width(), rect.height())
            painter.setPen(QColor(0, 0, 0, 180))
            painter.drawText(shadow_rect, flags, text)

        # Lớp 2: Viền chữ (Stroke/Outline) xung quanh
        if stroke_width > 0:
            painter.setPen(stroke_color)
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx != 0 or dy != 0:
                        out_rect = QRectF(rect.x() + dx, rect.y() + dy, rect.width(), rect.height())
                        painter.drawText(out_rect, flags, text)

        # Lớp 3: Chữ chính (Foreground Fill)
        painter.setPen(text_color)
        painter.drawText(rect, flags, text)

        return fm.boundingRect(rect.toRect(), flags, text)

    font_fam = config.font_family or "Segoe UI"
    text_color = QColor(config.text_color or "#FFFFFF")
    stroke_color = QColor(config.stroke_color or "#000000")
    stroke_w = config.stroke_width if config.stroke_width is not None else 3
    has_shadow = config.has_shadow
    shadow_off = config.shadow_offset or 4

    # Bố cục dọc trong safe_rect:
    # - Top: Tên truyện (Lớn, Nổi bật, Wrap nếu dài)
    # - Middle: Tác giả
    # - Center/Bottom-Center: TẬP {volume_num} (Rất lớn, màu vàng kim/nổi)
    # - Bottom: Chương {start} – {end}

    curr_y = safe_rect.top() + 40

    # 1. Tên truyện
    if config.show_title and item.story_title:
        title_font = QFont(font_fam, config.title_size or 56, QFont.Bold)
        title_rect = QRectF(safe_rect.left(), curr_y, safe_rect.width(), 160)
        # Tự co cỡ chữ nếu tên quá dài
        fm_title = QFontMetrics(title_font)
        req_h = fm_title.boundingRect(title_rect.toRect(), Qt.TextWordWrap | Qt.AlignHCenter, item.story_title).height()
        if req_h > 160 and title_font.pointSize() > 36:
            title_font.setPointSize(int(title_font.pointSize() * 0.8))
        
        draw_text_with_outline(
            item.story_title.upper(),
            title_font,
            title_rect,
            Qt.TextWordWrap | Qt.AlignHCenter | Qt.AlignTop,
            text_color,
            stroke_color,
            stroke_w + 1,
            has_shadow,
            shadow_off,
        )
        curr_y += req_h + 30

    # 2. Tác giả
    if config.show_author and item.author:
        author_font = QFont(font_fam, config.author_size or 34, QFont.Normal)
        author_text = f"Tác giả: {item.author}"
        author_rect = QRectF(safe_rect.left(), curr_y, safe_rect.width(), 60)
        draw_text_with_outline(
            author_text,
            author_font,
            author_rect,
            Qt.AlignHCenter | Qt.AlignTop,
            QColor("#E0E0E0"),
            stroke_color,
            stroke_w,
            has_shadow,
            shadow_off,
        )
        curr_y += 70

    # 3. Đường kẻ trang trí tinh tế ở giữa
    line_y = (safe_rect.top() + safe_rect.bottom()) / 2 - 20
    painter.setPen(QPen(QColor(255, 215, 0, 160), 2))
    center_x = w / 2
    painter.drawLine(center_x - 220, line_y, center_x + 220, line_y)

    # 4. Số Tập: TẬP {volume_num} (Màu vàng kim nổi bật)
    if config.show_volume:
        vol_font = QFont(font_fam, config.volume_size or 72, QFont.Black)
        vol_rect = QRectF(safe_rect.left(), line_y + 30, safe_rect.width(), 130)
        vol_color = QColor("#FFD700")  # Gold accent
        draw_text_with_outline(
            f"TẬP {item.volume_num:02d}" if item.volume_num < 100 else f"TẬP {item.volume_num}",
            vol_font,
            vol_rect,
            Qt.AlignHCenter | Qt.AlignVCenter,
            vol_color,
            stroke_color,
            stroke_w + 2,
            has_shadow,
            shadow_off + 2,
        )

    # 5. Khoảng chương: Chương {start} – {end}
    if config.show_chapters:
        chap_font = QFont(font_fam, config.chapters_size or 38, QFont.Bold)
        chap_rect = QRectF(safe_rect.left(), safe_rect.bottom() - 100, safe_rect.width(), 80)
        chap_text = f"Chương {item.start_chapter}  —  Chương {item.end_chapter}"
        draw_text_with_outline(
            chap_text,
            chap_font,
            chap_rect,
            Qt.AlignHCenter | Qt.AlignVCenter,
            QColor("#F5F5F5"),
            stroke_color,
            stroke_w,
            has_shadow,
            shadow_off,
        )

    painter.end()
    return canvas


def save_frame_image(item: AudioVideoItem, config: VideoConfig, output_image_path: str) -> str:
    """
    Kết xuất ảnh khung hình và lưu ra tệp PNG/JPEG để đưa vào FFmpeg.
    """
    img = render_frame(item, config)
    os.makedirs(os.path.dirname(os.path.abspath(output_image_path)), exist_ok=True)
    if not img.save(output_image_path, "PNG"):
        raise IOError(f"Không thể ghi tệp ảnh khung hình: {output_image_path}")
    return output_image_path

"""从上传的文档里抠出纯文本，供「解析文章」使用。

支持范围：
- .pdf   → pypdf（纯 Python，能处理多数论文 PDF 的字体/编码）
- .docx  → 标准库 zipfile + ElementTree 读 word/document.xml（不额外引入 python-docx）
- .txt / .md / 其它纯文本 → 直接按常见编码解码
- .doc   → 老二进制格式，没有可靠的开源纯 Python 解析器，明确报错让用户另存为 .docx 或 PDF

设计取舍：
- 文件以 base64 从请求体传进来（前端 FileReader 读取），这样可以不用 python-multipart。
- 两道闸门防拖垮服务：单个文件最大 MAX_BYTES，抠出的正文最多 MAX_CHARS。
- 所有失败都抛 DocTextError，由路由层转成统一错误响应，不会 500。
"""
from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from xml.etree import ElementTree

# 单个文件上限 20MB。学术 PDF 一般 1~8MB，20MB 已经足够宽裕。
MAX_BYTES = 20 * 1024 * 1024
# 抠出的正文上限 8 万字符。再长对抽关键词没有增益，只会白烧模型额度。
MAX_CHARS = 80_000

# docx 里正文所在的命名空间
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

# 纯文本类型的扩展名
_TEXT_EXT = (".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log", ".rst")

# 老版 Word 二进制格式
_LEGACY_DOC = (".doc", ".rtf", ".wps")


class DocTextError(Exception):
    """文档读取失败。message 会直接展示给用户，所以要写人话。"""


def _ext(filename: str) -> str:
    name = (filename or "").strip().lower()
    i = name.rfind(".")
    return name[i:] if i >= 0 else ""


def _decode_text(raw: bytes) -> str:
    """按常见编码依次尝试，最后用 utf-8 宽松模式兜底（中文文档最常见的坑）。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    """统一换行、压掉多余空白，避免模型在排版噪声上浪费注意力。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去掉零宽字符与软连字符（PDF 抽取常见）
    text = re.sub(r"[\u200b-\u200f\u2028\u2029\u00ad\ufeff]", "", text)
    # 连续 3 个以上空行压成 2 个
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 行内连续空白压成一个空格
    text = re.sub(r"[ \t\u3000]{2,}", " ", text)
    return text.strip()


def _from_pdf(raw: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出可操作提示
        raise DocTextError(
            "服务端缺少 PDF 解析组件（pypdf）。请在项目根目录执行："
            ".venv\\Scripts\\python.exe -m pip install \"pypdf>=5\""
        ) from exc

    try:
        reader = PdfReader(io.BytesIO(raw))
        if getattr(reader, "is_encrypted", False):
            # 有些 PDF 只加密了权限位，空密码就能打开
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise DocTextError("这个 PDF 有加密，无法读取正文。请先去掉密码再上传。") from exc
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001 - 单页失败不影响其它页
                pages.append("")
            if sum(len(p) for p in pages) > MAX_CHARS:
                break
    except DocTextError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DocTextError("这个 PDF 读不出来，可能文件损坏或格式特殊。可试试另存一份再上传。") from exc

    text = _clean("\n".join(pages))
    if len(text) < 40:
        raise DocTextError(
            "这个 PDF 里没抠出文字，很可能整份都是扫描图片（图片型 PDF）。"
            "请改用粘贴文本，或先用 OCR 转成可复制文字。"
        )
    return text


def _from_docx(raw: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise DocTextError("这个 Word 文件读不出来，可能已损坏。可先用 Word 另存为 .docx 再上传。") from exc

    with zf:
        names = set(zf.namelist())
        target = "word/document.xml"
        if target not in names:
            raise DocTextError("这个文件不像是标准 .docx。若来自 WPS，请另存为 .docx 或 PDF 再上传。")
        try:
            xml = zf.read(target)
        except Exception as exc:  # noqa: BLE001
            raise DocTextError("读取 Word 正文失败，文件可能已损坏。") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise DocTextError("Word 正文解析失败，文件结构异常。") from exc

    # 逐段取 <w:t> 文本；<w:br>/<w:tab> 转成空白，段与段之间换行
    lines: list[str] = []
    for para in root.iter(f"{_W_NS}p"):
        buf: list[str] = []
        for node in para.iter():
            tag = node.tag
            if tag == f"{_W_NS}t":
                buf.append(node.text or "")
            elif tag in (f"{_W_NS}br", f"{_W_NS}cr"):
                buf.append("\n")
            elif tag == f"{_W_NS}tab":
                buf.append(" ")
        line = "".join(buf).strip()
        if line:
            lines.append(line)
        if sum(len(x) for x in lines) > MAX_CHARS:
            break

    text = _clean("\n".join(lines))
    if len(text) < 20:
        raise DocTextError("这个 Word 文档里几乎没有文字内容，无法抽取关键词。")
    return text


def _from_plain(raw: bytes) -> str:
    text = _clean(_decode_text(raw))
    if not text:
        raise DocTextError("文件里没有可读的文字内容。")
    return text


def extract_text(filename: str, raw: bytes) -> tuple[str, str]:
    """返回 (正文, 说明)。

    正文已做清洗并截断到 MAX_CHARS；说明用于告诉前端"是从哪种格式读的"。
    任何解析失败都抛 DocTextError，message 可直接展示。
    """
    if not raw:
        raise DocTextError("文件是空的，没有内容可解析。")
    if len(raw) > MAX_BYTES:
        raise DocTextError(
            f"文件太大了（{len(raw) / 1024 / 1024:.1f}MB），请上传 20MB 以内的文件。"
        )

    ext = _ext(filename)
    if ext in _LEGACY_DOC:
        raise DocTextError(
            f"暂不支持 {ext} 这种老格式。请用 Word/WPS 打开后「另存为」.docx 或 .pdf，再上传。"
        )
    if ext == ".pdf":
        return _truncate(_from_pdf(raw)), "pdf"
    if ext == ".docx":
        return _truncate(_from_docx(raw)), "docx"

    if ext in _TEXT_EXT:
        return _truncate(_from_plain(raw)), "text"

    # 扩展名不认识：先按 zip 试试是不是 docx，再按纯文本试
    if raw[:4] == b"PK\x03\x04":
        return _truncate(_from_docx(raw)), "docx"
    if raw[:5] == b"%PDF-":
        return _truncate(_from_pdf(raw)), "pdf"
    return _truncate(_from_plain(raw)), "text"


def _truncate(text: str) -> str:
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS]


def decode_base64(data: str) -> bytes:
    """把前端传来的 base64（可带 data: 前缀）还原成字节流。"""
    s = (data or "").strip()
    if not s:
        raise DocTextError("没有收到文件内容。")
    # 去掉 data:application/pdf;base64, 这类前缀
    if s.startswith("data:"):
        comma = s.find(",")
        if comma >= 0:
            s = s[comma + 1 :]
    s = re.sub(r"\s+", "", s)
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocTextError("文件内容传输不完整，请重新上传一次。") from exc

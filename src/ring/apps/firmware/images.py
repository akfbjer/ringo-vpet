"""Explicit device/firmware catalog and bounded MCUboot package inspection."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
from zipfile import ZipFile

FIRMWARE_ROOT = Path(__file__).resolve().parents[4] / "firmware_release"
MAX_IMAGE_BYTES = 4 * 1024 * 1024
FAMILIES = {"ringo": "Ringo", "r1": "R1"}


def version_tuple(value):
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[+.](\d+))?", value)
    if not match:
        raise ValueError(f"无效固件版本：{value}")
    return tuple(int(v or 0) for v in match.groups())


@dataclass(frozen=True)
class Firmware:
    id: str
    device: str
    version: str
    label: str
    path: Path

    def summary(self):
        return dict(id=self.id, device=self.device, version=self.version,
                    label=self.label, filename=self.path.name, size=self.path.stat().st_size)


@dataclass(frozen=True)
class Image:
    data: bytes
    version: tuple[int, int, int, int]
    digest: bytes


def read_catalog(root=FIRMWARE_ROOT):
    root = Path(root).resolve()
    path = root / "catalog.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1 or not isinstance(data.get("firmwares"), list):
        raise ValueError("固件清单格式无效")
    result, ids = [], set()
    for entry in data["firmwares"]:
        identity, family = entry["id"], entry["device"]
        if not isinstance(identity, str) or not identity or identity in ids or family not in FAMILIES:
            raise ValueError("固件清单的 ID 或设备类型无效")
        version_tuple(entry["version"])
        filename = entry["file"]
        if not isinstance(filename, str) or not filename:
            raise ValueError("固件文件名无效")
        image_path = (root / filename).resolve()
        if not image_path.is_relative_to(root) or image_path.suffix.lower() != ".zip":
            raise ValueError("固件必须是 firmware_release 内的 ZIP 文件")
        if not image_path.is_file():
            raise ValueError(f"固件文件不存在：{filename}")
        ids.add(identity)
        result.append(Firmware(identity, family, entry["version"],
                               entry.get("label", entry["version"]), image_path))
    return result


def _tlvs(data, offset, magic):
    if offset < 32 or offset + 4 > len(data):
        raise ValueError("固件 TLV 头被截断")
    actual, size = struct.unpack_from("<HH", data, offset)
    end = offset + size
    if actual != magic or size < 4 or end > len(data):
        raise ValueError("固件 TLV 区域无效")
    values, cursor = [], offset + 4
    while cursor < end:
        if cursor + 4 > end:
            raise ValueError("固件 TLV 被截断")
        tag, length = struct.unpack_from("<HH", data, cursor)
        cursor += 4
        if cursor + length > end:
            raise ValueError("固件 TLV 长度无效")
        values.append((tag, data[cursor:cursor + length]))
        cursor += length
    return values, end


def inspect_image(data):
    if not 32 <= len(data) <= MAX_IMAGE_BYTES:
        raise ValueError("固件大小无效")
    magic, load, header_size, protected_size, size, flags = struct.unpack_from("<IIHHII", data)
    if magic != 0x96F3B83D or header_size < 32 or size == 0:
        raise ValueError("不是有效的 MCUboot 固件")
    if load != 0 or flags & (0x100 | 0x10 | 0x20):
        raise ValueError("固件不兼容当前 MCUboot Flash 布局")
    end = header_size + size
    if end > len(data):
        raise ValueError("固件镜像被截断")
    if protected_size:
        _, protected_end = _tlvs(data, end, 0x6908)
        if protected_end - end != protected_size:
            raise ValueError("固件保护区长度不一致")
        end = protected_end
    tlvs, _ = _tlvs(data, end, 0x6907)
    if not any(tag in (0x20, 0x22, 0x23, 0x24) and value for tag, value in tlvs):
        raise ValueError("固件缺少 MCUboot 签名")
    digest = None
    for tag, algorithm in ((0x12, "sha512"), (0x11, "sha384"), (0x10, "sha256")):
        values = [value for kind, value in tlvs if kind == tag]
        if values:
            if len(values) != 1 or len(values[0]) != hashlib.new(algorithm).digest_size:
                raise ValueError("固件 MCUboot 摘要格式无效")
            # Encrypted MCUboot packages carry a digest of the plaintext. Only
            # the bootloader can decrypt and authenticate those images.
            if not flags & 0x0C and values[0] != hashlib.new(algorithm, data[:end]).digest():
                raise ValueError("固件镜像内容与 MCUboot 摘要不一致")
            digest = values[0]
            break
    if digest is None:
        raise ValueError("固件缺少 MCUboot 镜像摘要")
    return Image(data, struct.unpack_from("<BBHI", data, 20), digest)


def load_image(firmware):
    with ZipFile(firmware.path) as archive:
        entries = archive.infolist()
        if len(entries) > 64:
            raise ValueError("固件包包含过多文件")
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)):
            raise ValueError("固件包包含重复文件名")
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in entry.filename:
                raise ValueError("固件包路径无效")
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > 64 * 1024:
            raise ValueError("固件包清单过大")
        manifest = json.loads(archive.read(manifest_info))
        files = manifest.get("files", [])
        if manifest.get("format-version") != 1 or len(files) != 1:
            raise ValueError("仅支持单应用 MCUboot 固件包")
        entry = files[0]
        if (entry.get("type") != "application" or entry.get("soc") != "nrf54l15"
                or entry.get("load_address") != 0xE000):
            raise ValueError("固件包的芯片或 Flash 布局不兼容")
        binary = archive.getinfo(entry["file"])
        if not binary.filename.endswith(".signed.bin") or binary.file_size > MAX_IMAGE_BYTES:
            raise ValueError("固件镜像文件无效")
        if entry.get("size") != binary.file_size:
            raise ValueError("固件包大小声明不一致")
        image = inspect_image(archive.read(binary))
        if (image.version != version_tuple(firmware.version)
                or image.version != version_tuple(entry["version_MCUBOOT"])):
            raise ValueError("固件清单版本与镜像版本不一致")
        return image

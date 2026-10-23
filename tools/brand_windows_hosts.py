"""Brand copies of the GUI interpreter while preserving its executable code and private DLL loading.

The original signed Python interpreter is unchanged. Copies have CAIO VERSIONINFO/icons
and no Authenticode signature. Resource data must fit the existing reserved .rsrc section.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def aligned(data: bytes) -> bytes:
    return data + b"\0" * (-len(data) % 4)


def version_block(
    key: str, value: bytes = b"", children: bytes = b"", *, text: bool = True
) -> bytes:
    length = len(value) // 2 if text else len(value)
    header = struct.pack("<HHH", 0, length, int(text)) + (key + "\0").encode("utf-16-le")
    block = aligned(header) + value
    if children:
        block = aligned(block) + children
    return struct.pack("<H", len(block)) + block[2:]


def version_info(name: str, description: str, version: str, copyright: str) -> bytes:
    revision = int(version.rsplit("dev", 1)[-1]) if "dev" in version else 0
    numeric = (2 << 16, revision)
    fixed = struct.pack(
        "<13I", 0xFEEF04BD, 0x10000, *numeric, *numeric, 0x3F, 0, 0x40004, 1, 0, 0, 0
    )
    strings = {
        "CompanyName": "CAIO",
        "FileDescription": description,
        "FileVersion": version,
        "InternalName": name.removesuffix(".exe"),
        "OriginalFilename": name,
        "ProductName": "CAIO - Central de Automacoes",
        "ProductVersion": version,
        "LegalCopyright": copyright,
        "Comments": "Private Python runtime; original Python license retained.",
    }
    table = b"".join(
        aligned(version_block(k, (v + "\0").encode("utf-16-le"))) for k, v in strings.items()
    )
    info = version_block("StringFileInfo", children=version_block("040904B0", children=table))
    translation = version_block("Translation", struct.pack("<HH", 0x409, 1200), text=False)
    var = version_block("VarFileInfo", children=translation)
    return version_block("VS_VERSION_INFO", fixed, aligned(info) + var, text=False)


def resource_section(resources: dict[tuple[int, int, int], bytes], rva: int) -> bytes:
    """Encode three-level integer resource identifiers, following IMAGE_RESOURCE_DIRECTORY."""
    tree: dict = {}
    for (kind, identifier, language), value in resources.items():
        tree.setdefault(kind, {}).setdefault(identifier, {})[language] = value
    directories: list[tuple[int, dict]] = []
    nodes: dict[int, int] = {}
    cursor = 0

    def reserve(node: dict) -> None:
        nonlocal cursor
        offset = cursor
        nodes[id(node)] = offset
        directories.append((offset, node))
        cursor += 16 + 8 * len(node)
        for value in node.values():
            if isinstance(value, dict):
                reserve(value)

    reserve(tree)
    leaves = [
        (offset + 16 + 8 * index, key, value)
        for offset, node in directories
        for index, (key, value) in enumerate(sorted(node.items()))
        if isinstance(value, bytes)
    ]
    data_offsets = {entry: cursor + index * 16 for index, (entry, _, _) in enumerate(leaves)}
    cursor += 16 * len(leaves)
    output = bytearray(cursor)
    for offset, node in directories:
        struct.pack_into("<IIHHHH", output, offset, 0, 0, 0, 0, 0, len(node))
        for index, (key, value) in enumerate(sorted(node.items())):
            entry = offset + 16 + 8 * index
            target = (
                (nodes[id(value)] | 0x80000000) if isinstance(value, dict) else data_offsets[entry]
            )
            struct.pack_into("<II", output, entry, key, target)
    for entry, _, value in leaves:
        output.extend(b"\0" * (-len(output) % 4))
        offset = len(output)
        output.extend(value)
        struct.pack_into("<IIII", output, data_offsets[entry], rva + offset, len(value), 0, 0)
    return bytes(output)


def brand(
    template: Path, target: Path, *, name: str, description: str, version: str, icon: Path
) -> None:
    import pefile

    pe = pefile.PE(str(template))
    section = next(section for section in pe.sections if section.Name.rstrip(b"\0") == b".rsrc")
    # Keep manifests/other runtime resources; replace only icons, group icons and version data.
    resources = {}
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id in {3, 14, 16}:
            continue
        for entry in kind.directory.entries:
            for language in entry.directory.entries:
                item = language.data.struct
                resources[(kind.id, entry.id, language.id)] = pe.get_data(
                    item.OffsetToData, item.Size
                )
    original = next(
        table.entries
        for group in pe.FileInfo
        for item in group
        if hasattr(item, "StringTable")
        for table in item.StringTable
    )
    copyright = original[b"LegalCopyright"].decode("utf-8")
    resources[(16, 1, 0x409)] = version_info(name, description, version, copyright)
    ico = icon.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    if reserved or kind != 1 or not 1 <= count <= 100:
        raise ValueError("Invalid application ICO")
    group = struct.pack("<HHH", 0, 1, count)
    for index in range(count):
        entry = ico[6 + index * 16 : 22 + index * 16]
        size, offset = struct.unpack_from("<II", entry, 8)
        if offset + size > len(ico):
            raise ValueError("Truncated ICO")
        resources[(3, index + 1, 0x409)] = ico[offset : offset + size]
        group += entry[:12] + struct.pack("<H", index + 1)
    resources[(14, 1, 0x409)] = group
    data = resource_section(resources, section.VirtualAddress)
    if len(data) > section.SizeOfRawData:
        raise ValueError("CAIO resources exceed the reserved interpreter resource section")
    pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].Size = len(data)
    # Branding invalidates the upstream signature: never advertise it as signed Python.
    security = pe.OPTIONAL_HEADER.DATA_DIRECTORY[4]
    certificate_offset = security.VirtualAddress
    security.VirtualAddress = security.Size = 0
    pe.OPTIONAL_HEADER.CheckSum = 0
    result = bytearray(pe.write())
    result[section.PointerToRawData : section.PointerToRawData + section.SizeOfRawData] = (
        data.ljust(section.SizeOfRawData, b"\0")
    )
    if certificate_offset:
        result = result[:certificate_offset]
    target.write_bytes(result)
    pe.close()
    check = pefile.PE(str(target))
    check.OPTIONAL_HEADER.CheckSum = check.generate_checksum()
    check.write(str(target))
    check.close()


def build_hosts(runtime: Path, icon: Path, version: str) -> None:
    from orquestrador_app.windows_hosts import HOST_DESCRIPTIONS

    for name, description in HOST_DESCRIPTIONS.items():
        brand(
            runtime / "pythonw.exe",
            runtime / name,
            name=name,
            description=description,
            version=version,
            icon=icon,
        )

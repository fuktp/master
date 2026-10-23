from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pytest
from openpyxl import Workbook

from orquestrador_app.files import Publisher
from orquestrador_app.io import digest


def workbook(path: Path, value: str = "new") -> None:
    book = Workbook()
    book.active.append(["Header"])
    book.active.append([value])
    book.save(path)
    book.close()


def publisher(tmp_path: Path, **retention: int) -> Publisher:
    return Publisher(
        tmp_path / "versions", {"count": 10, "days": 90, "bytes": 99999999, **retention}
    )


def test_valid_publication_backup_integrity_and_restore(tmp_path: Path) -> None:
    old, new = tmp_path / "final.xlsx", tmp_path / "download.xlsx"
    workbook(old, "old")
    workbook(new)
    previous = digest(old)
    service = publisher(tmp_path)
    result = service.publish(new, old, "run-1")
    assert result["sha256"] == digest(new)
    assert result["backup"]["sha256"] == previous
    record = service.versions()[0]
    service.validate_version(record)
    service.restore(record["id"], "restore-1")
    assert digest(old) == previous
    assert len(service.versions()) == 2


def test_backup_failure_prevents_destructive_replacement(tmp_path: Path) -> None:
    old, new = tmp_path / "final.xlsx", tmp_path / "download.xlsx"
    workbook(old, "old")
    workbook(new)
    previous = old.read_bytes()
    with patch.object(Publisher, "backup", side_effect=PermissionError("backup")):
        with pytest.raises(PermissionError):
            publisher(tmp_path).publish(new, old, "run")
    assert old.read_bytes() == previous


@pytest.mark.parametrize("content", [b"<html>login</html>", b"", b"PK\x00invalid"])
def test_invalid_download_preserves_old(tmp_path: Path, content: bytes) -> None:
    old, new = tmp_path / "final.xlsx", tmp_path / "download.xlsx"
    workbook(old, "old")
    previous = old.read_bytes()
    new.write_bytes(content)
    with pytest.raises(ValueError):
        publisher(tmp_path).publish(new, old, "run")
    assert old.read_bytes() == previous


def test_empty_sheet_and_partial_download_rejected(tmp_path: Path) -> None:
    path = tmp_path / "download.xlsx"
    book = Workbook()
    book.active.append(["Header"])
    book.save(path)
    book.close()
    with pytest.raises(ValueError):
        publisher(tmp_path).publish(path, tmp_path / "target.xlsx", "run")
    workbook(path)
    path.with_suffix(".xlsx.crdownload").touch()
    with pytest.raises(ValueError, match="parcial"):
        publisher(tmp_path).publish(path, tmp_path / "target.xlsx", "run")


def test_excel_lock_and_managed_retention_only(tmp_path: Path) -> None:
    target, source = tmp_path / "target.xlsx", tmp_path / "source.xlsx"
    workbook(target, "previous")
    workbook(source)
    original = target.read_bytes()
    service = publisher(tmp_path, count=1)
    import orquestrador_app.files as module

    replace = module.os.replace

    def blocked(incoming: object, destination: object) -> None:
        if Path(destination) == target:
            raise PermissionError("Excel lock")
        replace(incoming, destination)

    with patch.object(module.os, "replace", side_effect=blocked):
        with pytest.raises(PermissionError):
            service.publish(source, target, "run")
    assert target.read_bytes() == original
    unmanaged = service.backups / "unmanaged.json"
    unmanaged.write_text('{"owner":"someone_else"}')
    for index in range(4):
        workbook(source, str(index))
        service.publish(source, target, str(index))
    assert len(service.versions(target)) == 1
    assert unmanaged.exists()


def test_tampered_backup_rejected(tmp_path: Path) -> None:
    source, target = tmp_path / "new.xlsx", tmp_path / "final.xlsx"
    workbook(source)
    workbook(target, "old")
    service = publisher(tmp_path)
    service.publish(source, target, "run")
    record = service.versions()[0]
    (service.backups / (record["id"] + ".data")).write_bytes(b"tampered")
    with pytest.raises(ValueError):
        service.restore(record["id"], "restore")
    assert digest(target) == digest(source)


def test_events_idempotent_missing_keys_and_backup(tmp_path: Path) -> None:
    service = publisher(tmp_path)
    target = tmp_path / "historico_reports.csv"
    columns = ["Código", "Título"]
    rows = [{"Código": "01", "Título": "Um"}, {"Código": "01", "Título": "Um"}]
    kwargs = dict(
        columns=columns,
        target=target,
        run="run",
        keys=["Código"],
        separator=";",
        encoding="utf-8-sig",
    )
    assert service.merge_rows(rows, **kwargs)["appended"] == 1
    original = target.read_bytes()
    assert service.merge_rows(rows, **kwargs)["unchanged"]
    assert target.read_bytes() == original
    with pytest.raises(ValueError, match="inválida"):
        service.merge_rows([{"Código": "", "Título": "Sem chave"}], **kwargs)
    assert target.read_bytes() == original
    service.merge_rows([{"Código": "02", "Título": "Dois"}], **kwargs)
    assert len(service.versions(target)) == 1
    with target.open(encoding="utf-8-sig", newline="") as stream:
        assert len(list(csv.DictReader(stream, delimiter=";"))) == 2


def test_event_schema_conflict_preserves_history(tmp_path: Path) -> None:
    target = tmp_path / "history.csv"
    target.write_text("other;columns\n1;2\n")
    with pytest.raises(ValueError, match="Colunas"):
        publisher(tmp_path).merge_rows([{"ID": "1"}], ["ID"], target, "run", ["ID"], ";", "utf-8")
    assert target.read_text() == "other;columns\n1;2\n"

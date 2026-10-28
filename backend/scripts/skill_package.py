"""技能包运维 CLI：本地目录导入、导出、克隆到租户、列文件。

用法（backend 目录下）：
    uv run python -m scripts.skill_package import --dir ../skills/foo --name "技能名"
    uv run python -m scripts.skill_package import --dir ./foo --name "技能名" --tenant acme
    uv run python -m scripts.skill_package export --id 3 --output ./exported
    uv run python -m scripts.skill_package clone --id 3 --tenant acme --name "技能副本"
    uv run python -m scripts.skill_package list --id 3
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path
from uuid import UUID

from internal.application.skill_package_service import (
    SkillPackageService,
    should_skip_import_path,
)
from internal.application.skill_service import SkillService
from internal.domain.entity.request_context import RequestContext
from internal.domain.entity.tenant import Tenant
from internal.infrastructure.model.uow import SqlAlchemyUnitOfWork


def _open_scope(tenant_code: str | None) -> tuple[SqlAlchemyUnitOfWork, RequestContext]:
    """按租户编码构造工作单元与请求上下文；未指定时使用产品级作用域。"""
    tenant: Tenant | None = None
    if tenant_code:
        bootstrap = SqlAlchemyUnitOfWork()
        try:
            tenant = bootstrap.tenants.get_by_code(tenant_code)
        finally:
            bootstrap.close()
        if tenant is None:
            raise SystemExit(f"租户不存在：{tenant_code}")
    uow = SqlAlchemyUnitOfWork(tenant.id if tenant else None)
    context = RequestContext(scope="tenant" if tenant else "platform", tenant=tenant, host="cli")
    return uow, context


def _read_directory(directory: Path) -> dict[str, str]:
    """读取本地技能目录为 相对路径 -> 文本 的映射。"""
    if not directory.is_dir():
        raise SystemExit(f"目录不存在：{directory}")
    files: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(directory).as_posix()
        if should_skip_import_path(relative):
            continue
        try:
            files[relative] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise SystemExit(f"文件不是 UTF-8 文本：{relative}") from exc
    if not files:
        raise SystemExit(f"目录中没有可导入文件：{directory}")
    return files


def _import(args: argparse.Namespace) -> int:
    files = _read_directory(Path(args.dir))
    uow, context = _open_scope(args.tenant)
    try:
        package_service = SkillPackageService(uow, context)
        skill_service = SkillService(uow.skills, "技能", uow, context)
        existing = uow.skills.get_by_name(args.name)
        entry = files.get("SKILL.md", "")
        if existing:
            if not args.replace:
                raise SystemExit(f"技能已存在：{args.name}；如需覆盖请加 --replace")
            skill_service.update(
                existing.id,
                {
                    "name": args.name,
                    "description": args.description or existing.description,
                    "content": entry,
                    "config": existing.config,
                    "is_enabled": existing.is_enabled,
                },
            )
            skill_id = existing.id
        else:
            created = skill_service.create(
                {
                    "name": args.name,
                    "description": args.description or "",
                    "content": entry,
                    "config": {},
                    "is_enabled": True,
                }
            )
            skill_id = created.id
        replaced = package_service.replace_files(skill_id, files)
        print(
            f"imported skill_id={skill_id} files={len(replaced)} entry={'yes' if entry else 'no'}"
        )
    finally:
        uow.close()
    return 0


def _export(args: argparse.Namespace) -> int:
    uow, context = _open_scope(args.tenant)
    try:
        service = SkillPackageService(uow, context)
        data = service.export_zip(args.id)
    finally:
        uow.close()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    root = output.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            target = (output / info.filename).resolve()
            if root not in target.parents and target != root:
                raise SystemExit(f"压缩包路径非法：{info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    print(f"exported skill_id={args.id} output={output}")
    return 0


def _clone(args: argparse.Namespace) -> int:
    if not args.tenant:
        raise SystemExit("克隆必须指定 --tenant")
    uow, context = _open_scope(args.tenant)
    try:
        service = SkillPackageService(uow, context)
        created = service.clone_to_current_tenant(args.id, args.name)
        print(f"cloned source_id={args.id} new_skill_id={created.id} tenant={args.tenant}")
    finally:
        uow.close()
    return 0


def _list(args: argparse.Namespace) -> int:
    uow, context = _open_scope(args.tenant)
    try:
        service = SkillPackageService(uow, context)
        files = service.list_files(args.id)
        total_bytes = sum(file.size_bytes for file in files)
        print(f"skill_id={args.id} files={len(files)} bytes={total_bytes}")
        for file in files:
            print(f"  {file.path}\t{file.size_bytes}\t{file.content_hash[:12]}")
    finally:
        uow.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="技能包运维 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="从本地目录导入技能包")
    import_parser.add_argument("--dir", required=True, help="技能目录（含 SKILL.md）")
    import_parser.add_argument("--name", required=True, help="技能名称")
    import_parser.add_argument("--description", default="", help="技能描述")
    import_parser.add_argument("--tenant", default="", help="租户编码；省略为产品级")
    import_parser.add_argument("--replace", action="store_true", help="覆盖同名技能")
    import_parser.set_defaults(func=_import)

    export_parser = subparsers.add_parser("export", help="导出技能包到目录")
    export_parser.add_argument("--id", type=UUID, required=True, help="技能 ID")
    export_parser.add_argument("--output", required=True, help="导出目录")
    export_parser.add_argument("--tenant", default="", help="以租户作用域读取")
    export_parser.set_defaults(func=_export)

    clone_parser = subparsers.add_parser("clone", help="克隆技能到租户")
    clone_parser.add_argument("--id", type=UUID, required=True, help="源技能 ID")
    clone_parser.add_argument("--tenant", required=True, help="目标租户编码")
    clone_parser.add_argument("--name", default=None, help="副本名称")
    clone_parser.set_defaults(func=_clone)

    list_parser = subparsers.add_parser("list", help="列出技能包文件")
    list_parser.add_argument("--id", type=UUID, required=True, help="技能 ID")
    list_parser.add_argument("--tenant", default="", help="以租户作用域读取")
    list_parser.set_defaults(func=_list)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())

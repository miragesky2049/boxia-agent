"""权益统一读写用例：屏蔽 tenant_application_instance 与 tenant_resource_entitlement 两套存储。

只依赖 domain Protocol 端口（仓储/uow/异常），不 import infra 具体类；
apply_batch/purge 自管事务边界（批量原子性要求先全量校验再写入，
校验失败整体回滚返回 failed 明细，不做部分成功）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from internal.application.audit import record_audit
from internal.application.entitlement_notify import (
    NOTICE_MODE_RESTORED,
    NOTICE_MODE_REVOKED,
    record_change_notice,
)
from internal.domain.auth.service import AuthService
from internal.domain.entity.common import Page
from internal.domain.entity.entitlement import (
    ENTITLEMENT_OBJECT_TYPES,
    OBJECT_TYPE_APP,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_REVOKED,
    BatchPreview,
    BatchResult,
    EntitlementItem,
    EntitlementView,
    RemovePreviewItem,
)
from internal.domain.entity.entitlement_plan import PLAN_AUTH_TYPES, EntitlementPlan
from internal.domain.entity.request_context import RequestContext
from internal.domain.errors import ForbiddenError, NotFoundError, ValidationError
from internal.domain.repository.apps_protocols import (
    EntitlementPlanRepositoryProtocol,
    EntitlementRepositoryProtocol,
)
from internal.domain.repository.protocols import UnitOfWork

MODE_GRANT = "grant"
MODE_REVOKE = "revoke"
_MODES = (MODE_GRANT, MODE_REVOKE)

# P1-5 批量上限：服务层兜底校验（接口层 payload 另有 max_length）
_BATCH_MAX_ITEMS = 200


class EntitlementService:
    """平台侧权益开通/取消/预览/物理清理的用例编排 + 审计。"""

    def __init__(
        self,
        uow: UnitOfWork,
        repo: EntitlementRepositoryProtocol,
        context: RequestContext,
        *,
        auth_service: AuthService | None = None,
        plan_repo: EntitlementPlanRepositoryProtocol | None = None,
        revoke_strict: bool = False,
    ) -> None:
        self._uow = uow
        self._repo = repo
        self._context = context
        self._auth_service = auth_service
        self._plan_repo = plan_repo
        self._revoke_strict = revoke_strict

    # ========== 读侧 ==========
    def list_by_tenant(
        self,
        tenant_id: UUID,
        *,
        object_type: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Page[EntitlementView]:
        """租户权益分页列表（status 为读侧时间计算后的有效状态）。"""
        self._require_platform()
        if object_type is not None:
            self._validate_object_type(object_type)
        items, total = self._repo.list_by_tenant(
            tenant_id, object_type, status, keyword, page, page_size
        )
        return Page(items=items, total=total, page=page, page_size=page_size)

    def list_tenants_by_object(
        self, object_type: str, object_id: UUID, *, page: int = 1, page_size: int = 20
    ) -> Page[dict]:
        """对象反查持有权益的租户（平台资源运营视角）。"""
        self._require_platform()
        self._validate_object_type(object_type)
        items, total = self._repo.list_tenants_by_object(object_type, object_id, page, page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    # ========== 批量 ==========
    def preview(self, tenant_id: UUID, mode: str, items: list[EntitlementItem]) -> BatchPreview:
        """dry-run：不改库，给出将新增/将失效/无变化三组（D-3 影响提示）。"""
        self._require_platform()
        self._validate_mode(mode)
        self._validate_items(items)
        self._require_tenant(tenant_id)
        if mode == MODE_GRANT:
            return self._preview_grant(tenant_id, items)
        return self._preview_revoke(tenant_id, items)

    async def apply_batch(
        self,
        tenant_id: UUID,
        mode: str,
        items: list[EntitlementItem],
        *,
        reason: str = "",
        auth_type: str = "FORMAL",
        quota: dict[str, Any] | None = None,
        start_time: datetime | None = None,
        expire_time: datetime | None = None,
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> BatchResult:
        """批量开通/软失效：单事务，任一项校验失败整体回滚并返回 failed 明细。"""
        self._require_platform()
        self._validate_mode(mode)
        self._validate_items(items)
        try:
            self._require_tenant(tenant_id)
            failed, affected_counts = self._validate_batch(tenant_id, mode, items)
            if failed:
                self._uow.rollback()
                return BatchResult(updated=0, failed=tuple(failed))
            if mode == MODE_REVOKE and self._revoke_strict and any(affected_counts.values()):
                # 严格模式：权益仍被角色授权引用则整批拒绝（ENTITLEMENT_IN_USE，409 语义）
                raise ValidationError("权益仍被角色授权引用，严格模式下不可取消")
            # 写前快照先于写入读取，写后快照在提交前读取，两组快照使审计可还原一次批量操作
            before = self._snapshots(tenant_id, items)
            updated, affected = await self._write_batch(
                tenant_id,
                mode,
                items,
                reason=reason,
                auth_type=auth_type,
                quota=quota or {},
                start_time=start_time,
                expire_time=expire_time,
                granted_by=actor_id,
                affected_counts=affected_counts,
            )
            after = self._snapshots(tenant_id, items)
            was_active = sum(
                1 for snap in before if snap is not None and snap["status"] == STATUS_ACTIVE
            )
            if mode == MODE_GRANT:
                # 恢复语义下 revoked/expired/wait_effect 均计入 add，仅 active 无变化
                add, remove, unchanged = len(items) - was_active, 0, was_active
            else:
                # 校验已保证 revoke 项全部存在且未取消，整批都是失效
                add, remove, unchanged = 0, len(items), 0
            record_audit(
                self._uow,
                action="entitlement.batch",
                actor_id=actor_id,
                actor_username=actor_username,
                resource_type="entitlement",
                resource_id=str(tenant_id),
                ip=ip,
                user_agent=user_agent,
                tenant_id=tenant_id,
                detail={
                    "mode": mode,
                    "tenant_id": str(tenant_id),
                    "reason": reason,
                    "updated": updated,
                    "affected_role_grants": affected,
                    "items": [item.to_dict() for item in items],
                    "add": add,
                    "remove": remove,
                    "unchanged": unchanged,
                    "before": before,
                    "after": after,
                },
            )
            self._record_change_notices(
                tenant_id, mode, items, before, reason=reason, actor_username=actor_username
            )
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return BatchResult(updated=updated, failed=(), affected_role_grants=affected)

    # ========== 套餐模板（P3-3） ==========
    def list_plans(
        self, *, keyword: str | None = None, page: int = 1, page_size: int = 20
    ) -> Page[EntitlementPlan]:
        """套餐模板分页（平台级定义，不区分租户）。"""
        self._require_platform()
        items, total = self._require_plan_repo().list_page(keyword, page, page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)

    def get_plan(self, plan_id: UUID) -> EntitlementPlan:
        self._require_platform()
        plan = self._require_plan_repo().get(plan_id)
        if plan is None:
            raise NotFoundError("套餐不存在")
        return plan

    def create_plan(
        self,
        *,
        code: str,
        name: str,
        description: str,
        auth_type: str,
        duration_days: int | None,
        quota: dict[str, Any],
        items: list[EntitlementItem],
        actor_id: UUID,
        actor_username: str,
    ) -> UUID:
        """创建模板：code 唯一 + 条目对象存在性前置校验；定义行不落权益，返回模板 ID。"""
        self._require_platform()
        if not code.strip():
            raise ValidationError("套餐编码不能为空")
        if auth_type not in PLAN_AUTH_TYPES:
            raise ValidationError(f"不支持的套餐授权类型：{auth_type}")
        if duration_days is not None and duration_days <= 0:
            raise ValidationError("套餐期限天数必须为正数")
        if not items:
            raise ValidationError("套餐条目不能为空")
        keys = {(item.object_type, item.object_id) for item in items}
        if len(keys) != len(items):
            raise ValidationError("套餐条目重复")
        for item in items:
            self._validate_object_type(item.object_type)
            if self._repo.describe_object(item.object_type, item.object_id) is None:
                raise ValidationError(f"对象不存在：{item.object_type}/{item.object_id}")
        repo = self._require_plan_repo()
        if repo.get_by_code(code) is not None:
            raise ValidationError(f"套餐编码已存在：{code}")
        try:
            plan_id = repo.create(
                code=code,
                name=name,
                description=description,
                auth_type=auth_type,
                duration_days=duration_days,
                quota=quota,
                items=tuple(items),
            )
            record_audit(
                self._uow,
                action="entitlement.plan.create",
                actor_id=actor_id,
                actor_username=actor_username,
                resource_type="entitlement_plan",
                resource_id=str(plan_id),
                detail={
                    "code": code,
                    "name": name,
                    "auth_type": auth_type,
                    "duration_days": duration_days,
                    "quota": quota,
                    "items": [item.to_dict() for item in items],
                },
            )
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return plan_id

    def delete_plan(
        self,
        plan_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
    ) -> None:
        """删除模板定义（条目行外键级联）；已开通权益不受影响。"""
        self._require_platform()
        repo = self._require_plan_repo()
        plan = repo.get(plan_id)
        if plan is None:
            raise NotFoundError("套餐不存在")
        try:
            repo.delete(plan_id)
            record_audit(
                self._uow,
                action="entitlement.plan.delete",
                actor_id=actor_id,
                actor_username=actor_username,
                resource_type="entitlement_plan",
                resource_id=str(plan_id),
                detail={"code": plan.code, "name": plan.name},
            )
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise

    async def apply_plan(
        self,
        tenant_id: UUID,
        plan_id: UUID,
        *,
        start_time: datetime | None = None,
        expire_time: datetime | None = None,
        reason: str = "",
        actor_id: UUID,
        actor_username: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> BatchResult:
        """套餐开通：展开条目套用默认 auth_type/期限后复用 apply_batch 单事务批量。

        expire_time 未显式传入且模板有 duration_days 时，按生效起点顺延；
        弃用/不存在对象等按 apply_batch 语义整体拒绝并返回 failed 明细。
        """
        self._require_platform()
        plan = self._require_plan_repo().get(plan_id)
        if plan is None:
            raise NotFoundError("套餐不存在")
        if not plan.is_active:
            raise ValidationError("套餐已停用，不可开通")
        final_expire = expire_time
        if final_expire is None and plan.duration_days is not None:
            now = datetime.now(UTC)
            base = start_time if start_time is not None and start_time > now else now
            final_expire = base + timedelta(days=plan.duration_days)
        return await self.apply_batch(
            tenant_id,
            MODE_GRANT,
            list(plan.items),
            reason=reason or f"套餐开通：{plan.name}",
            auth_type=plan.auth_type,
            quota=plan.quota,
            start_time=start_time,
            expire_time=final_expire,
            actor_id=actor_id,
            actor_username=actor_username,
            ip=ip,
            user_agent=user_agent,
        )

    async def purge(
        self,
        tenant_id: UUID,
        object_type: str,
        object_id: UUID,
        *,
        actor_id: UUID,
        actor_username: str,
        actor_role_code: str,
        confirm: bool,
        reason: str = "",
    ) -> dict[str, Any]:
        """物理清除：先写快照审计，再删权益行并级联删角色授权行（P3-6）。

        仅平台 superadmin；confirm=True 为二次确认位；返回删除计数与 audit_id。
        """
        self._require_platform()
        if actor_role_code != "superadmin":
            raise ForbiddenError("权益清除仅限平台 superadmin")
        if not confirm:
            raise ValidationError("清除为不可逆操作，需显式二次确认")
        self._validate_object_type(object_type)
        try:
            self._require_tenant(tenant_id)
            snapshot = self._repo.get(tenant_id, object_type, object_id)
            role_grants = self._repo.affected_role_grants(tenant_id, object_type, object_id)
            deleted = self._repo.purge(tenant_id, object_type, object_id)
            role_grants_deleted = self._repo.purge_role_grants(tenant_id, object_type, object_id)
            if object_type == OBJECT_TYPE_APP and self._auth_service is not None:
                await self._auth_service.invalidate(tenant_id, object_id)
            audit_id = record_audit(
                self._uow,
                action="entitlement.purge",
                actor_id=actor_id,
                actor_username=actor_username,
                resource_type="entitlement",
                resource_id=str(tenant_id),
                tenant_id=tenant_id,
                detail={
                    "tenant_id": str(tenant_id),
                    "object_type": object_type,
                    "object_id": str(object_id),
                    "deleted": deleted,
                    "role_grants_deleted": role_grants_deleted,
                    "reason": reason,
                    "snapshot": self._view_snapshot(snapshot),
                    "role_grants_before": [
                        {
                            "role_id": str(g["role_id"]),
                            "role_name": g["role_name"],
                            "subject_type": g["subject_type"],
                        }
                        for g in role_grants
                    ],
                },
            )
            self._uow.commit()
        except Exception:
            self._uow.rollback()
            raise
        return {
            "deleted": deleted,
            "role_grants_deleted": role_grants_deleted,
            "audit_id": str(audit_id),
        }

    @staticmethod
    def _view_snapshot(view: EntitlementView | None) -> dict[str, Any] | None:
        if view is None:
            return None
        return {
            "object_type": view.object_type,
            "object_id": str(view.object_id),
            "name": view.name,
            "status": view.status,
            "auth_source": view.auth_source,
            "auth_type": view.auth_type,
            "start_time": view.start_time.isoformat() if view.start_time else None,
            "expire_time": view.expire_time.isoformat() if view.expire_time else None,
            "quota": view.quota,
            "remark": view.remark,
        }

    # ========== 生命周期（系统定时调用，无作用域门禁） ==========
    def process_resource_wait_effective(self, now: datetime) -> int:
        """到点把 tenant_resource_entitlement 的 wait_effect 行落库为 active（P3-1）。

        读侧 effective_status 已按时间计算，本流转只为把持久状态对齐、
        支撑统计与运维查询；返回值为本批激活条数。
        """
        rows = self._repo.list_resource_wait_effective(now)
        for row in rows:
            self._repo.update_entitlement_status(row["id"], STATUS_ACTIVE)
        return len(rows)

    def process_resource_expired(self, now: datetime) -> int:
        """到期把 tenant_resource_entitlement 的 active 行落库为 expired（P3-1）。"""
        rows = self._repo.list_resource_expired(now)
        for row in rows:
            self._repo.update_entitlement_status(row["id"], STATUS_EXPIRED)
        return len(rows)

    # ========== 内部：校验 ==========
    def _require_platform(self) -> None:
        # 权益写操作是平台运营职责；租户上下文命中即 403（SCOPE_FORBIDDEN 语义，§4.2）
        if not self._context.is_platform:
            raise ForbiddenError("权益操作仅限平台作用域")

    def _require_plan_repo(self) -> EntitlementPlanRepositoryProtocol:
        if self._plan_repo is None:
            raise RuntimeError("套餐仓储未装配（组合根遗漏 plan_repo）")
        return self._plan_repo

    def _require_tenant(self, tenant_id: UUID) -> None:
        tenant = self._uow.tenants.get_by_id(tenant_id)
        if tenant is None:
            raise NotFoundError("租户不存在")
        if not tenant.is_active:
            raise ValidationError("租户已停用，不可变更权益")

    @staticmethod
    def _validate_mode(mode: str) -> None:
        if mode not in _MODES:
            raise ValidationError(f"不支持的批量模式：{mode}")

    @staticmethod
    def _validate_object_type(object_type: str) -> None:
        if object_type not in ENTITLEMENT_OBJECT_TYPES:
            raise ValidationError(f"不支持的权益对象类型：{object_type}")

    @staticmethod
    def _validate_items(items: list[EntitlementItem]) -> None:
        if not items:
            raise ValidationError("批量项不能为空")
        if len(items) > _BATCH_MAX_ITEMS:
            raise ValidationError(f"批量项不能超过 {_BATCH_MAX_ITEMS} 个")

    def _validate_batch(
        self, tenant_id: UUID, mode: str, items: list[EntitlementItem]
    ) -> tuple[list[dict[str, Any]], dict[tuple[str, UUID], int]]:
        """全量预校验（先于任何写入执行）：返回失败明细 + revoke 各子项受影响角色授权数。"""
        failed: list[dict[str, Any]] = []
        affected_counts: dict[tuple[str, UUID], int] = {}
        seen: set[tuple[str, UUID]] = set()
        for item in items:
            self._validate_object_type(item.object_type)
            key = (item.object_type, item.object_id)
            if key in seen:
                failed.append(self._failed(item, "批量项重复"))
                continue
            seen.add(key)
            meta = self._repo.describe_object(item.object_type, item.object_id)
            if meta is None:
                failed.append(self._failed(item, "对象不存在"))
                continue
            if mode == MODE_GRANT:
                if meta["is_deprecated"]:
                    failed.append(self._failed(item, "资源已弃用，不可新开通"))
                continue
            view = self._repo.get(tenant_id, item.object_type, item.object_id)
            if view is None:
                failed.append(self._failed(item, "该对象当前无权益"))
                continue
            if view.status == STATUS_REVOKED:
                failed.append(self._failed(item, "权益已取消"))
                continue
            affected_counts[key] = len(
                self._repo.affected_role_grants(tenant_id, item.object_type, item.object_id)
            )
        return failed, affected_counts

    @staticmethod
    def _failed(item: EntitlementItem, reason: str) -> dict[str, Any]:
        return {
            "object_type": item.object_type,
            "object_id": str(item.object_id),
            "reason": reason,
        }

    # ========== 内部：preview ==========
    def _preview_grant(self, tenant_id: UUID, items: list[EntitlementItem]) -> BatchPreview:
        add: list[EntitlementView] = []
        unchanged: list[EntitlementView] = []
        for item in items:
            view = self._repo.get(tenant_id, item.object_type, item.object_id)
            if view is None:
                add.append(self._synth_view(item))
            elif view.status == STATUS_ACTIVE:
                unchanged.append(view)
            else:
                # 恢复语义：revoked/expired/wait_effect/suspended/disabled 均整行覆盖重写
                add.append(view)
        return BatchPreview(add=tuple(add), unchanged=tuple(unchanged))

    def _preview_revoke(self, tenant_id: UUID, items: list[EntitlementItem]) -> BatchPreview:
        remove: list[RemovePreviewItem] = []
        unchanged: list[EntitlementView] = []
        for item in items:
            view = self._repo.get(tenant_id, item.object_type, item.object_id)
            if view is None or view.status == STATUS_REVOKED:
                unchanged.append(view if view is not None else self._synth_view(item))
                continue
            grants = self._repo.affected_role_grants(tenant_id, item.object_type, item.object_id)
            remove.append(
                RemovePreviewItem(
                    view=view,
                    affected_role_grants=len(grants),
                    affected_role_names=tuple(str(g["role_name"]) for g in grants),
                )
            )
        return BatchPreview(remove=tuple(remove), unchanged=tuple(unchanged))

    def _synth_view(self, item: EntitlementItem) -> EntitlementView:
        """preview 展示用合成视图：对象元数据 + 乐观默认值，不代表持久状态。"""
        meta = self._repo.describe_object(item.object_type, item.object_id) or {}
        return EntitlementView(
            object_type=item.object_type,
            object_id=item.object_id,
            name=str(meta.get("name", "")),
            status=STATUS_ACTIVE,
            auth_source="OPS",
            auth_type="FORMAL",
            start_time=None,
            expire_time=None,
            quota={},
            remark="",
            granted_at=None,
            is_deprecated=bool(meta.get("is_deprecated", False)),
        )

    # ========== 内部：写入 ==========
    async def _write_batch(
        self,
        tenant_id: UUID,
        mode: str,
        items: list[EntitlementItem],
        *,
        reason: str,
        auth_type: str,
        quota: dict[str, Any],
        start_time: datetime | None,
        expire_time: datetime | None,
        granted_by: UUID,
        affected_counts: dict[tuple[str, UUID], int],
    ) -> tuple[int, int]:
        updated = 0
        affected = 0
        for item in items:
            if mode == MODE_GRANT:
                self._repo.grant(
                    tenant_id,
                    item,
                    auth_source="OPS",
                    auth_type=auth_type,
                    start_time=start_time,
                    expire_time=expire_time,
                    quota=quota,
                    remark=reason,
                    granted_by=granted_by,
                )
            else:
                self._repo.revoke(tenant_id, item.object_type, item.object_id, reason)
                affected += affected_counts.get((item.object_type, item.object_id), 0)
            updated += 1
            if item.object_type == OBJECT_TYPE_APP and self._auth_service is not None:
                await self._auth_service.invalidate(tenant_id, item.object_id)
        return updated, affected

    # ========== 内部：审计快照 ==========
    def _snapshots(
        self, tenant_id: UUID, items: list[EntitlementItem]
    ) -> list[dict[str, Any] | None]:
        """批量项读侧快照序列，与 items 同序；无权益记 None。"""
        return [
            self._snapshot(self._repo.get(tenant_id, item.object_type, item.object_id))
            for item in items
        ]

    @staticmethod
    def _snapshot(view: EntitlementView | None) -> dict[str, Any] | None:
        """权益视图转 JSON 安全 dict，供审计 before/after 还原操作前后状态。"""
        if view is None:
            return None
        return {
            "object_type": view.object_type,
            "object_id": str(view.object_id),
            "name": view.name,
            "status": view.status,
            "auth_source": view.auth_source,
            "auth_type": view.auth_type,
            "start_time": view.start_time.isoformat() if view.start_time else None,
            "expire_time": view.expire_time.isoformat() if view.expire_time else None,
            "granted_at": view.granted_at.isoformat() if view.granted_at else None,
            "quota": view.quota,
            "remark": view.remark,
        }

    def _record_change_notices(
        self,
        tenant_id: UUID,
        mode: str,
        items: list[EntitlementItem],
        before: list[dict[str, Any] | None],
        *,
        reason: str,
        actor_username: str,
    ) -> None:
        """P3-7：取消/恢复开通随同一事务写租户通知；新开通（无行或 active）不发。"""
        notice_mode = NOTICE_MODE_REVOKED if mode == MODE_REVOKE else NOTICE_MODE_RESTORED
        now = datetime.now(UTC)
        for item, snap in zip(items, before, strict=True):
            if snap is None:
                continue
            if mode == MODE_GRANT and snap["status"] not in (STATUS_REVOKED, STATUS_EXPIRED):
                continue
            record_change_notice(
                self._uow,
                tenant_id=tenant_id,
                object_type=item.object_type,
                object_id=str(item.object_id),
                name=str(snap["name"]),
                notice_mode=notice_mode,
                reason=reason,
                actor_username=actor_username,
                operated_at=now,
            )

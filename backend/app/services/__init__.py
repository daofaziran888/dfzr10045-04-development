"""领域服务注册表：通用资源路由按模块 key 分派到独立业务服务。"""
from __future__ import annotations

from app.services.base import BaseModuleService
from app.services.data_contract import DataContractService
from app.services.contract_version import ContractVersionService
from app.services.field_promise import FieldPromiseService
from app.services.consumer_app import ConsumerAppService
from app.services.subscription_plan import SubscriptionPlanService
from app.services.service_endpoint import ServiceEndpointService
from app.services.query_plan import QueryPlanService
from app.services.result_set import ResultSetService
from app.services.cache_policy import CachePolicyService
from app.services.rate_quota import RateQuotaService
from app.services.sla_target import SlaTargetService
from app.services.sla_breach import SlaBreachService
from app.services.reconcile_task import ReconcileTaskService
from app.services.dual_run import DualRunService
from app.services.diff_attrib import DiffAttribService
from app.services.dataset_release import DatasetReleaseService
from app.services.freshness_track import FreshnessTrackService
from app.services.sample_probe import SampleProbeService
from app.services.access_grant import AccessGrantService
from app.services.usage_meter import UsageMeterService
from app.services.incident_log import IncidentLogService
from app.services.contract_audit import ContractAuditService
from app.services.fetch_receipt import FetchReceiptService
from app.services.source_batch import SourceBatchService
from app.services.delivery_segment import DeliverySegmentService

SERVICES: dict[str, BaseModuleService] = {
    "data_contract": DataContractService(),
    "contract_version": ContractVersionService(),
    "field_promise": FieldPromiseService(),
    "consumer_app": ConsumerAppService(),
    "subscription_plan": SubscriptionPlanService(),
    "service_endpoint": ServiceEndpointService(),
    "query_plan": QueryPlanService(),
    "result_set": ResultSetService(),
    "cache_policy": CachePolicyService(),
    "rate_quota": RateQuotaService(),
    "sla_target": SlaTargetService(),
    "sla_breach": SlaBreachService(),
    "reconcile_task": ReconcileTaskService(),
    "dual_run": DualRunService(),
    "diff_attrib": DiffAttribService(),
    "dataset_release": DatasetReleaseService(),
    "freshness_track": FreshnessTrackService(),
    "sample_probe": SampleProbeService(),
    "access_grant": AccessGrantService(),
    "usage_meter": UsageMeterService(),
    "incident_log": IncidentLogService(),
    "contract_audit": ContractAuditService(),
    "fetch_receipt": FetchReceiptService(),
    "source_batch": SourceBatchService(),
    "delivery_segment": DeliverySegmentService(),
}


def service_for(module: str) -> BaseModuleService | None:
    return SERVICES.get(module)

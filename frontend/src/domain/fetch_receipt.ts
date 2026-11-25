/**
 * 订阅取数控制台的纯前端领域逻辑：调接口、拼展示行、判断列越界。
 *
 * 页面本身只负责渲染，列投影是否越界、续取资格如何呈现都在这里算，
 * 与后端「回执钉住可读列」的规则保持一致。
 */

export type FetchResult = {
  status: string
  message?: string
  reason?: string
  columns?: string[]
  rows?: Record<string, unknown>[]
  page?: number
  page_size?: number
  total_rows?: number
  total_pages?: number
  promise_version?: string
  promise_version_id?: string
  degraded?: boolean
  receipt?: ReceiptRow
  snapshot?: SnapshotRow
  segment?: SegmentRow
  /** 列权限收窄之后，回执列里不再可读的部分。 */
  leaked_columns?: string[]
}

export type ReceiptRow = {
  回执编号: string
  订阅编号: string
  消费方应用: string
  所属端点: string
  来源批次: string
  承诺版本: string
  可读列: string
  快照编号: string
  归属标识?: string
  已交付页数: string
  总页数: string
  status: string
}

export type SnapshotRow = {
  快照编号: string
  可读列?: string
  承诺版本?: string
  归属标识?: string
  status: string
}

export type SegmentRow = {
  分段编号: string
  页码: string
  承诺版本: string
  可读列: string
}

export type InspectionSegment = {
  分段编号: string
  页码: number
  承诺版本: string
  可读列: string[]
  实际列: string[]
  行数: number
  status: string
}

export type InspectionReport = {
  status: string
  message?: string
  receipt?: ReceiptRow
  承诺版本?: string
  可读列?: string[]
  快照编号?: string
  快照列?: string[]
  快照状态?: string
  段数?: number
  segments?: InspectionSegment[]
  越界分段?: { 分段编号: string; 越界列: string[]; 缺失列: string[] }[]
  已交付页数?: number
  总页数?: number
  下一段?: number | null
  可继续领取?: boolean
  后续领取说明?: string
}

export function splitColumns(value: string | undefined): string[] {
  return String(value ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

/** 逐段列出越界列：分段承诺版本或实际列超出回执可读列即视为越界。 */
export function findOutOfScopeSegments(
  receipt: Pick<ReceiptRow, '承诺版本'> & { 可读列: string },
  segments: InspectionSegment[],
): InspectionSegment[] {
  const allowed = new Set(splitColumns(receipt.可读列))
  return segments.filter(
    (segment) =>
      segment.承诺版本 !== receipt.承诺版本 ||
      segment.实际列.some((column) => !allowed.has(column)),
  )
}

/** 回执处于生效中且还有未交付分段时才允许继续领取。 */
export function canKeepFetching(
  receipt: Pick<ReceiptRow, 'status' | '已交付页数' | '总页数'>,
): boolean {
  return (
    receipt.status === '生效中' &&
    Number(receipt.已交付页数) < Number(receipt.总页数)
  )
}

/** 两个订阅对同一来源批的回执列做差集，用于展示各自的可见范围。 */
export function columnDifference(left: string[], right: string[]): string[] {
  const rightSet = new Set(right)
  return left.filter((column) => !rightSet.has(column))
}

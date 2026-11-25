import { request } from './client'
import type {
  FetchResult,
  InspectionReport,
} from '@/domain/fetch_receipt'

async function postJson<T>(path: string, payload: unknown): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  if (!response.ok) throw new Error(`接口返回 ${response.status}，取数未完成`)
  return (await response.json()) as T
}

export function fetchBySubscription(
  subscriptionId: string,
  endpointId: string,
  pageSize: number,
  today?: string,
): Promise<FetchResult> {
  return postJson<FetchResult>('/api/fetch/subscribe', {
    subscription_id: subscriptionId,
    endpoint_id: endpointId,
    page_size: pageSize,
    today: today || null,
  })
}

export function continueSegment(
  receiptId: string,
  today?: string,
): Promise<FetchResult> {
  return postJson<FetchResult>('/api/fetch/continue', {
    receipt_id: receiptId,
    today: today || null,
  })
}

export function refetchSnapshot(
  receiptId: string,
  page: number,
  today?: string,
): Promise<FetchResult> {
  return postJson<FetchResult>('/api/fetch/refetch', {
    receipt_id: receiptId,
    page,
    today: today || null,
  })
}

export async function inspectReceipt(
  receiptId: string,
  today?: string,
): Promise<InspectionReport> {
  const query = today ? `?today=${encodeURIComponent(today)}` : ''
  const response = await request(`/api/fetch/inspect/${encodeURIComponent(receiptId)}${query}`)
  if (!response.ok) throw new Error('回执复核读取失败')
  return (await response.json()) as InspectionReport
}

export function switchPromiseVersion(
  contractId: string,
  newVersion: string,
  retirePrevious = true,
): Promise<{ status: string; retired_versions: string[]; receipts_pending: string[] }> {
  return postJson('/api/fetch/switch-version', {
    contract_id: contractId,
    new_version: newVersion,
    retire_previous: retirePrevious,
  })
}

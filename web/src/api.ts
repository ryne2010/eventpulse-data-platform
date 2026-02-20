// Centralized API client for the EventPulse UI.
//
// Design goals:
// - Small + dependency-free (fetch + TypeScript types)
// - Optional X-Task-Token support for internal endpoints (Cloud Tasks, signed URLs, etc.)
// - Friendly errors for UI display

export type IngestionStatus = 'received' | 'processing' | 'success' | 'failed' | string

export type Ingestion = {
  id: string
  dataset: string
  source: string | null
  filename: string | null
  file_ext: string | null
  sha256: string
  raw_path: string
  raw_generation?: number | null
  received_at: string | null
  processing_started_at?: string | null
  processing_heartbeat_at?: string | null
  processing_attempts?: number
  status: IngestionStatus
  error: string | null
  processed_at: string | null
  quality_passed?: boolean | null
}

export type QualityReport = Record<string, any>

export type LineageArtifact = {
  artifact: Record<string, any>
  created_at: string
}

export type Meta = {
  version: string
  ok: boolean
  runtime: {
    queue: string
    storage_backend: string
    raw_data_dir: string
    raw_gcs_bucket: string
    raw_gcs_prefix: string
    contracts_dir: string
    incoming_dir: string
    archive_dir: string
    task_auth_mode: 'token' | 'iam' | string
    ingest_auth_mode?: 'none' | 'token' | string
    ingest_token_configured?: boolean
    edge_auth_mode?: 'none' | 'token' | string
    edge_allowed_datasets?: string[]
    enable_edge_signed_urls?: boolean
    enable_edge_media?: boolean
    edge_media_gcs_bucket?: string
    edge_media_gcs_prefix?: string
    edge_media_allowed_exts?: string[]
    edge_enroll_enabled?: boolean
    edge_offline_threshold_seconds?: number
    enable_signed_urls: boolean
    signed_url_expires_seconds: number
    require_signed_url_sha256?: boolean
    enable_gcs_event_ingestion: boolean
    enable_demo_endpoints?: boolean
    enable_ingest_from_path?: boolean
    enable_contract_write?: boolean
    enable_incoming_list?: boolean
  }
}

export type DbTableStat = {
  name: string
  size_bytes: number
  row_estimate: number
  error?: string
}

export type DbStats = {
  captured_at: string
  database: { name: string; size_bytes: number }
  tables: DbTableStat[]
}

export type DeviceInfo = {
  device_id: string
  label?: string | null
  metadata?: Record<string, any> | null
  token_updated_at?: string | null
  token_iterations?: number | null
  created_at?: string | null
  updated_at?: string | null
  revoked_at?: string | null
  last_seen_at?: string | null
  last_seen_ip?: string | null
  last_user_agent?: string | null
}

export type DeviceLatestReading = {
  device_id: string
  sensor: string
  ts?: string | null
  value?: number | null
  units?: string | null
  lat?: number | null
  lon?: number | null
  battery_v?: number | null
  rssi_dbm?: number | null
  firmware_version?: string | null
  status?: string | null
  message?: string | null
  severity_num?: number | null
  severity?: string | null
  alert_type?: string | null
  _loaded_at?: string | null
  _ingestion_id?: string | null
}



export type DeviceMediaItem = {
  id: string
  device_id: string
  media_type: 'image' | 'video' | string
  gcs_bucket: string
  object_name: string
  gcs_uri: string
  content_type?: string | null
  bytes?: number | null
  captured_at?: string | null
  notes?: string | null
  created_at: string
}
export type PruneRequest = {
  dry_run?: boolean
  confirm?: string
  audit_older_than_days?: number
  audit_limit?: number
  ingestions_older_than_days?: number
  ingestions_limit?: number
}

export type PruneResult = {
  ok: boolean
  dry_run: boolean
  audit: any | null
  ingestions: any | null
}

export type CuratedSample = {
  rows: Record<string, any>[]
  limit: number
  table_exists: boolean
}

export type SchemaHistory = {
  dataset: string
  items: {
    schema_hash: string
    schema_json: any
    first_seen_at: string | null
    last_seen_at: string | null
  }[]
}

export type DatasetSummary = {
  dataset: string
  has_contract: boolean
  contract_sha256?: string | null
  contract_description?: string | null
  primary_key?: string | null
  drift_policy?: string | null
  ingestion_count: number
  last_received_at?: string | null
  last_processed_at?: string | null
  counts: {
    received: number
    processing: number
    success: number
    failed: number
  }
  curated_table_exists: boolean
  latest_schema_hash?: string | null
  schema_last_seen_at?: string | null
}

export type DatasetContractResponse = {
  dataset: string
  contract: {
    sha256: string
    filename: string
    description: string
    primary_key: string | null
    drift_policy: string | null
    quality: any
    columns: Record<string, any>
    raw_yaml: string
  }
}

export type MartItem = {
  name: string
  view: string
  description: string
  exists: boolean
}

export type MartListResponse = {
  dataset: string
  items: MartItem[]
}

export type MartDataResponse = {
  dataset: string
  mart: string
  view: string
  rows: Record<string, any>[]
  limit: number
}

export type SeedResponse = {
  ok: boolean
  rows: number
  seed_id: string
  per_ingestion_max: number
  ingestions: { ingestion_id: string; job_id: string; rows: number }[]
}

export type IngestionPreview = {
  ingestion_id: string
  dataset: string
  table_exists: boolean
  rows: Record<string, any>[]
  limit: number
}

export type PlatformStats = {
  hours: number
  totals: Record<string, number>
  recent: Record<string, number>
  activity: { hour: string; received: number; processing: number; success: number; failed: number; other: number }[]
  total_ingestions: number
  backlog: number
  stuck_processing: number
  success_rate: number | null
}

export type AuditEvent = {
  id: string
  event_type: string
  actor: string | null
  dataset: string | null
  ingestion_id: string | null
  details: Record<string, any>
  created_at: string
}

export type AuditEventsResponse = { items: AuditEvent[] }

export type QualityTrendPoint = {
  bucket: string
  total: number
  passed: number
  failed: number
  avg_rows: number
}

export type QualityTrendResponse = {
  dataset: string | null
  hours: number
  bucket_minutes: number
  series: QualityTrendPoint[]
}

export type IncomingFile = {
  relative_path: string
  size_bytes: number
  modified_at: string
}

export type IncomingListResponse = { items: IncomingFile[]; limit: number }

export type DataProduct = {
  dataset: string
  name: string
  kind: string
  description: string
  view: string
  exists: boolean
  endpoint: string
  version?: string | null
  contract_sha256?: string | null
}

export type DataProductsResponse = { items: DataProduct[]; dataset_count: number; count: number }

export type ContractValidateResponse = {
  ok: boolean
  contract: {
    dataset: string
    description: string
    primary_key: string | null
    drift_policy: string | null
    quality: any
    columns: Record<string, any>
  }
}

export type ContractUpdateResponse = DatasetContractResponse


export type GcsSignedUrlRequest = {
  dataset: string
  filename: string
  sha256?: string
  source?: string
}

export type GcsSignedUrlResponse = {
  method: 'PUT'
  upload_url: string
  required_headers: Record<string, string>
  gcs_uri: string
  object_name: string
  expires_in_seconds: number
  event_ingestion_enabled: boolean
}

function getTaskToken(): string | null {
  try {
    const v = localStorage.getItem('eventpulse.taskToken')
    return v && v.trim() ? v.trim() : null
  } catch {
    return null
  }
}

function getIngestToken(): string | null {
  try {
    const v = localStorage.getItem('eventpulse.ingestToken')
    return v && v.trim() ? v.trim() : null
  } catch {
    return null
  }
}

export function setTaskToken(token: string) {
  try {
    if (!token.trim()) localStorage.removeItem('eventpulse.taskToken')
    else localStorage.setItem('eventpulse.taskToken', token.trim())
  } catch {
    // ignore
  }
}

export function setIngestToken(token: string) {
  try {
    if (!token.trim()) localStorage.removeItem('eventpulse.ingestToken')
    else localStorage.setItem('eventpulse.ingestToken', token.trim())
  } catch {
    // ignore
  }
}

export function getTaskTokenForUi(): string {
  return getTaskToken() ?? ''
}

export function getIngestTokenForUi(): string {
  return getIngestToken() ?? ''
}

function withAuthHeaders(headers?: HeadersInit): HeadersInit {
  const token = getTaskToken()
  if (!token) return headers ?? {}
  return { ...(headers ?? {}), 'X-Task-Token': token }
}

function withIngestHeaders(headers?: HeadersInit): HeadersInit {
  const token = getIngestToken()
  if (!token) return headers ?? {}
  return { ...(headers ?? {}), 'X-Ingest-Token': token }
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: withAuthHeaders({
      'content-type': 'application/json',
      ...(init?.headers || {}),
    }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed: ${res.status}`)
  }
  return (await res.json()) as T
}

async function rawFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, headers: withAuthHeaders(init?.headers) })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed: ${res.status}`)
  }
  return (await res.json()) as T
}

export const api = {
  // Meta / ops
  meta: () => jsonFetch<Meta>('/api/meta'),
  stats: (hours = 24) => jsonFetch<PlatformStats>(`/api/stats?hours=${hours}`),

  // Observability / governance
  auditEvents: (limit = 200, dataset?: string, ingestion_id?: string, event_type?: string, actor?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (dataset && dataset !== 'all') params.set('dataset', dataset)
    if (ingestion_id) params.set('ingestion_id', ingestion_id)
    if (event_type && event_type !== 'all') params.set('event_type', event_type)
    if (actor) params.set('actor', actor)
    return jsonFetch<AuditEventsResponse>(`/api/audit_events?${params.toString()}`)
  },

  qualityTrend: (hours = 168, bucket_minutes = 60, dataset?: string) => {
    const params = new URLSearchParams({ hours: String(hours), bucket_minutes: String(bucket_minutes) })
    if (dataset && dataset !== 'all') params.set('dataset', dataset)
    return jsonFetch<QualityTrendResponse>(`/api/trends/quality?${params.toString()}`)
  },

  dataProducts: (limit_datasets = 200) =>
    jsonFetch<DataProductsResponse>(`/api/data_products?limit_datasets=${limit_datasets}`),


  // Datasets
  listDatasets: (limit = 100) => jsonFetch<{ items: DatasetSummary[] }>(`/api/datasets?limit=${limit}`),
  getContract: (dataset: string) => jsonFetch<DatasetContractResponse>(`/api/datasets/${dataset}/contract`),
  validateContract: (raw_yaml: string) =>
    jsonFetch<ContractValidateResponse>('/api/contracts/validate', {
      method: 'POST',
      body: JSON.stringify({ raw_yaml }),
    }),
  updateContract: (dataset: string, raw_yaml: string) =>
    jsonFetch<ContractUpdateResponse>(`/api/datasets/${dataset}/contract`, {
      method: 'PUT',
      body: JSON.stringify({ raw_yaml }),
    }),
  schemaHistory: (dataset: string, limit = 20) => jsonFetch<SchemaHistory>(`/api/datasets/${dataset}/schemas?limit=${limit}`),
  curatedSample: (dataset: string, limit = 20) =>
    jsonFetch<CuratedSample>(`/api/datasets/${dataset}/curated/sample?limit=${limit}`),
  listMarts: (dataset: string) => jsonFetch<MartListResponse>(`/api/datasets/${dataset}/marts`),
  getMart: (dataset: string, mart: string, limit = 200) =>
    jsonFetch<MartDataResponse>(`/api/datasets/${dataset}/marts/${mart}?limit=${limit}`),

  // Ingestions
  listIngestions: (limit = 50, dataset?: string, status?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (dataset && dataset !== 'all') params.set('dataset', dataset)
    if (status && status !== 'all') params.set('status', status)
    return jsonFetch<{ items: Ingestion[] }>(`/api/ingestions?${params.toString()}`)
  },
  getIngestion: (id: string) => jsonFetch<{ ingestion: Ingestion; quality_report: QualityReport }>(`/api/ingestions/${id}`),
  getLineage: (id: string) => jsonFetch<LineageArtifact>(`/api/ingestions/${id}/lineage`),
  ingestionPreview: (id: string, limit = 10) => jsonFetch<IngestionPreview>(`/api/ingestions/${id}/preview?limit=${limit}`),
  replayIngestion: (id: string) =>
    jsonFetch<{ ok: boolean; replay_of: string; ingestion_id: string; job_backend: string; job_id: string }>(
      `/api/ingestions/${id}/replay`,
      { method: 'POST' },
    ),

  // Upload/ingest helpers
  uploadDirect: async (dataset: string, file: File, source = 'ui') => {
    const params = new URLSearchParams({ dataset, filename: file.name, source })
    return rawFetch<{ ingestion_id: string; job_backend: string; job_id: string; raw_path: string }>(
      `/api/ingest/upload?${params.toString()}`,
      {
        method: 'POST',
        headers: withIngestHeaders({ 'Content-Type': 'application/octet-stream' }),
        body: file,
      },
    )
  },

  gcsSignedUrl: (payload: GcsSignedUrlRequest) =>
    jsonFetch<GcsSignedUrlResponse>('/api/uploads/gcs_signed_url', { method: 'POST', body: JSON.stringify(payload) }),

  ingestFromGcs: (dataset: string, gcs_uri: string, source = 'ui') =>
    jsonFetch<any>('/api/ingest/from_gcs', { method: 'POST', body: JSON.stringify({ dataset, gcs_uri, source }) }),

  ingestFromPath: (dataset: string, relative_path: string, source = 'ui') =>
    jsonFetch<any>('/api/ingest/from_path', { method: 'POST', body: JSON.stringify({ dataset, relative_path, source }) }),

  incomingList: (limit = 200) => jsonFetch<IncomingListResponse>(`/api/incoming/list?limit=${limit}`),

  // Ops (internal)
  pingDb: () => jsonFetch<any>('/api/ping'),
  reclaimStuck: (older_than_seconds = 600, limit = 50) =>
    jsonFetch<any>('/internal/admin/reclaim_stuck', {
      method: 'POST',
      body: JSON.stringify({ older_than_seconds, limit }),
    }),
  dbStats: () => jsonFetch<DbStats>('/internal/admin/db_stats'),

  prune: (payload: PruneRequest) =>
    jsonFetch<PruneResult>('/internal/admin/prune', {
      method: 'POST',
      body: JSON.stringify(payload ?? {}),
    }),

  // Devices (internal admin)
  listDevices: (limit = 200) =>
    jsonFetch<{ ok: boolean; devices: DeviceInfo[]; limit: number }>(`/internal/admin/devices?limit=${limit}`),
  getDevice: (device_id: string) =>
    jsonFetch<{ ok: boolean; device: DeviceInfo }>(`/internal/admin/devices/${encodeURIComponent(device_id)}`),
  deviceTelemetry: (device_id: string, limit = 200) =>
    jsonFetch<{ ok: boolean; device_id: string; rows: Record<string, any>[]; limit: number; table_exists: boolean }>(
      `/internal/admin/devices/${encodeURIComponent(device_id)}/telemetry?limit=${limit}`,
    ),
  deviceLatestReadings: (device_id: string, limit = 200) =>
    jsonFetch<{ ok: boolean; device_id: string; rows: DeviceLatestReading[]; limit: number; view_exists: boolean }>(
      `/internal/admin/devices/${encodeURIComponent(device_id)}/latest_readings?limit=${limit}`,
    ),
  createDevice: (payload: { device_id: string; label?: string; metadata?: Record<string, any> }) =>
    jsonFetch<{ ok: boolean; device: DeviceInfo; device_token: string }>('/internal/admin/devices', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  rotateDeviceToken: (device_id: string) =>
    jsonFetch<{ ok: boolean; device_id: string; device_token: string }>(
      `/internal/admin/devices/${encodeURIComponent(device_id)}/rotate_token`,
      { method: 'POST' },
    ),
  revokeDevice: (device_id: string) =>
    jsonFetch<{ ok: boolean; device_id: string; revoked: boolean }>(
      `/internal/admin/devices/${encodeURIComponent(device_id)}/revoke`,
      { method: 'POST' },
    ),




  // Media (internal admin)
  listMedia: (limit = 200, device_id?: string) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (device_id) params.set('device_id', device_id)
    return jsonFetch<{ ok: boolean; items: DeviceMediaItem[]; limit: number; device_id?: string }>(
      `/internal/admin/media?${params.toString()}`,
    )
  },

  getMedia: (media_id: string) =>
    jsonFetch<{ ok: boolean; item: DeviceMediaItem }>(
      `/internal/admin/media/${encodeURIComponent(media_id)}`,
    ),

  mediaReadSignedUrl: (gcs_uri: string, expires_in_seconds = 300) =>
    jsonFetch<{ ok: boolean; download_url: string; expires_in_seconds: number }>(
      '/internal/admin/media/gcs_read_signed_url',
      { method: 'POST', body: JSON.stringify({ gcs_uri, expires_in_seconds }) },
    ),
  // Demo
  seedParcels: (limit = 50) =>
    jsonFetch<SeedResponse>(`/api/demo/seed/parcels?limit=${limit}&per_ingestion_max=15`, { method: 'POST' }),

  seedEdgeTelemetry: (limit = 200) =>
    jsonFetch<SeedResponse>(`/api/demo/seed/edge_telemetry?limit=${limit}&per_ingestion_max=200`, { method: 'POST' }),
}

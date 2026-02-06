export type Ingestion = {
  id: string
  dataset: string
  source: string | null
  filename: string | null
  file_ext: string | null
  sha256: string
  raw_path: string
  received_at: string
  status: 'received' | 'processing' | 'success' | 'failed'
  error: string | null
  processed_at: string | null
}

export type QualityReport = Record<string, any>

export type Meta = {
  version: string
  ok: boolean
  runtime: {
    queue: string
    raw_data_dir: string
    contracts_dir: string
    incoming_dir: string
    archive_dir: string
  }
}

export type CuratedSample = {
  rows: Record<string, any>[]
  limit: number
  table_exists: boolean
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

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: {
      'content-type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `Request failed: ${res.status}`)
  }
  return (await res.json()) as T
}

export const api = {
  meta: () => jsonFetch<Meta>('/api/meta'),
  listIngestions: (limit = 50) => jsonFetch<{ items: Ingestion[] }>(`/api/ingestions?limit=${limit}`),
  getIngestion: (id: string) => jsonFetch<{ ingestion: Ingestion; quality_report: QualityReport }>(`/api/ingestions/${id}`),
  ingestionPreview: (id: string, limit = 10) => jsonFetch<IngestionPreview>(`/api/ingestions/${id}/preview?limit=${limit}`),
  curatedSample: (dataset: string, limit = 20) =>
    jsonFetch<CuratedSample>(`/api/datasets/${dataset}/curated/sample?limit=${limit}`),
  seedParcels: (limit = 50) =>
    jsonFetch<SeedResponse>(`/api/demo/seed/parcels?limit=${limit}&per_ingestion_max=15`, { method: 'POST' }),
}

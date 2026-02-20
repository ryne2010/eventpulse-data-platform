import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import {
  api,
  type ContractValidateResponse,
  type DatasetContractResponse,
  type DatasetSummary,
  type Ingestion,
  type MartDataResponse,
  type MartItem,
  type SchemaHistory,
} from '../api'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  Input,
  Label,
  Page,
  Separator,
  Tabs,
  Textarea,
} from '../portfolio-ui'

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.replace('T', ' ').replace('Z', 'Z')
}

function shortHash(h?: string | null) {
  if (!h) return '—'
  return `${h.slice(0, 10)}…`
}

function statusBadge(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'success' || s === 'loaded') return <Badge variant="success">success</Badge>
  if (s === 'processing') return <Badge variant="warning">processing</Badge>
  if (s === 'received') return <Badge variant="outline">received</Badge>
  if (s.startsWith('failed')) return <Badge variant="destructive">failed</Badge>
  return <Badge variant="secondary">{s || '—'}</Badge>
}

function qualityBadge(passed: boolean | null | undefined, status: string) {
  const s = (status || '').toLowerCase()
  if (passed === true) return <Badge variant="success">quality ok</Badge>
  if (passed === false) return <Badge variant="destructive">quality fail</Badge>
  if (s === 'success' || s === 'loaded' || s.startsWith('failed')) return <Badge variant="outline">quality —</Badge>
  return <Badge variant="secondary">quality n/a</Badge>
}

function jsonCell(v: any) {
  if (v === null || v === undefined) return <span className="text-muted-foreground">—</span>
  if (typeof v === 'object') return <span className="font-mono text-xs text-muted-foreground">{JSON.stringify(v)}</span>
  return <span className="text-muted-foreground">{String(v)}</span>
}

function buildDynamicColumns(rows: Record<string, any>[]): ColumnDef<Record<string, any>>[] {
  const keys = rows.length ? Object.keys(rows[0]) : []
  return keys.map((k) => ({ header: k, accessorKey: k, cell: (info) => jsonCell(info.getValue()) }))
}

function Section(props: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{props.title}</CardTitle>
        {props.description ? <CardDescription>{props.description}</CardDescription> : null}
      </CardHeader>
      <CardContent className="space-y-3">{props.children}</CardContent>
    </Card>
  )
}

type ContractDiff = {
  missing_in_observed: string[]
  extra_in_observed: string[]
  type_mismatches: { name: string; contract: string; observed: string }[]
}

function computeContractDiff(contract: DatasetContractResponse['contract'] | null, schema: any | null): ContractDiff {
  const contractCols = contract?.columns ? Object.entries(contract.columns) : []
  const contractSet = new Set(contractCols.map(([k]) => k))

  const observedCols: { name: string; logical_type?: string }[] = Array.isArray(schema?.columns) ? schema.columns : []
  const observedSet = new Set(observedCols.map((c) => String(c.name)))

  const missing = [...contractSet].filter((c) => !observedSet.has(c)).sort()
  const extra = [...observedSet].filter((c) => !contractSet.has(c)).sort()

  const typeMismatches: { name: string; contract: string; observed: string }[] = []
  for (const [name, spec] of contractCols) {
    if (!observedSet.has(name)) continue
    const expected = String((spec as any)?.type ?? '').toLowerCase()
    const obs = observedCols.find((c) => String(c.name) === name)
    const observed = String(obs?.logical_type ?? '').toLowerCase()
    if (expected && observed && expected !== observed) {
      typeMismatches.push({ name, contract: expected, observed })
    }
  }

  typeMismatches.sort((a, b) => a.name.localeCompare(b.name))

  return { missing_in_observed: missing, extra_in_observed: extra, type_mismatches: typeMismatches }
}

function GeoScatter(props: { rows: Record<string, any>[]; height?: number }) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null)
  const height = props.height ?? 420

  const points = React.useMemo(() => {
    const out: { lat: number; lon: number; metric?: number | null }[] = []
    for (const r of props.rows ?? []) {
      const lat = Number(r.lat)
      const lon = Number(r.lon)
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue
      // Generic metric for point sizing (parcels: sale_price, telemetry: value)
      const metricRaw = (r as any).sale_price ?? (r as any).value
      const metric = metricRaw === null || metricRaw === undefined ? null : Number(metricRaw)
      out.push({ lat, lon, metric: Number.isFinite(metric as any) ? (metric as number) : null })
    }
    return out
  }, [props.rows])

  React.useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const width = canvas.clientWidth
    const h = canvas.clientHeight

    canvas.width = Math.floor(width * dpr)
    canvas.height = Math.floor(h * dpr)
    ctx.scale(dpr, dpr)

    ctx.clearRect(0, 0, width, h)

    if (!points.length) {
      ctx.fillStyle = 'rgba(0,0,0,0.55)'
      ctx.font = '14px ui-sans-serif, system-ui'
      ctx.fillText('No geo points available yet.', 12, 24)
      return
    }

    const lats = points.map((p) => p.lat)
    const lons = points.map((p) => p.lon)
    const minLat = Math.min(...lats)
    const maxLat = Math.max(...lats)
    const minLon = Math.min(...lons)
    const maxLon = Math.max(...lons)

    const pad = 18
    const usableW = Math.max(1, width - pad * 2)
    const usableH = Math.max(1, h - pad * 2)

    const toX = (lon: number) => {
      if (maxLon === minLon) return width / 2
      return pad + ((lon - minLon) / (maxLon - minLon)) * usableW
    }

    const toY = (lat: number) => {
      if (maxLat === minLat) return h / 2
      // invert so north is up
      return pad + (1 - (lat - minLat) / (maxLat - minLat)) * usableH
    }

    // frame
    ctx.strokeStyle = 'rgba(0,0,0,0.20)'
    ctx.lineWidth = 1
    ctx.strokeRect(pad, pad, usableW, usableH)

    // points
    for (const p of points) {
      const x = toX(p.lon)
      const y = toY(p.lat)

      // Scale point radius by metric (log-ish), but keep it subtle.
      const metric = (p as any).metric ?? 0
      const r = metric > 0 ? Math.max(1.5, Math.min(4.5, Math.log10(metric + 10))) : 1.8

      ctx.fillStyle = 'rgba(59, 130, 246, 0.55)'
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
    }

    // caption
    ctx.fillStyle = 'rgba(0,0,0,0.60)'
    ctx.font = '12px ui-sans-serif, system-ui'
    ctx.fillText(`points: ${points.length}   lat: ${minLat.toFixed(3)}…${maxLat.toFixed(3)}   lon: ${minLon.toFixed(3)}…${maxLon.toFixed(3)}`, 12, h - 10)
  }, [points])

  return (
    <div className="w-full">
      <div className="rounded-md border bg-muted/10 overflow-hidden">
        <canvas ref={canvasRef} className="w-full" style={{ height }} />
      </div>
      <div className="text-xs text-muted-foreground mt-2">
        Note: this is a lightweight scatter plot (no map tiles). It exists to demonstrate the geospatial analytics "slice" and works for any dataset with a geo_points mart.
      </div>
    </div>
  )
}

export default function DatasetPage() {
  const params = useParams({ from: '/datasets/$dataset' })
  const dataset = String(params.dataset)

  const nav = useNavigate()
  const qc = useQueryClient()

  const [tab, setTab] = React.useState<'overview' | 'contract' | 'schemas' | 'curated' | 'marts' | 'map'>('overview')
  const [selectedSchema, setSelectedSchema] = React.useState<any | null>(null)
  const [curatedLimit, setCuratedLimit] = React.useState(25)
  const [martLimit, setMartLimit] = React.useState(200)
  const [selectedMart, setSelectedMart] = React.useState<string>('freshness')

  const metaQ = useQuery({ queryKey: ['meta'], queryFn: api.meta })

  const datasetsQ = useQuery({ queryKey: ['datasets'], queryFn: () => api.listDatasets(250) })

  const summary: DatasetSummary | undefined = datasetsQ.data?.items?.find((d) => d.dataset === dataset)

  const contractQ = useQuery({
    queryKey: ['contract', dataset],
    queryFn: () => api.getContract(dataset),
    retry: false,
  })

  const schemasQ = useQuery({ queryKey: ['schemas', dataset], queryFn: () => api.schemaHistory(dataset, 50) })

  const curatedQ = useQuery({
    queryKey: ['curated', dataset, curatedLimit],
    queryFn: () => api.curatedSample(dataset, curatedLimit),
  })

  const martsQ = useQuery({ queryKey: ['marts', dataset], queryFn: () => api.listMarts(dataset) })

  const selectedMartQ = useQuery({
    queryKey: ['mart', dataset, selectedMart, martLimit],
    queryFn: () => api.getMart(dataset, selectedMart, martLimit),
    enabled: Boolean(selectedMart),
    retry: false,
  })

  const geoQ = useQuery({
    queryKey: ['mart', dataset, 'geo_points'],
    queryFn: () => api.getMart(dataset, 'geo_points', 600),
    enabled: tab === 'map',
    retry: false,
  })

  const recentIngestionsQ = useQuery({
    queryKey: ['ingestions', 25, dataset, 'all'],
    queryFn: () => api.listIngestions(25, dataset, 'all'),
    enabled: tab === 'overview',
    refetchInterval: 10_000,
  })

  // -------- Contract editing helpers --------
  const enableContractWrite = Boolean(metaQ.data?.runtime?.enable_contract_write)

  const [yamlDraft, setYamlDraft] = React.useState('')
  const [yamlDirty, setYamlDirty] = React.useState(false)

  React.useEffect(() => {
    const raw = contractQ.data?.contract?.raw_yaml
    if (!yamlDirty && typeof raw === 'string') {
      setYamlDraft(raw)
    }
  }, [contractQ.data?.contract?.raw_yaml, yamlDirty])

  const validateMut = useMutation({
    mutationFn: async () => api.validateContract(yamlDraft),
  })

  const saveMut = useMutation({
    mutationFn: async () => api.updateContract(dataset, yamlDraft),
    onSuccess: async () => {
      setYamlDirty(false)
      await qc.invalidateQueries({ queryKey: ['contract', dataset] })
      await qc.invalidateQueries({ queryKey: ['datasets'] })
    },
  })

  // Contract diff (overview)
  const latestSchema = schemasQ.data?.items?.[0]?.schema_json ?? null
  const contractDiff = React.useMemo(() => {
    if (!contractQ.data?.contract || !latestSchema) return null
    return computeContractDiff(contractQ.data.contract, latestSchema)
  }, [contractQ.data?.contract, latestSchema])

  const hasGeo = React.useMemo(() => {
    const cols: any = contractQ.data?.contract?.columns ?? {}
    const hasLatLon = Boolean(cols?.lat && cols?.lon)
    const hasGeoMart = Boolean((martsQ.data?.items ?? []).some((m: any) => m?.name === 'geo_points' && m?.exists))
    return hasLatLon || hasGeoMart
  }, [contractQ.data?.contract?.columns, martsQ.data?.items])

  const tabs = React.useMemo(() => {
    const items = [
      { value: 'overview', label: 'Overview' },
      { value: 'contract', label: 'Contract' },
      { value: 'schemas', label: 'Schema history' },
      { value: 'curated', label: 'Curated sample' },
      { value: 'marts', label: 'Marts' },
    ] as { value: string; label: string }[]

    // Show geo tab if the dataset looks geospatial.
    if (hasGeo) items.push({ value: 'map', label: 'Map' })
    return items
  }, [dataset, hasGeo])

  // Columns
  const contractColumns: ColumnDef<{ name: string; type: string; required: boolean; unique: boolean; min?: any; max?: any }>[] = [
    { header: 'column', accessorKey: 'name' },
    { header: 'type', accessorKey: 'type', cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '—')}</span> },
    { header: 'required', accessorKey: 'required', cell: (info) => (info.getValue() ? 'yes' : 'no') },
    { header: 'unique', accessorKey: 'unique', cell: (info) => (info.getValue() ? 'yes' : 'no') },
    { header: 'min', accessorKey: 'min', cell: (info) => jsonCell(info.getValue()) },
    { header: 'max', accessorKey: 'max', cell: (info) => jsonCell(info.getValue()) },
  ]

  const schemaColumns: ColumnDef<SchemaHistory['items'][number]>[] = [
    { header: 'schema_hash', accessorKey: 'schema_hash', cell: (info) => <span className="font-mono text-xs">{shortHash(String(info.getValue() ?? ''))}</span> },
    { header: 'columns', accessorKey: 'schema_json', cell: (info) => {
      const s: any = info.getValue() as any
      const cols = Array.isArray(s?.columns) ? s.columns.length : 0
      return <span className="text-muted-foreground">{cols}</span>
    } },
    { header: 'first_seen', accessorKey: 'first_seen_at', cell: (info) => <span className="font-mono text-xs">{fmtTime(String(info.getValue() ?? ''))}</span> },
    { header: 'last_seen', accessorKey: 'last_seen_at', cell: (info) => <span className="font-mono text-xs">{fmtTime(String(info.getValue() ?? ''))}</span> },
  ]

  const ingestionColumns: ColumnDef<Ingestion>[] = [
    {
      header: 'id',
      accessorKey: 'id',
      cell: (info) => <span className="font-mono text-xs">{shortHash(String(info.getValue() ?? ''))}</span>,
    },
    {
      header: 'status',
      accessorKey: 'status',
      cell: (info) => statusBadge(String(info.getValue() ?? '')),
    },
    {
      header: 'quality',
      accessorKey: 'quality_passed',
      cell: (info) => qualityBadge(info.getValue() as any, info.row.original.status),
    },
    {
      header: 'received',
      accessorKey: 'received_at',
      cell: (info) => <span className="font-mono text-xs">{fmtTime(String(info.getValue() ?? ''))}</span>,
    },
    {
      header: 'file',
      accessorKey: 'filename',
      cell: (info) => <span className="text-muted-foreground">{String(info.getValue() ?? '—')}</span>,
    },
  ]

  // Derived contract rows
  const contractRows = React.useMemo(() => {
    const c = contractQ.data?.contract
    if (!c?.columns) return []
    return Object.entries(c.columns).map(([name, spec]) => {
      const s = spec as any
      return {
        name,
        type: String(s?.type ?? 'string'),
        required: Boolean(s?.required),
        unique: Boolean(s?.unique),
        min: s?.min,
        max: s?.max,
      }
    })
  }, [contractQ.data?.contract])

  const curatedRows = curatedQ.data?.rows ?? []

  const martRows = (selectedMartQ.data as MartDataResponse | undefined)?.rows ?? []

  const runtimeBadges = (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="outline">dataset: {dataset}</Badge>
      {summary?.has_contract ? <Badge variant="success">contract</Badge> : <Badge variant="outline">no contract</Badge>}
      {summary?.curated_table_exists ? <Badge variant="success">curated</Badge> : <Badge variant="outline">no curated</Badge>}
      {summary?.counts?.processing ? <Badge variant="warning">processing: {summary.counts.processing}</Badge> : null}
    </div>
  )

  return (
    <Page
      title={`Dataset ${dataset}`}
      description="Contracts → schema history → curated outputs → marts (and optional geo view)."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/datasets" className="no-underline">
            <Button size="sm" variant="outline">Back</Button>
          </Link>
          <Button size="sm" variant="outline" onClick={() => nav({ to: '/upload' })}>
            Upload
          </Button>
        </div>
      }
    >
      {runtimeBadges}

      <div className="mt-4">
        <Tabs items={tabs as any} value={tab} onValueChange={(v) => setTab(v as any)} />
      </div>

      <div className="mt-4 space-y-4">
        {tab === 'overview' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Summary" description="A dataset view derived from contracts + the ingestion metadata DB.">
              {datasetsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {datasetsQ.isError ? <div className="text-sm text-destructive">Failed to load dataset summary.</div> : null}
              {summary ? (
                <div className="text-sm space-y-2">
                  <div>
                    <span className="text-muted-foreground">description:</span>{' '}
                    <span>{summary.contract_description ?? contractQ.data?.contract?.description ?? '—'}</span>
                  </div>
                  <div className="grid gap-2">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">ingestions</span>
                      <span className="font-mono">{summary.ingestion_count ?? 0}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">last received</span>
                      <span className="font-mono">{fmtTime(summary.last_received_at)}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">last processed</span>
                      <span className="font-mono">{fmtTime(summary.last_processed_at)}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-muted-foreground">latest schema</span>
                      <span className="font-mono">{shortHash(summary.latest_schema_hash)}</span>
                    </div>
                  </div>

                  <Separator />

                  <div className="grid grid-cols-2 gap-2">
                    <Card className="p-3">
                      <div className="text-xs text-muted-foreground">success</div>
                      <div className="text-lg font-semibold">{summary.counts.success}</div>
                    </Card>
                    <Card className="p-3">
                      <div className="text-xs text-muted-foreground">failed</div>
                      <div className="text-lg font-semibold">{summary.counts.failed}</div>
                    </Card>
                  </div>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">No summary yet. Ingest data (or create a contract) to populate it.</div>
              )}
            </Section>

            <Section title="Contract vs observed" description="Diff between the current contract and the latest observed schema (most recent ingestion).">
              {!contractDiff ? (
                <div className="text-sm text-muted-foreground">No diff yet (need a contract + at least 1 observed schema).</div>
              ) : (
                <div className="text-sm space-y-3">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant={contractDiff.missing_in_observed.length ? 'warning' : 'success'}>
                      missing: {contractDiff.missing_in_observed.length}
                    </Badge>
                    <Badge variant={contractDiff.extra_in_observed.length ? 'warning' : 'success'}>
                      extra: {contractDiff.extra_in_observed.length}
                    </Badge>
                    <Badge variant={contractDiff.type_mismatches.length ? 'warning' : 'success'}>
                      type mismatches: {contractDiff.type_mismatches.length}
                    </Badge>
                  </div>

                  {contractDiff.missing_in_observed.length ? (
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Missing columns</div>
                      <div className="flex flex-wrap gap-1">
                        {contractDiff.missing_in_observed.slice(0, 18).map((c) => (
                          <Badge key={c} variant="outline">{c}</Badge>
                        ))}
                        {contractDiff.missing_in_observed.length > 18 ? <span className="text-xs text-muted-foreground">…</span> : null}
                      </div>
                    </div>
                  ) : null}

                  {contractDiff.extra_in_observed.length ? (
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Extra columns</div>
                      <div className="flex flex-wrap gap-1">
                        {contractDiff.extra_in_observed.slice(0, 18).map((c) => (
                          <Badge key={c} variant="outline">{c}</Badge>
                        ))}
                        {contractDiff.extra_in_observed.length > 18 ? <span className="text-xs text-muted-foreground">…</span> : null}
                      </div>
                    </div>
                  ) : null}

                  {contractDiff.type_mismatches.length ? (
                    <div>
                      <div className="text-xs text-muted-foreground mb-1">Type mismatches</div>
                      <div className="space-y-1">
                        {contractDiff.type_mismatches.slice(0, 10).map((m) => (
                          <div key={m.name} className="text-xs font-mono">
                            {m.name}: {m.contract} → {m.observed}
                          </div>
                        ))}
                        {contractDiff.type_mismatches.length > 10 ? <div className="text-xs text-muted-foreground">…</div> : null}
                      </div>
                    </div>
                  ) : null}
                </div>
              )}
            </Section>

            <div className="md:col-span-2">
              <Section title="Recent ingestions" description="Last 25 ingestions for this dataset (click a row to inspect).">
                {recentIngestionsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
                {recentIngestionsQ.isError ? <div className="text-sm text-destructive">Failed to load recent ingestions.</div> : null}
                {recentIngestionsQ.data?.items?.length ? (
                  <DataTable
                    data={recentIngestionsQ.data.items}
                    columns={ingestionColumns as any}
                    height={380}
                    columnMinWidth={180}
                    onRowClick={(row) => nav({ to: '/ingestions/$id', params: { id: row.id } })}
                  />
                ) : (
                  <div className="text-sm text-muted-foreground">No ingestions yet.</div>
                )}
              </Section>
            </div>
          </div>
        ) : null}

        {tab === 'contract' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Contract (YAML)" description="Source of truth for validation, drift policy, and curated table creation.">
              {contractQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {contractQ.isError ? (
                <div className="text-sm text-muted-foreground">
                  No contract found for this dataset yet.
                </div>
              ) : null}

              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">sha: {shortHash(contractQ.data?.contract?.sha256 ?? '—')}</Badge>
                  <Badge variant="outline">file: {contractQ.data?.contract?.filename ?? '—'}</Badge>
                  {enableContractWrite ? <Badge variant="success">write enabled</Badge> : <Badge variant="outline">write disabled</Badge>}
                </div>

                <div>
                  <Label>YAML</Label>
                  <Textarea
                    value={yamlDraft}
                    onChange={(e) => {
                      setYamlDraft(e.target.value)
                      setYamlDirty(true)
                    }}
                    className="font-mono text-xs"
                    rows={16}
                    placeholder={contractQ.isError ? 'Create a contract YAML here (then click Validate / Save).' : ''}
                  />
                  <div className="text-xs text-muted-foreground mt-1">
                    Saving requires <span className="font-mono">ENABLE_CONTRACT_WRITE=true</span> and internal auth.
                    If <span className="font-mono">TASK_AUTH_MODE=token</span>, set a task token in <Link to="/meta" className="underline">Ops</Link>.
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => validateMut.mutate()} disabled={!yamlDraft.trim() || validateMut.isPending}>
                    Validate
                  </Button>
                  <Button size="sm" onClick={() => saveMut.mutate()} disabled={!enableContractWrite || !yamlDraft.trim() || saveMut.isPending}>
                    Save
                  </Button>
                  {yamlDirty ? <Badge variant="warning">unsaved</Badge> : <Badge variant="outline">synced</Badge>}
                </div>

                {validateMut.isError ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                    {(validateMut.error as Error).message}
                  </div>
                ) : null}

                {validateMut.data ? (
                  <ContractValidationPreview resp={validateMut.data as ContractValidateResponse} />
                ) : null}

                {saveMut.isError ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                    {(saveMut.error as Error).message}
                  </div>
                ) : null}

                {saveMut.isSuccess ? (
                  <div className="rounded-md border border-emerald-600/40 bg-emerald-600/5 p-3 text-sm">
                    Saved. The API reloaded the contract and wrote an audit event.
                  </div>
                ) : null}
              </div>
            </Section>

            <Section title="Parsed columns" description="Contract columns drive validation and curated table creation.">
              {contractRows.length ? (
                <DataTable data={contractRows} columns={contractColumns} height={560} columnMinWidth={220} />
              ) : (
                <div className="text-sm text-muted-foreground">No columns to show.</div>
              )}
            </Section>
          </div>
        ) : null}

        {tab === 'schemas' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Schema history" description="Observed schemas over time (for drift detection).">
              {schemasQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {schemasQ.isError ? <div className="text-sm text-destructive">Failed to load schema history.</div> : null}
              {schemasQ.data?.items?.length ? (
                <DataTable
                  data={schemasQ.data.items}
                  columns={schemaColumns as any}
                  height={560}
                  columnMinWidth={220}
                  onRowClick={(row) => {
                    // Show the selected schema JSON in the right-hand panel
                    setSelectedSchema(row.schema_json)
                  }}
                />
              ) : (
                <div className="text-sm text-muted-foreground">No schemas yet. Ingest a file to record an observed schema.</div>
              )}
              <div className="text-xs text-muted-foreground">Tip: click a row to inspect the raw schema JSON.</div>
            </Section>

            <SchemaJsonPanel schema={selectedSchema} />
          </div>
        ) : null}

        {tab === 'curated' ? (
          <div className="space-y-4">
            <Section title="Curated sample" description="Rows from curated_<dataset> (if it exists).">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label htmlFor="curatedLimit">Limit</Label>
                  <Input
                    id="curatedLimit"
                    type="number"
                    value={curatedLimit}
                    min={1}
                    max={200}
                    onChange={(e) => setCuratedLimit(Math.max(1, Math.min(200, Number(e.target.value || 25))))}
                    className="w-28"
                  />
                </div>
                <div className="text-xs text-muted-foreground">Note: samples are ordered by newest loaded rows.</div>
              </div>

              {curatedQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {curatedQ.isError ? <div className="text-sm text-destructive">Failed to load curated sample.</div> : null}

              {!curatedQ.data?.table_exists ? (
                <div className="text-sm text-muted-foreground">Curated table does not exist yet. Ingest at least one valid file.</div>
              ) : curatedRows.length ? (
                <DataTable data={curatedRows} columns={buildDynamicColumns(curatedRows)} height={560} columnMinWidth={240} />
              ) : (
                <div className="text-sm text-muted-foreground">No rows available.</div>
              )}
            </Section>
          </div>
        ) : null}

        {tab === 'marts' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Section title="Available marts" description="Read-optimized views (warehouse-style) published per dataset.">
              {martsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {martsQ.isError ? <div className="text-sm text-destructive">Failed to load marts.</div> : null}
              {martsQ.data?.items?.length ? (
                <div className="space-y-2">
                  {martsQ.data.items.map((m: MartItem) => {
                    const active = selectedMart === m.name
                    return (
                      <button
                        key={m.name}
                        type="button"
                        onClick={() => setSelectedMart(m.name)}
                        className={
                          'w-full text-left rounded-md border p-3 transition-colors ' +
                          (active ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/50')
                        }
                      >
                        <div className="flex items-center justify-between">
                          <div className="font-mono text-sm">{m.name}</div>
                          {m.exists ? <Badge variant="success">ready</Badge> : <Badge variant="outline">pending</Badge>}
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{m.description}</div>
                        <div className="text-xs text-muted-foreground mt-1 font-mono">{m.view}</div>
                      </button>
                    )
                  })}
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">No marts configured for this dataset.</div>
              )}
            </Section>

            <Section title="Mart preview" description="Sample rows from the selected mart view.">
              <div className="flex flex-wrap items-end gap-3">
                <div className="space-y-1">
                  <Label htmlFor="martLimit">Limit</Label>
                  <Input
                    id="martLimit"
                    type="number"
                    value={martLimit}
                    min={1}
                    max={2000}
                    onChange={(e) => setMartLimit(Math.max(1, Math.min(2000, Number(e.target.value || 200))))}
                    className="w-28"
                  />
                </div>
                <div className="text-xs text-muted-foreground">Views are capped to 2000 rows per request.</div>
              </div>

              {selectedMartQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {selectedMartQ.isError ? (
                <div className="text-sm text-muted-foreground">
                  This mart is not available yet. Ingest at least one file to build curated tables, then refresh.
                </div>
              ) : null}

              {martRows.length ? (
                <DataTable data={martRows} columns={buildDynamicColumns(martRows)} height={560} columnMinWidth={220} />
              ) : null}

              {selectedMartQ.data ? (
                <div className="text-xs text-muted-foreground">
                  Endpoint: <span className="font-mono">/api/datasets/{dataset}/marts/{selectedMart}</span>
                </div>
              ) : null}
            </Section>
          </div>
        ) : null}

        {tab === 'map' ? (
          <div className="space-y-4">
            <Section title="Geospatial view" description="Lightweight map powered by the geo_points mart (lat/lon).">
              {geoQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {geoQ.isError ? (
                <div className="text-sm text-muted-foreground">
                  Geo mart not available yet. Ingest data first.
                </div>
              ) : null}

              {geoQ.data?.rows ? <GeoScatter rows={geoQ.data.rows} /> : null}

              <Separator />

              <div className="text-xs text-muted-foreground">
                Powered by the <span className="font-mono">geo_points</span> mart (a Postgres view) so the UI stays simple and consumption-friendly.
              </div>
            </Section>
          </div>
        ) : null}
      </div>
    </Page>
  )
}

function ContractValidationPreview(props: { resp: ContractValidateResponse }) {
  const c = props.resp.contract
  const colCount = Object.keys(c.columns || {}).length
  return (
    <div className="rounded-md border bg-muted/30 p-3 text-sm">
      <div className="font-medium mb-1">Validation OK</div>
      <div className="text-xs text-muted-foreground">
        dataset: <span className="font-mono">{c.dataset}</span> • primary_key:{' '}
        <span className="font-mono">{c.primary_key ?? '—'}</span> • columns: <span className="font-mono">{colCount}</span>
      </div>
    </div>
  )
}

function SchemaJsonPanel(props: { schema: any }) {
  return (
    <Section title="Schema JSON" description="Raw inferred schema (used for drift detection).">
      {props.schema ? (
        <pre className="overflow-x-auto rounded-md border bg-muted/30 p-4 text-xs">{JSON.stringify(props.schema, null, 2)}</pre>
      ) : (
        <div className="text-sm text-muted-foreground">Click a schema row to inspect.</div>
      )}
    </Section>
  )
}


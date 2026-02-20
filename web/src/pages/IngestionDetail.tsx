import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams, Link } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, type Ingestion, type QualityReport, type AuditEvent } from '../api'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  DataTable,
  Page,
  Tabs,
  Separator,
} from '../portfolio-ui'

function statusVariant(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'loaded' || s === 'success') return 'success'
  if (s === 'processing') return 'warning'
  if (s === 'received') return 'outline'
  if (s.startsWith('failed')) return 'destructive'
  return 'secondary'
}

function statusLabel(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'loaded') return 'success'
  return s || '—'
}

function shortHash(h?: string | null) {
  if (!h) return '—'
  return `${h.slice(0, 10)}…`
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.replace('T', ' ').replace('Z', 'Z')
}

function jsonCell(v: any) {
  if (v === null || v === undefined) return <span className="text-muted-foreground">—</span>
  if (typeof v === 'object') return <span className="font-mono text-xs text-muted-foreground">{JSON.stringify(v)}</span>
  return <span className="text-muted-foreground">{String(v)}</span>
}

function buildColumns(rows: Record<string, any>[]): ColumnDef<Record<string, any>>[] {
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

function QualitySummary(props: { ingestion: Ingestion; report: QualityReport | undefined }) {
  const r = props.report as any
  const ok = Boolean(r?.ok)
  const errors: string[] = r?.errors ?? []
  const warnings: string[] = r?.warnings ?? []
  const metrics = r?.metrics ?? {}
  const nullFractions: Record<string, number> = metrics?.null_fractions ?? {}

  const worstNulls = Object.entries(nullFractions)
    .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    .slice(0, 12)
    .filter(([, v]) => (v ?? 0) > 0)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={ok ? 'success' : 'destructive'}>{ok ? 'QUALITY PASS' : 'QUALITY FAIL'}</Badge>
        <Badge variant="outline">rows: {metrics?.row_count ?? '—'}</Badge>
        <Badge variant="outline">cols: {metrics?.column_count ?? '—'}</Badge>
        {r?.observed_schema_hash ? <Badge variant="outline">schema: {shortHash(r.observed_schema_hash)}</Badge> : null}
      </div>

      {errors.length ? (
        <div className="space-y-1">
          <div className="text-sm font-medium">Errors</div>
          <ul className="list-disc pl-5 text-sm text-destructive space-y-1">
            {errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">No errors.</div>
      )}

      {warnings.length ? (
        <div className="space-y-1">
          <div className="text-sm font-medium">Warnings</div>
          <ul className="list-disc pl-5 text-sm text-muted-foreground space-y-1">
            {warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {worstNulls.length ? (
        <div className="space-y-2">
          <div className="text-sm font-medium">Top null fractions</div>
          <div className="grid gap-2 md:grid-cols-2">
            {worstNulls.map(([k, v]) => (
              <div key={k} className="rounded-md border p-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono">{k}</span>
                  <span className="text-muted-foreground">{(v * 100).toFixed(1)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <details>
        <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
          View full quality report JSON
        </summary>
        <pre className="mt-2 overflow-x-auto rounded-md border bg-muted/30 p-3 text-xs">{JSON.stringify(r, null, 2)}</pre>
      </details>
    </div>
  )
}

function DriftSummary(props: { report: QualityReport | undefined }) {
  const drift = (props.report as any)?.drift
  if (!drift) return <div className="text-sm text-muted-foreground">No drift info available.</div>

  const type = drift?.type ?? 'none'
  const breaking = Boolean(drift?.breaking)
  const added: string[] = drift?.added ?? []
  const removed: string[] = drift?.removed ?? []
  const changed = drift?.changed_type ?? {}

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={type === 'none' ? 'outline' : breaking ? 'destructive' : 'warning'}>
          drift: {type}
        </Badge>
        <Badge variant={breaking ? 'destructive' : 'success'}>{breaking ? 'breaking' : 'non-breaking'}</Badge>
      </div>

      {added.length ? (
        <div className="space-y-1">
          <div className="text-sm font-medium">Added columns</div>
          <div className="flex flex-wrap gap-2">{added.map((c: string) => <Badge key={c} variant="secondary">{c}</Badge>)}</div>
        </div>
      ) : null}

      {removed.length ? (
        <div className="space-y-1">
          <div className="text-sm font-medium">Removed columns</div>
          <div className="flex flex-wrap gap-2">{removed.map((c: string) => <Badge key={c} variant="destructive">{c}</Badge>)}</div>
        </div>
      ) : null}

      {Object.keys(changed).length ? (
        <div className="space-y-2">
          <div className="text-sm font-medium">Type changes</div>
          <div className="rounded-md border overflow-hidden">
            <div className="grid grid-cols-3 bg-muted/30 px-3 py-2 text-xs font-medium text-muted-foreground">
              <div>column</div>
              <div>from</div>
              <div>to</div>
            </div>
            {Object.entries(changed).map(([col, v]: any) => (
              <div key={col} className="grid grid-cols-3 px-3 py-2 text-xs border-t">
                <div className="font-mono">{col}</div>
                <div className="text-muted-foreground">{v?.from ?? '—'}</div>
                <div className="text-muted-foreground">{v?.to ?? '—'}</div>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {type === 'none' ? <div className="text-sm text-muted-foreground">No schema drift detected.</div> : null}
    </div>
  )
}

export function IngestionDetailPage() {
  const { id } = useParams({ from: '/ingestions/$id' })
  const navigate = useNavigate()

  const [tab, setTab] = React.useState<'overview' | 'quality' | 'drift' | 'lineage' | 'audit' | 'rows'>('overview')
  const [copyMsg, setCopyMsg] = React.useState<string | null>(null)

  const q = useQuery({
    queryKey: ['ingestion', id],
    queryFn: () => api.getIngestion(id),
    refetchInterval: 4000,
  })

  const ingestion = q.data?.ingestion
  const report = q.data?.quality_report

  const lineageQ = useQuery({
    queryKey: ['lineage', id],
    queryFn: () => api.getLineage(id),
    enabled: Boolean(ingestion),
  })

  const rowsQ = useQuery({
    queryKey: ['preview', id],
    queryFn: () => api.ingestionPreview(id, 50),
    enabled: Boolean(ingestion),
  })

  const auditQ = useQuery({
    queryKey: ['audit_events', id],
    queryFn: () => api.auditEvents(200, undefined, id),
    enabled: Boolean(ingestion),
    refetchInterval: 10_000,
  })

  const rows = rowsQ.data?.rows ?? []
  const rowCols = React.useMemo(() => buildColumns(rows), [rows])

  async function copy(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text)
      setCopyMsg(`Copied ${label}.`)
      setTimeout(() => setCopyMsg(null), 1500)
    } catch {
      setCopyMsg('Copy failed.')
      setTimeout(() => setCopyMsg(null), 1500)
    }
  }

  async function replay() {
    if (!ingestion) return
    try {
      const res = await api.replayIngestion(ingestion.id)
      await navigate({ to: '/ingestions/$id', params: { id: res.ingestion_id } })
    } catch (e) {
      setCopyMsg(`Replay failed: ${(e as Error).message}`)
      setTimeout(() => setCopyMsg(null), 2500)
    }
  }

  const tabs = [
    { value: 'overview', label: 'Overview' },
    { value: 'quality', label: 'Quality' },
    { value: 'drift', label: 'Drift' },
    { value: 'lineage', label: 'Lineage' },
    { value: 'audit', label: 'Audit' },
    { value: 'rows', label: 'Curated rows' },
  ] as const

  const auditColumns: ColumnDef<AuditEvent>[] = [
    {
      header: 'time',
      accessorKey: 'created_at',
      cell: (info) => <span className="font-mono text-xs">{fmtTime(String(info.getValue() ?? ''))}</span>,
    },
    {
      header: 'event',
      accessorKey: 'event_type',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'actor',
      accessorKey: 'actor',
      cell: (info) => <span className="text-muted-foreground">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'details',
      accessorKey: 'details',
      cell: (info) => jsonCell(info.getValue()),
    },
  ]


  return (
    <Page
      title={`Ingestion ${id}`}
      description="Inspect the end-to-end record: quality results, drift, lineage artifact, and curated outputs."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/ingestions" className="no-underline">
            <Button size="sm" variant="outline">Back</Button>
          </Link>
          {ingestion ? (
            <Link to="/datasets/$dataset" params={{ dataset: ingestion.dataset }} className="no-underline">
              <Button size="sm" variant="outline">Dataset</Button>
            </Link>
          ) : null}
          <Button size="sm" onClick={replay} disabled={!ingestion}>Replay</Button>
        </div>
      }
    >
      {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
      {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}

      {copyMsg ? <div className="text-xs text-muted-foreground mb-2">{copyMsg}</div> : null}

      {ingestion ? (
        <>
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <Badge variant={statusVariant(ingestion.status) as any}>{statusLabel(ingestion.status)}</Badge>
            <Badge variant="outline">dataset: {ingestion.dataset}</Badge>
            <Badge variant="outline">attempts: {ingestion.processing_attempts ?? 0}</Badge>
            {ingestion.error ? <Badge variant="destructive">error</Badge> : null}
            {ingestion.quality_passed === true ? <Badge variant="success">quality ok</Badge> : null}
            {ingestion.quality_passed === false ? <Badge variant="destructive">quality fail</Badge> : null}
          </div>

          <Tabs items={tabs as any} value={tab} onValueChange={(v) => setTab(v as any)} className="mb-4" />

          {tab === 'overview' ? (
            <div className="grid gap-4 md:grid-cols-2">
              <Section title="Ingestion record">
                <div className="text-sm space-y-1">
                  <div>
                    <span className="text-muted-foreground">id:</span>{' '}
                    <span className="font-mono">{ingestion.id}</span>{' '}
                    <Button size="sm" variant="ghost" onClick={() => copy(ingestion.id, 'id')}>Copy</Button>
                  </div>
                  <div>
                    <span className="text-muted-foreground">source:</span> <span className="font-mono">{ingestion.source ?? '—'}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">file:</span> <span className="font-mono">{ingestion.filename ?? '—'}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">sha256:</span> <span className="font-mono">{shortHash(ingestion.sha256)}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">raw:</span>
                    <span className="font-mono text-xs break-all">{ingestion.raw_path}</span>
                    <Button size="sm" variant="ghost" onClick={() => copy(ingestion.raw_path, 'raw path')}>Copy</Button>
                  </div>
                  {ingestion.raw_generation ? (
                    <div>
                      <span className="text-muted-foreground">generation:</span> <span className="font-mono">{ingestion.raw_generation}</span>
                    </div>
                  ) : null}
                </div>

                {ingestion.error ? (
                  <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive">
                    {ingestion.error}
                  </div>
                ) : null}
              </Section>

              <Section title="Timing">
                <div className="grid gap-2 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">received_at</span>
                    <span className="font-mono">{fmtTime(ingestion.received_at)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">processing_started_at</span>
                    <span className="font-mono">{fmtTime(ingestion.processing_started_at)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">processing_heartbeat_at</span>
                    <span className="font-mono">{fmtTime(ingestion.processing_heartbeat_at)}</span>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">processed_at</span>
                    <span className="font-mono">{fmtTime(ingestion.processed_at)}</span>
                  </div>
                </div>

                <Separator />

                <div className="text-xs text-muted-foreground">
                  Tip: If an ingestion is stuck in <span className="font-mono">PROCESSING</span>, check worker logs and the reclaim-stuck runbook.
                </div>
              </Section>
            </div>
          ) : null}

          {tab === 'quality' ? (
            <Section title="Quality report" description="Contract-based validation + basic profiling metrics.">
              <QualitySummary ingestion={ingestion} report={report} />
            </Section>
          ) : null}

          {tab === 'drift' ? (
            <Section title="Schema drift" description="Diff between last-seen schema and this ingestion's observed schema.">
              <DriftSummary report={report} />
            </Section>
          ) : null}

          {tab === 'lineage' ? (
            <Section title="Lineage artifact" description="Governance-friendly artifact persisted per ingestion.">
              {lineageQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {lineageQ.isError ? <div className="text-sm text-destructive">Error: {(lineageQ.error as Error).message}</div> : null}
              {lineageQ.data ? (
                <>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="outline">created_at: {lineageQ.data.created_at ?? '—'}</Badge>
                  </div>
                  <pre className="overflow-x-auto rounded-md border bg-muted/30 p-4 text-xs">{JSON.stringify(lineageQ.data.artifact, null, 2)}</pre>
                </>
              ) : (
                <div className="text-sm text-muted-foreground">No lineage artifact yet (ingestion may still be processing).</div>
              )}
            </Section>
          ) : null}
        {tab === 'audit' ? (
          <Section title="Audit trail" description="Lifecycle + ops events recorded for this ingestion.">
            {auditQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {auditQ.error ? <div className="text-sm text-destructive">Failed to load audit events.</div> : null}
            <DataTable data={auditQ.data?.items ?? []} columns={auditColumns} height={520} columnMinWidth={220} />
          </Section>
        ) : null}



          {tab === 'rows' ? (
            <Section title="Curated rows" description="Rows from the curated table for this ingestion_id (if loaded).">
              {rowsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {rowsQ.isError ? <div className="text-sm text-destructive">Error: {(rowsQ.error as Error).message}</div> : null}
              {rowsQ.data?.table_exists === false ? (
                <div className="text-sm text-muted-foreground">Curated table not available yet for this dataset.</div>
              ) : null}
              <DataTable data={rows} columns={rowCols} height={520} />
            </Section>
          ) : null}
        </>
      ) : null}
    </Page>
  )
}

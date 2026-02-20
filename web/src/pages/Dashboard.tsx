import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Page, Separator } from '../portfolio-ui'

function fmtPct(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function fmtInt(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return Intl.NumberFormat().format(v)
}

function StatusKpi(props: { label: string; value: string; hint?: string; badge?: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
          {props.label}
          {props.badge}
        </CardTitle>
        {props.hint ? <CardDescription>{props.hint}</CardDescription> : null}
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight">{props.value}</div>
      </CardContent>
    </Card>
  )
}

function ActivityChart(props: { activity: { hour: string; received: number; processing: number; success: number; failed: number; other: number }[] }) {
  const max = Math.max(
    1,
    ...props.activity.map((a) => a.received + a.processing + a.success + a.failed + a.other),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>Ingestion activity (last {props.activity.length} hours)</span>
        <span>Higher bar = more ingestions received</span>
      </div>

      <div className="flex items-end gap-1 rounded-md border bg-muted/20 p-3 overflow-x-auto">
        {props.activity.map((a) => {
          const total = a.received + a.processing + a.success + a.failed + a.other
          const h = Math.max(2, Math.round((total / max) * 72))
          return (
            <div key={a.hour} className="flex flex-col items-center gap-1">
              <div
                className="w-3 rounded-sm bg-muted-foreground/40"
                title={`${a.hour}\nreceived=${a.received} processing=${a.processing} success=${a.success} failed=${a.failed}`}
                style={{ height: h }}
              />
            </div>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-muted-foreground/40" /> total per hour
        </span>
      </div>
    </div>
  )
}

export function DashboardPage() {
  const metaQ = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const statsQ = useQuery({ queryKey: ['stats', 24], queryFn: () => api.stats(24), refetchInterval: 5000 })
  const dsQ = useQuery({ queryKey: ['datasets', 50], queryFn: () => api.listDatasets(50) })

  // Field device status is derived from marts_edge_telemetry_device_status.
  // This is intentionally a *public* mart (no secrets), so the dashboard can
  // surface basic ops signal without needing internal auth.
  const devicesQ = useQuery({
    queryKey: ['mart', 'edge_telemetry', 'device_status'],
    queryFn: async () => {
      const res = await api.getMart('edge_telemetry', 'device_status', 1000)
      return (res.rows ?? []) as any[]
    },
    refetchInterval: 10_000,
  })

  const [seedLoading, setSeedLoading] = React.useState(false)
  const [seedResult, setSeedResult] = React.useState<string | null>(null)
  const [seedEdgeLoading, setSeedEdgeLoading] = React.useState(false)
  const [seedEdgeResult, setSeedEdgeResult] = React.useState<string | null>(null)

  const deviceTotals = React.useMemo(() => {
    const rows = devicesQ.data ?? []
    if (!rows.length) return { total: 0, online: 0, offline: 0, revoked: 0, alerting: 0, critical: 0, warning: 0 }

    const total = rows.length
    const revoked = rows.filter((r) => Boolean((r as any).revoked_at)).length
    const offline = rows.filter((r) => Boolean((r as any).is_offline) && !Boolean((r as any).revoked_at)).length
    const online = Math.max(0, total - offline - revoked)
    const alerting = rows.filter((r) => Number((r as any).alert_count ?? 0) > 0 && !Boolean((r as any).revoked_at)).length
    const critical = rows.filter((r) => String((r as any).alert_severity ?? '').toLowerCase() === 'critical' && !Boolean((r as any).revoked_at)).length
    const warning = rows.filter((r) => String((r as any).alert_severity ?? '').toLowerCase() === 'warning' && !Boolean((r as any).revoked_at)).length
    return { total, online, offline, revoked, alerting, critical, warning }
  }, [devicesQ.data])
  const demoEnabled = Boolean(metaQ.data?.runtime?.enable_demo_endpoints)

  async function seedParcels() {
    setSeedLoading(true)
    setSeedResult(null)
    try {
      const res = await api.seedParcels(60)
      setSeedResult(`Seeded ${res.rows} rows across ${res.ingestions.length} ingestions (seed_id=${res.seed_id}).`)
    } catch (e) {
      setSeedResult(`Seed failed: ${(e as Error).message}`)
    } finally {
      setSeedLoading(false)
    }
  }

  async function seedEdgeTelemetry() {
    setSeedEdgeLoading(true)
    setSeedEdgeResult(null)
    try {
      const res = await api.seedEdgeTelemetry(240)
      setSeedEdgeResult(`Seeded ${res.rows} rows across ${res.ingestions.length} ingestions (seed_id=${res.seed_id}).`)
    } catch (e) {
      setSeedEdgeResult(`Seed failed: ${(e as Error).message}`)
    } finally {
      setSeedEdgeLoading(false)
    }
  }

  const totals = statsQ.data?.totals ?? {}
  const activity = statsQ.data?.activity ?? []

  const storage = metaQ.data?.runtime?.storage_backend
  const queue = metaQ.data?.runtime?.queue

  return (
    <Page
      title="Dashboard"
      description="Operational overview for the event-driven ingestion pipeline."
      actions={
        <div className="flex items-center gap-2">
          {storage ? <Badge variant="outline">storage: {storage}</Badge> : null}
          {queue ? <Badge variant="outline">queue: {queue}</Badge> : null}
          <Link to="/upload" className="no-underline">
            <Button size="sm" variant="outline">Ingest</Button>
          </Link>
          <Link to="/products" className="no-underline">
            <Button size="sm" variant="outline">Products</Button>
          </Link>
          <Link to="/trends" className="no-underline">
            <Button size="sm" variant="outline">Trends</Button>
          </Link>
          <Link to="/audit" className="no-underline">
            <Button size="sm" variant="outline">Audit</Button>
          </Link>
          <Link to="/ingestions" className="no-underline">
            <Button size="sm">Ingestions</Button>
          </Link>
        </div>
      }
    >
      {metaQ.isLoading || statsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
      {(metaQ.isError || statsQ.isError) ? (
        <div className="text-sm text-destructive">
          Error: {((metaQ.error || statsQ.error) as Error).message}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <StatusKpi label="Total ingestions" value={fmtInt(statsQ.data?.total_ingestions)} />
        <StatusKpi label="Backlog" value={fmtInt(statsQ.data?.backlog)} hint="received + processing" />
        <StatusKpi label="Success rate" value={fmtPct(statsQ.data?.success_rate)} hint="success / (success + failed)" />
        <StatusKpi
          label="Stuck processing"
          value={fmtInt(statsQ.data?.stuck_processing)}
          hint="processing older than TTL"
          badge={statsQ.data?.stuck_processing ? <Badge variant="warning">check</Badge> : undefined}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 mt-6">
        <Card>
          <CardHeader>
            <CardTitle>Status totals</CardTitle>
            <CardDescription>Grouped status counts from the metadata DB.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">received: {fmtInt(totals.received)}</Badge>
              <Badge variant="warning">processing: {fmtInt(totals.processing)}</Badge>
              <Badge variant="success">success: {fmtInt(totals.success)}</Badge>
              <Badge variant="destructive">failed: {fmtInt(totals.failed)}</Badge>
            </div>
            <Separator />
            {activity.length ? <ActivityChart activity={activity} /> : <div className="text-sm text-muted-foreground">No recent activity.</div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Datasets</CardTitle>
            <CardDescription>Contract-backed datasets available in this environment.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {dsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading datasets…</div> : null}
            {dsQ.isError ? <div className="text-sm text-destructive">Error: {(dsQ.error as Error).message}</div> : null}
            {dsQ.data?.items?.length ? (
              <div className="space-y-2">
                {dsQ.data.items.slice(0, 8).map((d) => (
                  <div key={d.dataset} className="flex items-center justify-between rounded-md border p-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Link to="/datasets/$dataset" params={{ dataset: d.dataset }} className="font-medium">
                          {d.dataset}
                        </Link>
                        {d.curated_table_exists ? <Badge variant="secondary">curated</Badge> : <Badge variant="outline">no curated</Badge>}
                        {d.has_contract ? <Badge variant="outline">contract</Badge> : <Badge variant="warning">no contract</Badge>}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        ingestions: {fmtInt(d.ingestion_count)} • last: {d.last_received_at ?? '—'}
                      </div>
                    </div>
                    <Link to="/datasets/$dataset" params={{ dataset: d.dataset }} className="no-underline">
                      <Button size="sm" variant="outline">Open</Button>
                    </Link>
                  </div>
                ))}
                <Link to="/datasets" className="text-sm text-muted-foreground hover:text-foreground">
                  View all datasets →
                </Link>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">No datasets found yet. Add a contract or ingest data.</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Field devices</CardTitle>
            <CardDescription>Online/offline signal from edge telemetry marts.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {devicesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading devices…</div> : null}
            {devicesQ.isError ? (
              <div className="text-sm text-muted-foreground">
                No device status yet. Ingest edge telemetry (seed from the Dashboard or run the RPi agent).
              </div>
            ) : null}

            {deviceTotals.total ? (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  <Badge variant="secondary">online: {fmtInt(deviceTotals.online)}</Badge>
                  <Badge variant={deviceTotals.offline ? 'destructive' : 'outline'}>offline: {fmtInt(deviceTotals.offline)}</Badge>
                  <Badge variant={deviceTotals.alerting ? 'warning' : 'outline'}>alerting: {fmtInt(deviceTotals.alerting)}</Badge>
                  <Badge variant={deviceTotals.critical ? 'destructive' : 'outline'}>critical: {fmtInt(deviceTotals.critical)}</Badge>
                  <Badge variant={deviceTotals.warning ? 'warning' : 'outline'}>warning: {fmtInt(deviceTotals.warning)}</Badge>
                  <Badge variant="outline">revoked: {fmtInt(deviceTotals.revoked)}</Badge>
                  <Badge variant="outline">total: {fmtInt(deviceTotals.total)}</Badge>
                </div>
                <Link to="/devices" className="no-underline">
                  <Button size="sm" variant="outline">Open Devices</Button>
                </Link>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">No devices observed yet.</div>
            )}

            <div className="text-xs text-muted-foreground">
              Offline threshold is controlled by <span className="font-mono">EDGE_OFFLINE_THRESHOLD_SECONDS</span>.
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle>Quick actions</CardTitle>
            <CardDescription>Helpful shortcuts for exploring the demo.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <Link to="/upload" className="no-underline">
              <Button variant="outline">Upload a file</Button>
            </Link>
            <Link to="/products" className="no-underline">
              <Button variant="outline">Browse data products</Button>
            </Link>
            <Link to="/trends" className="no-underline">
              <Button variant="outline">View trends</Button>
            </Link>
            <Link to="/audit" className="no-underline">
              <Button variant="outline">Open audit log</Button>
            </Link>
            <Link to="/datasets/$dataset" params={{ dataset: 'parcels' }} className="no-underline">
              <Button variant="outline">Open parcels dataset</Button>
            </Link>
            <Link to="/datasets/$dataset" params={{ dataset: 'edge_telemetry' }} className="no-underline">
              <Button variant="outline">Open edge telemetry</Button>
            </Link>
            {demoEnabled ? (
              <>
                <Button onClick={seedParcels} disabled={seedLoading}>
                  {seedLoading ? 'Seeding…' : 'Seed parcels'}
                </Button>
                <Button onClick={seedEdgeTelemetry} disabled={seedEdgeLoading}>
                  {seedEdgeLoading ? 'Seeding…' : 'Seed edge telemetry'}
                </Button>
              </>
            ) : (
              <Badge variant="outline">Demo endpoints disabled</Badge>
            )}
            {seedResult ? <span className="text-sm text-muted-foreground">{seedResult}</span> : null}
            {seedEdgeResult ? <span className="text-sm text-muted-foreground">{seedEdgeResult}</span> : null}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}

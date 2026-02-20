import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api, getTaskTokenForUi, setTaskToken, type DbStats } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, Page, Separator } from '../portfolio-ui'

function fmtBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function MetaPage() {
  const q = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const r = q.data?.runtime

  const [taskToken, setTaskTokenState] = React.useState(getTaskTokenForUi())
  React.useEffect(() => setTaskTokenState(getTaskTokenForUi()), [])

  function updateToken(v: string) {
    setTaskTokenState(v)
    setTaskToken(v)
  }

  const needsToken = (r?.task_auth_mode ?? 'token') === 'token'
  const hasToken = Boolean(taskToken.trim())
  const canUseInternal = !needsToken || hasToken

  const [pingMsg, setPingMsg] = React.useState<string | null>(null)
  const [reclaimMsg, setReclaimMsg] = React.useState<string | null>(null)
  const [olderThan, setOlderThan] = React.useState(600)
  const [limit, setLimit] = React.useState(50)

  const [dbStats, setDbStats] = React.useState<DbStats | null>(null)
  const [dbStatsMsg, setDbStatsMsg] = React.useState<string | null>(null)

  const [pruneMsg, setPruneMsg] = React.useState<string | null>(null)
  const [auditDays, setAuditDays] = React.useState(30)
  const [auditLimit, setAuditLimit] = React.useState(50000)
  const [ingDays, setIngDays] = React.useState(90)
  const [ingLimit, setIngLimit] = React.useState(5000)
  const [confirm, setConfirm] = React.useState('')

  async function ping() {
    setPingMsg(null)
    try {
      const res = await api.pingDb()
      setPingMsg(JSON.stringify(res, null, 2))
    } catch (e) {
      setPingMsg(`Ping failed: ${(e as Error).message}`)
    }
  }

  async function reclaim() {
    setReclaimMsg(null)
    try {
      const res = await api.reclaimStuck(olderThan, limit)
      setReclaimMsg(JSON.stringify(res, null, 2))
    } catch (e) {
      setReclaimMsg(`Reclaim failed: ${(e as Error).message}`)
    }
  }

  async function refreshDbStats() {
    setDbStatsMsg(null)
    try {
      const res = await api.dbStats()
      setDbStats(res)
    } catch (e) {
      setDbStats(null)
      setDbStatsMsg(`DB stats failed: ${(e as Error).message}`)
    }
  }

  async function prune(dryRun: boolean) {
    setPruneMsg(null)
    try {
      const res = await api.prune({
        dry_run: dryRun,
        confirm: dryRun ? undefined : confirm,
        audit_older_than_days: auditDays,
        audit_limit: auditLimit,
        ingestions_older_than_days: ingDays,
        ingestions_limit: ingLimit,
      })
      setPruneMsg(JSON.stringify(res, null, 2))
      // Refresh DB stats after a real prune.
      if (!dryRun) {
        await refreshDbStats()
      }
    } catch (e) {
      setPruneMsg(`Prune failed: ${(e as Error).message}`)
    }
  }

  return (
    <Page
      title="Ops"
      description="Runtime configuration, internal ops actions, and helpful links."
      actions={
        <div className="flex items-center gap-2">
          <a href="/docs" className="no-underline">
            <Button size="sm" variant="outline">
              API docs
            </Button>
          </a>
          <Link to="/upload" className="no-underline">
            <Button size="sm">Ingest</Button>
          </Link>
          <Link to="/audit" className="no-underline">
            <Button size="sm" variant="outline">
              Audit
            </Button>
          </Link>
        </div>
      }
    >
      {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
      {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}

      {q.data ? (
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Service</CardTitle>
              <CardDescription>Build and runtime details.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">ok: {q.data.ok ? 'true' : 'false'}</Badge>
                <Badge variant="outline">version: {q.data.version}</Badge>
              </div>

              <Separator />

              <div className="text-sm space-y-1">
                <div>
                  <span className="text-muted-foreground">queue:</span> <span className="font-mono">{r?.queue ?? '—'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">storage:</span> <span className="font-mono">{r?.storage_backend ?? '—'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">task auth:</span> <span className="font-mono">{r?.task_auth_mode ?? '—'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">ingest auth:</span> <span className="font-mono">{r?.ingest_auth_mode ?? '—'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">edge auth:</span> <span className="font-mono">{r?.edge_auth_mode ?? '—'}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">edge enroll:</span>{' '}
                  <span className="font-mono">{String(r?.edge_enroll_enabled ?? false)}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">edge signed URLs:</span>{' '}
                  <span className="font-mono">{String(r?.enable_edge_signed_urls ?? false)}</span>
                </div>
                <div>
                  <span className="text-muted-foreground">edge datasets:</span>{' '}
                  <span className="font-mono">{(r?.edge_allowed_datasets ?? []).join(', ') || '—'}</span>
                </div>
              </div>

              <Separator />

              <div className="text-xs text-muted-foreground space-y-1">
                <div>ENABLE_DEMO_ENDPOINTS: {String(r?.enable_demo_endpoints ?? false)}</div>
                <div>ENABLE_INGEST_FROM_PATH: {String(r?.enable_ingest_from_path ?? false)}</div>
                <div>ENABLE_SIGNED_URLS: {String(r?.enable_signed_urls ?? false)}</div>
                <div>REQUIRE_SIGNED_URL_SHA256: {String(r?.require_signed_url_sha256 ?? false)}</div>
                <div>ENABLE_GCS_EVENT_INGESTION: {String(r?.enable_gcs_event_ingestion ?? false)}</div>
                <div>ENABLE_CONTRACT_WRITE: {String(r?.enable_contract_write ?? false)}</div>
                <div>ENABLE_INCOMING_LIST: {String(r?.enable_incoming_list ?? false)}</div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Internal auth</CardTitle>
              <CardDescription>Used for privileged endpoints (Cloud Tasks, signed URLs, ops).</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1">
                <Label>Task token</Label>
                <Input
                  value={taskToken}
                  onChange={(e) => updateToken(e.target.value)}
                  placeholder={needsToken ? 'Required in token mode' : 'Optional'}
                />
                <div className="text-xs text-muted-foreground">
                  Stored in <span className="font-mono">localStorage</span> as <span className="font-mono">eventpulse.taskToken</span>.
                </div>
                {needsToken && !hasToken ? (
                  <div className="text-xs text-amber-600">Token mode enabled — internal actions will fail until a token is set.</div>
                ) : null}
              </div>

              <Separator />

              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={ping}>
                  Ping
                </Button>
                <Badge variant={canUseInternal ? 'success' : 'warning'}>internal: {canUseInternal ? 'enabled' : 'locked'}</Badge>
              </div>
              {pingMsg ? <pre className="overflow-x-auto rounded-md border bg-muted/30 p-3 text-xs">{pingMsg}</pre> : null}

              <Separator />

              <div className="space-y-2">
                <div className="text-sm font-medium">Reclaim stuck ingestions</div>
                <div className="grid gap-2 md:grid-cols-2">
                  <div className="space-y-1">
                    <Label>Older than (seconds)</Label>
                    <Input type="number" value={olderThan} onChange={(e) => setOlderThan(parseInt(e.target.value || '600', 10))} />
                  </div>
                  <div className="space-y-1">
                    <Label>Limit</Label>
                    <Input type="number" value={limit} onChange={(e) => setLimit(parseInt(e.target.value || '50', 10))} />
                  </div>
                </div>
                <Button size="sm" onClick={reclaim} disabled={!canUseInternal}>
                  Reclaim
                </Button>
                {reclaimMsg ? <pre className="overflow-x-auto rounded-md border bg-muted/30 p-3 text-xs">{reclaimMsg}</pre> : null}
                <div className="text-xs text-muted-foreground">
                  Moves stale <span className="font-mono">PROCESSING</span> ingestions back to <span className="font-mono">RECEIVED</span> for retry.
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>Maintenance</CardTitle>
              <CardDescription>DB size + retention pruning (internal auth required).</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="outline" onClick={refreshDbStats} disabled={!canUseInternal}>
                  Refresh DB stats
                </Button>
                {dbStats ? (
                  <Badge variant="outline">db: {fmtBytes(dbStats.database.size_bytes)}</Badge>
                ) : (
                  <Badge variant="outline">db: —</Badge>
                )}
              </div>

              {dbStatsMsg ? <div className="text-xs text-destructive">{dbStatsMsg}</div> : null}

              {dbStats ? (
                <div className="grid gap-2 md:grid-cols-2">
                  <div className="text-sm">
                    <div className="text-muted-foreground">Database</div>
                    <div className="font-mono">{dbStats.database.name || '—'}</div>
                    <div className="text-muted-foreground">Captured</div>
                    <div className="font-mono">{dbStats.captured_at}</div>
                  </div>
                  <div className="text-sm">
                    <div className="text-muted-foreground">Top tables</div>
                    <div className="space-y-1">
                      {dbStats.tables.slice(0, 5).map((t) => (
                        <div key={t.name} className="flex items-center justify-between gap-2">
                          <span className="font-mono">{t.name}</span>
                          <span className="text-muted-foreground">{fmtBytes(t.size_bytes)} / ~{t.row_estimate}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}

              <Separator />

              <div className="space-y-2">
                <div className="text-sm font-medium">Prune retention data</div>
                <div className="grid gap-2 md:grid-cols-4">
                  <div className="space-y-1">
                    <Label>Audit days</Label>
                    <Input type="number" value={auditDays} onChange={(e) => setAuditDays(parseInt(e.target.value || '30', 10))} />
                  </div>
                  <div className="space-y-1">
                    <Label>Audit limit</Label>
                    <Input type="number" value={auditLimit} onChange={(e) => setAuditLimit(parseInt(e.target.value || '50000', 10))} />
                  </div>
                  <div className="space-y-1">
                    <Label>Ingestion days</Label>
                    <Input type="number" value={ingDays} onChange={(e) => setIngDays(parseInt(e.target.value || '90', 10))} />
                  </div>
                  <div className="space-y-1">
                    <Label>Ingestion limit</Label>
                    <Input type="number" value={ingLimit} onChange={(e) => setIngLimit(parseInt(e.target.value || '5000', 10))} />
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="outline" onClick={() => prune(true)} disabled={!canUseInternal}>
                    Preview (dry run)
                  </Button>
                  <Input
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    placeholder="Type PRUNE to enable"
                    className="max-w-[220px]"
                  />
                  <Button size="sm" onClick={() => prune(false)} disabled={!canUseInternal || confirm.trim().toUpperCase() !== 'PRUNE'}>
                    Prune now
                  </Button>
                </div>

                {pruneMsg ? <pre className="overflow-x-auto rounded-md border bg-muted/30 p-3 text-xs">{pruneMsg}</pre> : null}

                <div className="text-xs text-muted-foreground">
                  Deletes are <span className="font-mono">oldest-first</span> and limited. Ingestion pruning only touches terminal rows
                  (<span className="font-mono">LOADED</span> / <span className="font-mono">FAILED_*</span>) and cascades to quality/lineage.
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>Paths</CardTitle>
              <CardDescription>Filesystem or bucket configuration.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div>
                <span className="text-muted-foreground">contracts_dir:</span> <span className="font-mono">{r?.contracts_dir ?? '—'}</span>
              </div>
              <div>
                <span className="text-muted-foreground">incoming_dir:</span> <span className="font-mono">{r?.incoming_dir ?? '—'}</span>
              </div>
              <div>
                <span className="text-muted-foreground">archive_dir:</span> <span className="font-mono">{r?.archive_dir ?? '—'}</span>
              </div>
              <Separator />
              <div>
                <span className="text-muted-foreground">raw_data_dir:</span> <span className="font-mono">{r?.raw_data_dir ?? '—'}</span>
              </div>
              <div>
                <span className="text-muted-foreground">raw_gcs_bucket:</span> <span className="font-mono">{r?.raw_gcs_bucket ?? '—'}</span>
              </div>
              <div>
                <span className="text-muted-foreground">raw_gcs_prefix:</span> <span className="font-mono">{r?.raw_gcs_prefix ?? '—'}</span>
              </div>
              <Separator />
              <div className="text-xs text-muted-foreground">Note: In Cloud Run, contracts are baked into the image (or mounted). Raw files live in GCS.</div>
            </CardContent>
          </Card>

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>Raw meta (JSON)</CardTitle>
              <CardDescription>Full /api/meta payload for troubleshooting.</CardDescription>
            </CardHeader>
            <CardContent>
              <pre className="overflow-x-auto rounded-md border bg-muted/30 p-4 text-xs">{JSON.stringify(q.data, null, 2)}</pre>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </Page>
  )
}

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, getTaskTokenForUi, type AuditEvent, type DeviceInfo, type DeviceLatestReading } from '../api'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Checkbox,
  CopyButton,
  DataTable,
  Input,
  Label,
  Page,
  Separator,
  Sparkline,
  Tabs,
} from '../portfolio-ui'

type TelemetryRow = Record<string, any>

function fmtTime(v: string | null | undefined) {
  if (!v) return '—'
  try {
    const d = new Date(v)
    return d.toLocaleString()
  } catch {
    return v
  }
}

function fmtNum(v: any, digits = 3) {
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

function truncate(s: string, n = 120) {
  const t = s ?? ''
  if (t.length <= n) return t
  return `${t.slice(0, n - 1)}…`
}

function computeOffline(
  lastSeenAt?: string | null,
  lastEventTs?: string | null,
  thresholdSeconds = 600,
): { isOffline: boolean; basis: 'last_seen_at' | 'last_event_ts' | 'none' } {
  const now = Date.now()
  const threshMs = Math.max(60, thresholdSeconds) * 1000

  if (lastSeenAt) {
    const t = Date.parse(lastSeenAt)
    if (Number.isFinite(t)) return { isOffline: now - t > threshMs, basis: 'last_seen_at' }
  }
  if (lastEventTs) {
    const t = Date.parse(lastEventTs)
    if (Number.isFinite(t)) return { isOffline: now - t > threshMs, basis: 'last_event_ts' }
  }
  return { isOffline: true, basis: 'none' }
}

type SensorSeverity = 'ok' | 'warning' | 'critical'

function normalizeSeverity(severity: any, severityNum: any): SensorSeverity {
  const s = String(severity ?? '').toLowerCase()
  if (s === 'critical') return 'critical'
  if (s === 'warning') return 'warning'
  const n = typeof severityNum === 'number' ? severityNum : Number(severityNum)
  if (Number.isFinite(n)) {
    if (n >= 2) return 'critical'
    if (n === 1) return 'warning'
  }
  return 'ok'
}

function severityVariant(sev: SensorSeverity): 'outline' | 'warning' | 'destructive' {
  if (sev === 'critical') return 'destructive'
  if (sev === 'warning') return 'warning'
  return 'outline'
}

export function DeviceDetailPage() {
  const { deviceId } = useParams({ from: '/devices/$deviceId' })

  const [tab, setTab] = React.useState<'overview' | 'telemetry' | 'audit' | 'commands'>('overview')
  const [rotateMsg, setRotateMsg] = React.useState<string | null>(null)
  const [revokeMsg, setRevokeMsg] = React.useState<string | null>(null)

  // Telemetry table UX
  const [onlyReadings, setOnlyReadings] = React.useState(true)
  const [sensorFilter, setSensorFilter] = React.useState('')

  const metaQ = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const r = metaQ.data?.runtime
  const needsToken = (r?.task_auth_mode ?? 'token') === 'token'
  const hasToken = Boolean(getTaskTokenForUi().trim())
  const canUseInternal = !needsToken || hasToken

  const deviceQ = useQuery({
    queryKey: ['device', deviceId],
    queryFn: () => api.getDevice(deviceId),
    enabled: canUseInternal,
    refetchInterval: 30_000,
  })

  const telemetryQ = useQuery({
    queryKey: ['deviceTelemetry', deviceId, 200],
    queryFn: () => api.deviceTelemetry(deviceId, 200),
    enabled: canUseInternal,
    refetchInterval: 15_000,
  })

  const latestReadingsQ = useQuery({
    queryKey: ['deviceLatestReadings', deviceId, 200],
    queryFn: () => api.deviceLatestReadings(deviceId, 200),
    enabled: canUseInternal,
    refetchInterval: 15_000,
  })

  const auditQ = useQuery({
    queryKey: ['audit_events', 200, 'all', 'all', '', deviceId],
    queryFn: () => api.auditEvents(200, undefined, undefined, undefined, deviceId),
    refetchInterval: 15_000,
  })

  const device: DeviceInfo | undefined = deviceQ.data?.device
  const rows: TelemetryRow[] = telemetryQ.data?.rows ?? []
  const latestRows: DeviceLatestReading[] = latestReadingsQ.data?.rows ?? []
  const lastEventTs: string | null = (rows[0] as any)?.ts ?? null
  const latestViewExists = latestReadingsQ.data?.view_exists

  const keySensors = React.useMemo(
    () => [
      { sensor: 'temp_c', label: 'Temperature', units: 'C', digits: 1 },
      { sensor: 'humidity_pct', label: 'Humidity', units: '%', digits: 0 },
      { sensor: 'water_pressure_psi', label: 'Water pressure', units: 'psi', digits: 1 },
      { sensor: 'oil_pressure_psi', label: 'Oil pressure', units: 'psi', digits: 1 },
      { sensor: 'oil_life_pct', label: 'Oil life', units: '%', digits: 0 },
      { sensor: 'oil_level_pct', label: 'Oil level', units: '%', digits: 0 },
      { sensor: 'drip_oil_level_pct', label: 'Drip oil level', units: '%', digits: 0 },
    ],
    [],
  )

  const latestBySensor = React.useMemo(() => {
    const m = new Map<string, DeviceLatestReading>()
    for (const r of latestRows) {
      const sensor = String((r as any)?.sensor ?? '')
      if (!sensor) continue
      m.set(sensor, r)
    }
    return m
  }, [latestRows])

  // Build small per-sensor series for sparklines.
  // API returns rows sorted by ts DESC; iterate in reverse for chronological order.
  const seriesBySensor = React.useMemo(() => {
    const m = new Map<string, Array<{ ts: number; value: number }>>()
    for (let i = rows.length - 1; i >= 0; i--) {
      const r = rows[i] as any
      if (!r || r.event_type !== 'reading') continue
      const sensor = String(r.sensor ?? '')
      if (!sensor) continue
      const value = typeof r.value === 'number' ? r.value : Number(r.value)
      if (!Number.isFinite(value)) continue
      const ts = Date.parse(String(r.ts ?? ''))
      if (!Number.isFinite(ts)) continue

      const arr = m.get(sensor) ?? []
      arr.push({ ts, value })
      if (!m.has(sensor)) m.set(sensor, arr)
    }
    return m
  }, [rows])

  const alertSummary = React.useMemo(() => {
    const active = keySensors
      .map((s) => {
        const row = latestBySensor.get(s.sensor)
        const sev = row ? normalizeSeverity((row as any)?.severity, (row as any)?.severity_num) : ('ok' as const)
        return {
          sensor: s.sensor,
          label: s.label,
          severity: sev,
          alertType: (row as any)?.alert_type,
          value: (row as any)?.value,
          units: (row as any)?.units,
          ts: (row as any)?.ts,
        }
      })
      .filter((x) => x.severity !== 'ok')

    const critical = active.filter((a) => a.severity === 'critical').length
    const warning = active.filter((a) => a.severity === 'warning').length
    return { active, critical, warning, total: active.length }
  }, [keySensors, latestBySensor])

  const filteredRows = React.useMemo(() => {
    const q = sensorFilter.trim().toLowerCase()
    let out = rows
    if (onlyReadings) {
      out = out.filter((r) => String((r as any)?.event_type ?? '') === 'reading')
    }
    if (q) {
      out = out.filter((r) => String((r as any)?.sensor ?? '').toLowerCase().includes(q))
    }
    return out
  }, [rows, onlyReadings, sensorFilter])

  const thresholdSeconds = r?.edge_offline_threshold_seconds ?? 600
  const offline = computeOffline(device?.last_seen_at ?? null, lastEventTs, thresholdSeconds)

  const apiBaseUrl = React.useMemo(() => {
    try {
      const loc = window.location
      return `${loc.protocol}//${loc.host}`
    } catch {
      return ''
    }
  }, [])

  const installCmd = React.useMemo(() => {
    const base = apiBaseUrl || 'https://YOUR_CLOUD_RUN_URL'
    const did = deviceId
    const lbl = (device?.label ?? '').trim()
    const parts = [
      'sudo bash field_ops/rpi/install.sh \\',
      `  --api-base-url "${base}" \\`,
      did ? `  --device-id "${did}" \\` : null,
      lbl ? `  --device-label "${lbl}" \\` : null,
      '  --enroll-token "PASTE_EDGE_ENROLL_TOKEN"',
    ]
      .filter(Boolean)
      .join('\n')
    return parts
  }, [apiBaseUrl, deviceId, device?.label])

  async function rotateToken() {
    setRotateMsg(null)
    setRevokeMsg(null)
    try {
      const res = await api.rotateDeviceToken(deviceId)
      setRotateMsg(JSON.stringify(res, null, 2))
      // Refresh device info (best effort)
      await deviceQ.refetch()
    } catch (e) {
      setRotateMsg(`Rotate failed: ${(e as Error).message}`)
    }
  }

  async function revoke() {
    setRotateMsg(null)
    setRevokeMsg(null)
    try {
      const res = await api.revokeDevice(deviceId)
      setRevokeMsg(JSON.stringify(res, null, 2))
      await deviceQ.refetch()
    } catch (e) {
      setRevokeMsg(`Revoke failed: ${(e as Error).message}`)
    }
  }

  const telemetryColumns: ColumnDef<TelemetryRow>[] = [
    {
      header: 'ts',
      accessorKey: 'ts',
      cell: (info) => <span className="font-mono text-xs">{fmtTime(String(info.getValue() ?? ''))}</span>,
    },
    {
      header: 'type',
      accessorKey: 'event_type',
      cell: (info) => {
        const v = String(info.getValue() ?? '')
        const variant = v === 'error' ? 'destructive' : v === 'heartbeat' ? 'secondary' : 'outline'
        return <Badge variant={variant as any}>{v || '—'}</Badge>
      },
    },
    {
      header: 'sensor',
      accessorKey: 'sensor',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'value',
      accessorKey: 'value',
      cell: (info) => <span className="font-mono text-xs">{fmtNum(info.getValue(), 3)}</span>,
    },
    {
      header: 'units',
      accessorKey: 'units',
      cell: (info) => <span className="text-xs text-muted-foreground">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'lat',
      accessorKey: 'lat',
      cell: (info) => <span className="font-mono text-xs">{fmtNum(info.getValue(), 5)}</span>,
    },
    {
      header: 'lon',
      accessorKey: 'lon',
      cell: (info) => <span className="font-mono text-xs">{fmtNum(info.getValue(), 5)}</span>,
    },
    {
      header: 'rssi_dbm',
      accessorKey: 'rssi_dbm',
      cell: (info) => <span className="font-mono text-xs">{fmtNum(info.getValue(), 0)}</span>,
    },
    {
      header: 'battery_v',
      accessorKey: 'battery_v',
      cell: (info) => <span className="font-mono text-xs">{fmtNum(info.getValue(), 2)}</span>,
    },
    {
      header: 'fw',
      accessorKey: 'firmware_version',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'status',
      accessorKey: 'status',
      cell: (info) => <span className="text-xs text-muted-foreground">{truncate(String(info.getValue() ?? '—'), 80)}</span>,
    },
    {
      header: 'message',
      accessorKey: 'message',
      cell: (info) => <span className="text-xs text-muted-foreground">{truncate(String(info.getValue() ?? '—'), 80)}</span>,
    },
  ]

  const auditItems: AuditEvent[] = auditQ.data?.items ?? []
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
      header: 'dataset',
      accessorKey: 'dataset',
      cell: (info) => {
        const v = info.getValue() as any
        return v ? <Badge variant="outline">{String(v)}</Badge> : <span className="text-muted-foreground">—</span>
      },
    },
    {
      header: 'details',
      accessorKey: 'details',
      cell: (info) => <span className="font-mono text-xs text-muted-foreground">{truncate(JSON.stringify(info.getValue() ?? {}), 140)}</span>,
    },
  ]

  return (
    <Page
      title={`Device: ${deviceId}`}
      description="Field ops view for a single Raspberry Pi / edge device."
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/devices" className="no-underline">
            <Button size="sm" variant="outline">Back</Button>
          </Link>
          <a href="/docs" className="no-underline">
            <Button size="sm" variant="outline">API docs</Button>
          </a>
        </div>
      }
    >
      {needsToken && !hasToken ? (
        <Card className="mb-4">
          <CardHeader>
            <CardTitle>Internal auth required</CardTitle>
            <CardDescription>
              Set <span className="font-mono">TASK_TOKEN</span> in the Ops page to unlock internal endpoints used by this view.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link to="/meta" className="no-underline">
              <Button size="sm">Open Ops</Button>
            </Link>
          </CardContent>
        </Card>
      ) : null}

      <Tabs
        items={[
          { value: 'overview', label: 'Overview' },
          { value: 'telemetry', label: 'Telemetry' },
          { value: 'audit', label: 'Audit' },
          { value: 'commands', label: 'Commands' },
        ]}
        value={tab}
        onValueChange={(v) => setTab(v as any)}
      />

      <div className="mt-4">
        {tab === 'overview' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Status</CardTitle>
                <CardDescription>Offline heuristic tuned by EDGE_OFFLINE_THRESHOLD_SECONDS.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  {device?.revoked_at ? <Badge variant="destructive">revoked</Badge> : null}
                  {offline.isOffline && !device?.revoked_at ? <Badge variant="warning">offline</Badge> : null}
                  {!offline.isOffline && !device?.revoked_at ? <Badge variant="success">online</Badge> : null}
                  <Badge variant="outline">threshold: {thresholdSeconds}s</Badge>
                  <Badge variant="outline">basis: {offline.basis}</Badge>
                </div>

                <Separator />

                <div className="text-sm space-y-1">
                  <div>
                    <span className="text-muted-foreground">label:</span> {device?.label ?? '—'}
                  </div>
                  <div>
                    <span className="text-muted-foreground">last seen:</span> <span className="font-mono">{fmtTime(device?.last_seen_at ?? null)}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">last event:</span> <span className="font-mono">{fmtTime(lastEventTs)}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">last ip:</span> <span className="font-mono">{device?.last_seen_ip ?? '—'}</span>
                  </div>
                  <div>
                    <span className="text-muted-foreground">user-agent:</span> <span className="font-mono">{truncate(device?.last_user_agent ?? '—', 80)}</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Actions</CardTitle>
                <CardDescription>Token rotation + revocation (internal auth).</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" onClick={rotateToken} disabled={!canUseInternal}>Rotate token</Button>
                  <Button size="sm" variant="destructive" onClick={revoke} disabled={!canUseInternal || Boolean(device?.revoked_at)}>
                    Revoke device
                  </Button>
                </div>

                {rotateMsg ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <CopyButton text={rotateMsg} label="Copy rotate result" />
                      <Badge variant="outline">token shown once</Badge>
                    </div>
                    <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto whitespace-pre-wrap">{rotateMsg}</pre>
                  </div>
                ) : null}

                {revokeMsg ? <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto whitespace-pre-wrap">{revokeMsg}</pre> : null}

                <Separator />

                <div className="text-xs text-muted-foreground">
                  After rotating/revoking: on the Pi, remove the saved device token and restart to re-enroll (if enrollment is enabled).
                </div>
              </CardContent>
            </Card>

            <Card className="md:col-span-2">
              <CardHeader>
                <CardTitle>Sensor snapshot</CardTitle>
                <CardDescription>
                  Latest per-sensor readings from the <span className="font-mono">latest_readings</span> mart (server-scored alerts).
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {!canUseInternal ? (
                  <div className="text-sm text-muted-foreground">Internal auth is required to view sensor readings.</div>
                ) : (
                  <>
                    {latestViewExists === false ? (
                      <div className="text-sm text-muted-foreground">
                        The <span className="font-mono">latest_readings</span> mart isn’t available yet. Ingest edge telemetry first (demo seed or a real device).
                      </div>
                    ) : null}

                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">sensors tracked: {keySensors.length}</Badge>
                      <Badge variant={keySensors.some((s) => !latestBySensor.get(s.sensor)) ? 'warning' : 'success'}>
                        missing: {keySensors.filter((s) => !latestBySensor.get(s.sensor)).length}
                      </Badge>
                      <Badge variant={alertSummary.total ? 'warning' : 'success'}>alerts: {alertSummary.total}</Badge>
                      <Badge variant={alertSummary.critical ? 'destructive' : 'outline'}>critical: {alertSummary.critical}</Badge>
                      <Badge variant={alertSummary.warning ? 'warning' : 'outline'}>warning: {alertSummary.warning}</Badge>
                      <Badge variant="outline">source: marts_edge_telemetry_latest_readings</Badge>
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                      {keySensors.map((s) => {
                        const row = latestBySensor.get(s.sensor)
                        const series = seriesBySensor.get(s.sensor) ?? []
                        const sparkValues = series.slice(-32).map((p) => p.value)
                        const ts = (row as any)?.ts as string | undefined
                        const units = ((row as any)?.units as string | undefined) ?? s.units
                        const value = (row as any)?.value
                        const sev = row ? normalizeSeverity((row as any)?.severity, (row as any)?.severity_num) : ('ok' as const)
                        const sevVariant = !row ? 'outline' : severityVariant(sev)
                        return (
                          <div key={s.sensor} className="rounded-md border bg-muted/10 p-3">
                            <div className="flex items-center justify-between gap-2">
                              <div className="text-sm font-medium">{s.label}</div>
                              {row ? (
                                <Badge variant={sevVariant as any} title={String((row as any)?.alert_type ?? '')}>
                                  {sev}
                                </Badge>
                              ) : (
                                <Badge variant="outline">missing</Badge>
                              )}
                            </div>
                            <div className="mt-1 flex items-end gap-2">
                              <div className="text-2xl font-semibold">{row ? fmtNum(value, s.digits) : '—'}</div>
                              <div className="text-sm text-muted-foreground">{row ? units : ''}</div>
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground">
                              {row ? (
                                <>
                                  <span className="font-mono">{s.sensor}</span> · <span className="font-mono">{fmtTime(ts)}</span>
                                </>
                              ) : (
                                <span className="font-mono">{s.sensor}</span>
                              )}
                            </div>

                            {sparkValues.length >= 2 ? (
                              <div className="mt-2">
                                <Sparkline
                                  values={sparkValues}
                                  width={160}
                                  height={28}
                                  className="text-muted-foreground/60"
                                  title={`${s.label} trend`}
                                />
                              </div>
                            ) : null}
                          </div>
                        )
                      })}
                    </div>

                    <div className="text-xs text-muted-foreground">
                      Tip: set <span className="font-mono">EDGE_SENSOR_MODE=script</span> on the Pi to stream real sensor readings (see docs/FIELD_OPS.md).
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            <Card className="md:col-span-2">
              <CardHeader>
                <CardTitle>Metadata</CardTitle>
                <CardDescription>Operator notes and device registry fields.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 md:grid-cols-2">
                <div className="text-sm space-y-1">
                  <div><span className="text-muted-foreground">created:</span> <span className="font-mono">{fmtTime(device?.created_at ?? null)}</span></div>
                  <div><span className="text-muted-foreground">updated:</span> <span className="font-mono">{fmtTime(device?.updated_at ?? null)}</span></div>
                  <div><span className="text-muted-foreground">token updated:</span> <span className="font-mono">{fmtTime(device?.token_updated_at ?? null)}</span></div>
                  <div><span className="text-muted-foreground">revoked:</span> <span className="font-mono">{fmtTime(device?.revoked_at ?? null)}</span></div>
                </div>
                <div>
                  <div className="text-sm font-medium mb-2">metadata JSON</div>
                  <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto whitespace-pre-wrap">
                    {JSON.stringify(device?.metadata ?? {}, null, 2)}
                  </pre>
                </div>
              </CardContent>
            </Card>
          </div>
        ) : null}

        {tab === 'telemetry' ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">rows: {filteredRows.length}</Badge>
              <Badge variant="outline">total: {rows.length}</Badge>
              {telemetryQ.isFetching ? <Badge variant="warning">updating…</Badge> : <Badge variant="success">live</Badge>}
              {telemetryQ.error ? <Badge variant="destructive">error</Badge> : null}
            </div>

            {!canUseInternal ? (
              <div className="text-sm text-muted-foreground">Internal auth is required to view per-device telemetry rows.</div>
            ) : null}

            <div className="flex flex-wrap items-center gap-3 rounded-md border bg-muted/10 p-3">
              <div className="flex items-center gap-2">
                <Checkbox
                  id="onlyReadings"
                  checked={onlyReadings}
                  onChange={(e) => setOnlyReadings(e.currentTarget.checked)}
                />
                <Label htmlFor="onlyReadings" className="text-sm">Readings only</Label>
              </div>

              <div className="flex items-center gap-2">
                <Label htmlFor="sensorFilter" className="text-sm">Sensor</Label>
                <Input
                  id="sensorFilter"
                  value={sensorFilter}
                  onChange={(e) => setSensorFilter(e.target.value)}
                  placeholder="e.g. temp_c"
                  className="h-8 w-56"
                />
              </div>

              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setOnlyReadings(false)
                  setSensorFilter('')
                }}
              >
                Reset
              </Button>
            </div>

            <DataTable data={filteredRows} columns={telemetryColumns} height={640} columnMinWidth={220} />
            <div className="text-xs text-muted-foreground">Pulled from curated_edge_telemetry filtered by device_id (internal endpoint).</div>
          </div>
        ) : null}

        {tab === 'audit' ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">events: {auditItems.length}</Badge>
              {auditQ.isFetching ? <Badge variant="warning">updating…</Badge> : <Badge variant="success">live</Badge>}
              {auditQ.error ? <Badge variant="destructive">error</Badge> : null}
            </div>

            <DataTable data={auditItems} columns={auditColumns} height={520} columnMinWidth={220} />
            <div className="text-xs text-muted-foreground">Filtered by actor = device_id.</div>
          </div>
        ) : null}

        {tab === 'commands' ? (
          <div className="grid gap-4 md:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Install / redeploy</CardTitle>
                <CardDescription>Re-run installer (idempotent) or use it for a fresh SD card image.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="flex items-center gap-2">
                  <CopyButton text={installCmd} label="Copy install command" />
                  <Badge variant="outline">edit token before running</Badge>
                </div>
                <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto">{installCmd}</pre>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>On-device triage</CardTitle>
                <CardDescription>Useful SSH commands for day-2 operations.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {[
                  {
                    label: 'Check service',
                    cmd: 'sudo systemctl status eventpulse-edge-agent',
                  },
                  {
                    label: 'Tail logs',
                    cmd: 'sudo journalctl -u eventpulse-edge-agent -n 200 --no-pager',
                  },
                  {
                    label: 'Restart',
                    cmd: 'sudo systemctl restart eventpulse-edge-agent',
                  },
                  {
                    label: 'Force re-enroll (delete token)',
                    cmd: 'sudo rm -f /var/lib/eventpulse-edge/spool/device_token.txt && sudo systemctl restart eventpulse-edge-agent',
                  },
                  {
                    label: 'Update container',
                    cmd: 'sudo /usr/local/bin/eventpulse-edge-agent-update',
                  },
                ].map((x) => (
                  <div key={x.label} className="space-y-1">
                    <div className="flex items-center gap-2">
                      <div className="text-sm font-medium">{x.label}</div>
                      <CopyButton text={x.cmd} label="Copy" size="sm" />
                    </div>
                    <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto">{x.cmd}</pre>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        ) : null}
      </div>
    </Page>
  )
}

import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, getTaskTokenForUi, type DeviceInfo } from '../api'
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
  CopyButton,
} from '../portfolio-ui'

type DeviceStatusRow = {
  device_id: string
  label?: string | null
  last_seen_at?: string | null
  last_seen_ip?: string | null
  revoked_at?: string | null
  event_count: number
  last_event_ts: string | null
  last_loaded_at: string | null
  alert_count?: number | null
  alert_severity?: string | null
  alerts?: string[] | null
  is_offline: boolean
}

type DeviceAlertRow = {
  device_id: string
  label?: string | null
  revoked_at?: string | null
  sensor: string
  value: number
  units?: string | null
  ts?: string | null
  severity_num?: number | null
  severity?: string | null
  alert_type?: string | null
}

type DeviceGeoStatusRow = DeviceStatusRow & {
  lat?: number | null
  lon?: number | null
  last_geo_ts?: string | null
}

function fmtTime(v: string | null | undefined) {
  if (!v) return '—'
  try {
    const d = new Date(v)
    return d.toLocaleString()
  } catch {
    return String(v)
  }
}

function statusBadge(row: { is_offline: boolean; revoked_at?: string | null }) {
  if (row.revoked_at) return <Badge variant="destructive">revoked</Badge>
  if (row.is_offline) return <Badge variant="destructive">offline</Badge>
  return <Badge variant="secondary">online</Badge>
}

function DeviceGeoScatter(props: { rows: DeviceGeoStatusRow[]; height?: number }) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null)
  const height = props.height ?? 420

  const points = React.useMemo(() => {
    const out: Array<{ lat: number; lon: number; status: 'online' | 'offline' | 'revoked'; alertCount: number; deviceId: string; label?: string | null }> = []
    for (const r of props.rows ?? []) {
      const lat = Number((r as any).lat)
      const lon = Number((r as any).lon)
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue
      const status = (r as any).revoked_at ? 'revoked' : (r as any).is_offline ? 'offline' : 'online'
      const alertCount = Number((r as any).alert_count ?? 0)
      out.push({ lat, lon, status, alertCount: Number.isFinite(alertCount) ? alertCount : 0, deviceId: String((r as any).device_id ?? ''), label: (r as any).label ?? null })
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
      ctx.fillText('No device geo points yet. Send telemetry with lat/lon.', 12, 24)
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
      const r = Math.max(2.2, Math.min(6.0, 2.2 + Math.log10(p.alertCount + 1)))

      if (p.status === 'revoked') ctx.fillStyle = 'rgba(107, 114, 128, 0.55)'
      else if (p.alertCount > 0) ctx.fillStyle = 'rgba(239, 68, 68, 0.60)'
      else if (p.status === 'offline') ctx.fillStyle = 'rgba(245, 158, 11, 0.60)'
      else ctx.fillStyle = 'rgba(59, 130, 246, 0.55)'

      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
    }

    // caption
    ctx.fillStyle = 'rgba(0,0,0,0.60)'
    ctx.font = '12px ui-sans-serif, system-ui'
    ctx.fillText(
      `devices: ${points.length}   lat: ${minLat.toFixed(3)}…${maxLat.toFixed(3)}   lon: ${minLon.toFixed(3)}…${maxLon.toFixed(3)}`,
      12,
      h - 10,
    )
  }, [points])

  return (
    <div className="w-full">
      <div className="rounded-md border bg-muted/10 overflow-hidden">
        <canvas ref={canvasRef} className="w-full" style={{ height }} />
      </div>
      <div className="text-xs text-muted-foreground mt-2">
        This is a lightweight scatter plot (no map tiles). Points are sized by alert count and colored by status.
      </div>
    </div>
  )
}

export function DevicesPage() {
  const nav = useNavigate()
  const metaQ = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const r = metaQ.data?.runtime

  const [tab, setTab] = React.useState<'status' | 'map' | 'alerts' | 'provisioning'>('status')

  const [taskToken, setTaskTokenState] = React.useState(getTaskTokenForUi())
  React.useEffect(() => setTaskTokenState(getTaskTokenForUi()), [])

  const needsToken = (r?.task_auth_mode ?? 'token') === 'token'
  const hasToken = Boolean(taskToken.trim())
  const canUseInternal = !needsToken || hasToken

  const apiBaseUrl = React.useMemo(() => {
    if (typeof window === 'undefined') return ''
    return window.location.origin
  }, [])

  function edgeEnvSnippet(deviceId: string, deviceToken: string) {
    const base = apiBaseUrl || 'https://YOUR_CLOUD_RUN_URL'
    return [
      '# edge.env (manual provisioning — keep secret)',
      `EDGE_API_BASE_URL="${base}"`,
      `EDGE_DEVICE_ID="${deviceId}"`,
      `EDGE_DEVICE_TOKEN="${deviceToken}"`,
      '',
      '# Recommended defaults',
      'EDGE_DATASET="edge_telemetry"',
      'EDGE_UPLOAD_MODE="signed_url"',
      'EDGE_SENSOR_MODE="simulated"',
      '',
    ].join('\n')
  }

  const devicesQ = useQuery({
    queryKey: ['devices', 'edge_telemetry'],
    queryFn: async () => {
      const res = await api.getMart('edge_telemetry', 'device_status', 1000)
      return (res.rows ?? []) as DeviceStatusRow[]
    },
    refetchInterval: 10_000,
  })

  const alertsQ = useQuery({
    queryKey: ['device-alerts', 'edge_telemetry'],
    queryFn: async () => {
      const res = await api.getMart('edge_telemetry', 'device_alerts', 2000)
      return (res.rows ?? []) as DeviceAlertRow[]
    },
    enabled: tab === 'alerts',
    refetchInterval: 10_000,
  })

  const geoQ = useQuery({
    queryKey: ['device-geo', 'edge_telemetry'],
    queryFn: async () => {
      const res = await api.getMart('edge_telemetry', 'device_geo_status', 2000)
      return (res.rows ?? []) as DeviceGeoStatusRow[]
    },
    enabled: tab === 'map',
    refetchInterval: 15_000,
    retry: false,
  })

  const registryQ = useQuery({
    queryKey: ['device-registry'],
    queryFn: () => api.listDevices(200),
    enabled: canUseInternal,
    refetchInterval: 15_000,
  })

  const rows = (devicesQ.data ?? []).map((rr) => ({
    ...rr,
    event_count: Number((rr as any).event_count ?? 0),
    is_offline: Boolean((rr as any).is_offline),
    label: (rr as any).label ?? null,
    last_seen_at: (rr as any).last_seen_at ?? null,
    last_seen_ip: (rr as any).last_seen_ip ?? null,
    revoked_at: (rr as any).revoked_at ?? null,
    alert_count: Number((rr as any).alert_count ?? 0),
    alert_severity: (rr as any).alert_severity ?? null,
    alerts: (rr as any).alerts ?? null,
  }))

  const alertRows = (alertsQ.data ?? []).map((rr) => ({
    ...rr,
    device_id: String((rr as any).device_id ?? ''),
    sensor: String((rr as any).sensor ?? ''),
    value: Number((rr as any).value ?? 0),
    units: (rr as any).units ?? null,
    ts: (rr as any).ts ?? null,
    severity_num: Number((rr as any).severity_num ?? 0),
    severity: (rr as any).severity ?? null,
    alert_type: (rr as any).alert_type ?? null,
    label: (rr as any).label ?? null,
    revoked_at: (rr as any).revoked_at ?? null,
  }))

  const registryDevices = (registryQ.data?.devices ?? []) as DeviceInfo[]

  const totals = React.useMemo(() => {
    const total = rows.length
    const offline = rows.filter((x) => x.is_offline && !x.revoked_at).length
    const revoked = rows.filter((x) => Boolean(x.revoked_at)).length
    const alerting = rows.filter((x) => Number((x as any).alert_count ?? 0) > 0 && !x.revoked_at).length
    const critical = rows.filter((x) => (x as any).alert_severity === 'critical' && !x.revoked_at).length
    const warning = rows.filter((x) => (x as any).alert_severity === 'warning' && !x.revoked_at).length
    return {
      total,
      offline,
      revoked,
      online: Math.max(0, total - offline - revoked),
      alerting,
      critical,
      warning,
    }
  }, [rows])

  const alertTotals = React.useMemo(() => {
    const total = alertRows.length
    const critical = alertRows.filter((r) => (r.severity ?? '').toLowerCase() === 'critical' || (r.severity_num ?? 0) >= 2).length
    const warning = Math.max(0, total - critical)
    const devices = new Set(alertRows.map((r) => r.device_id)).size
    return { total, devices, critical, warning }
  }, [alertRows])

  const [alertFilter, setAlertFilter] = React.useState('')
  const filteredAlerts = React.useMemo(() => {
    const q = alertFilter.trim().toLowerCase()
    if (!q) return alertRows
    return alertRows.filter((r) => {
      return (
        (r.device_id ?? '').toLowerCase().includes(q) ||
        (r.label ?? '').toLowerCase().includes(q) ||
        (r.sensor ?? '').toLowerCase().includes(q) ||
        (r.alert_type ?? '').toLowerCase().includes(q) ||
        (r.severity ?? '').toLowerCase().includes(q)
      )
    })
  }, [alertRows, alertFilter])

  const [provisionMsg, setProvisionMsg] = React.useState<string | null>(null)
  const [actionMsg, setActionMsg] = React.useState<string | null>(null)
  const [newDeviceId, setNewDeviceId] = React.useState('')
  const [newLabel, setNewLabel] = React.useState('')
  const [newMetadata, setNewMetadata] = React.useState('')

  // Quick deploy wizard inputs (enroll-token path is fastest for field ops).
  const [deployDeviceId, setDeployDeviceId] = React.useState('')
  const [deployLabel, setDeployLabel] = React.useState('')
  const [deployEnrollToken, setDeployEnrollToken] = React.useState('')
  const [deploySensorMode, setDeploySensorMode] = React.useState('simulated')

  async function provisionDevice() {
    setProvisionMsg(null)
    setActionMsg(null)
    const device_id = newDeviceId.trim()
    if (!device_id) {
      setProvisionMsg('device_id is required')
      return
    }

    let metadata: Record<string, any> | undefined = undefined
    const raw = newMetadata.trim()
    if (raw) {
      try {
        metadata = JSON.parse(raw)
      } catch (e) {
        setProvisionMsg(`metadata must be valid JSON: ${(e as Error).message}`)
        return
      }
    }

    try {
      const res = await api.createDevice({ device_id, label: newLabel.trim() || undefined, metadata })
      setProvisionMsg(JSON.stringify(res, null, 2) + `\n\n# Copy/paste edge.env snippet:\n${edgeEnvSnippet(device_id, res.device_token)}`)
      setNewDeviceId('')
      setNewLabel('')
      setNewMetadata('')
      await registryQ.refetch()
      await devicesQ.refetch()
    } catch (e) {
      setProvisionMsg(`Provision failed: ${(e as Error).message}`)
    }
  }

  async function rotateToken(device_id: string) {
    setActionMsg(null)
    try {
      const res = await api.rotateDeviceToken(device_id)
      setActionMsg(JSON.stringify(res, null, 2) + `

# Update your device edge.env:
${edgeEnvSnippet(device_id, res.device_token)}`)
      await registryQ.refetch()
    } catch (e) {
      setActionMsg(`Rotate failed: ${(e as Error).message}`)
    }
  }

  async function revoke(device_id: string) {
    setActionMsg(null)
    try {
      const res = await api.revokeDevice(device_id)
      setActionMsg(
        JSON.stringify(res, null, 2) +
          `

# Device revoked
- The existing EDGE_DEVICE_TOKEN is now invalid.
- On the device, remove/clear EDGE_DEVICE_TOKEN (or replace it), then restart the edge-agent service.
- To re-enable this device, rotate a new token (or provision a new device id).`
      )
      await registryQ.refetch()
      await devicesQ.refetch()
    } catch (e) {
      setActionMsg(`Revoke failed: ${(e as Error).message}`)
    }
  }

  const cols: ColumnDef<DeviceStatusRow>[] = [
    {
      header: 'device',
      accessorKey: 'device_id',
      cell: (info) => {
        const row = info.row.original
        return (
          <div className="space-y-0.5">
            {row.label ? <div className="text-sm font-medium">{row.label}</div> : null}
            <Link
              to="/devices/$deviceId"
              params={{ deviceId: String(info.getValue() ?? '') }}
              className="font-mono text-xs hover:underline"
            >
              {String(info.getValue() ?? '—')}
            </Link>
          </div>
        )
      },
    },
    {
      header: 'status',
      accessorKey: 'is_offline',
      cell: (info) => statusBadge(info.row.original),
    },
    {
      header: 'alerts',
      accessorKey: 'alert_count',
      cell: (info) => {
        const row = info.row.original
        const count = Number(info.getValue() ?? 0)
        if (!count) return <Badge variant="outline">0</Badge>
        const sev = String((row as any).alert_severity ?? 'warning').toLowerCase()
        const variant = sev === 'critical' ? 'destructive' : 'warning'
        return (
          <Badge variant={variant}>
            {count} {sev}
          </Badge>
        )
      },
    },
    {
      header: 'last_seen',
      accessorKey: 'last_seen_at',
      cell: (info) => <span className="font-mono text-xs">{fmtTime(info.getValue() as any)}</span>,
    },
    {
      header: 'last_event',
      accessorKey: 'last_event_ts',
      cell: (info) => <span className="font-mono text-xs">{fmtTime(info.getValue() as any)}</span>,
    },
    {
      header: 'events',
      accessorKey: 'event_count',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '0')}</span>,
    },
    {
      header: 'last_ip',
      accessorKey: 'last_seen_ip',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '—')}</span>,
    },
  ]

  const alertCols: ColumnDef<DeviceAlertRow>[] = [
    {
      header: 'device',
      accessorKey: 'device_id',
      cell: (info) => {
        const row = info.row.original
        return (
          <div className="space-y-0.5">
            {row.label ? <div className="text-sm font-medium">{row.label}</div> : null}
            <Link
              to="/devices/$deviceId"
              params={{ deviceId: String(info.getValue() ?? '') }}
              className="font-mono text-xs hover:underline"
            >
              {String(info.getValue() ?? '—')}
            </Link>
          </div>
        )
      },
    },
    {
      header: 'severity',
      accessorKey: 'severity',
      cell: (info) => {
        const v = String(info.getValue() ?? 'warning').toLowerCase()
        const variant = v === 'critical' ? 'destructive' : 'warning'
        return <Badge variant={variant}>{v}</Badge>
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
      cell: (info) => {
        const row = info.row.original
        const v = Number(info.getValue() ?? 0)
        return (
          <span className="font-mono text-xs">
            {Number.isFinite(v) ? v.toFixed(2) : String(info.getValue() ?? '—')} {row.units ?? ''}
          </span>
        )
      },
    },
    {
      header: 'ts',
      accessorKey: 'ts',
      cell: (info) => <span className="font-mono text-xs">{fmtTime(info.getValue() as any)}</span>,
    },
    {
      header: 'type',
      accessorKey: 'alert_type',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '—')}</span>,
    },
  ]

  const registryCols: ColumnDef<DeviceInfo>[] = [
    {
      header: 'device',
      accessorKey: 'device_id',
      cell: (info) => (
        <Link
          to="/devices/$deviceId"
          params={{ deviceId: String(info.getValue() ?? '') }}
          className="font-mono text-xs hover:underline"
        >
          {String(info.getValue() ?? '—')}
        </Link>
      ),
    },
    {
      header: 'label',
      accessorKey: 'label',
      cell: (info) => <span className="text-xs">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'last_seen',
      accessorKey: 'last_seen_at',
      cell: (info) => <span className="font-mono text-xs">{fmtTime(info.getValue() as any)}</span>,
    },
    {
      header: 'revoked',
      accessorKey: 'revoked_at',
      cell: (info) => {
        const v = info.getValue() as any
        if (!v) return <Badge variant="secondary">active</Badge>
        return <Badge variant="destructive">revoked</Badge>
      },
    },
    {
      header: 'actions',
      id: 'actions',
      cell: (info) => {
        const d = info.row.original
        const disabled = Boolean(d.revoked_at)
        return (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => rotateToken(d.device_id)} disabled={disabled || !canUseInternal}>
              Rotate token
            </Button>
            <Button size="sm" variant="outline" onClick={() => revoke(d.device_id)} disabled={disabled || !canUseInternal}>
              Revoke
            </Button>
          </div>
        )
      },
    },
  ]

  const storage = r?.storage_backend
  const queue = r?.queue

  return (
    <Page
      title="Devices"
      description="EdgeWatch-style device health view powered by edge_telemetry marts."
      actions={
        <div className="flex items-center gap-2">
          {storage ? <Badge variant="outline">storage: {storage}</Badge> : null}
          {queue ? <Badge variant="outline">queue: {queue}</Badge> : null}
          <Link to="/datasets/$dataset" params={{ dataset: 'edge_telemetry' }} className="no-underline">
            <Button size="sm" variant="outline">Open dataset</Button>
          </Link>
          <Link to="/upload" className="no-underline">
            <Button size="sm" variant="outline">Ingest</Button>
          </Link>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total devices</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{totals.total}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Online</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{totals.online}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Offline</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{totals.offline}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Revoked</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-semibold tracking-tight">{totals.revoked}</div>
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Tabs
          items={[
            { value: 'status', label: 'Status' },
            { value: 'map', label: 'Map' },
            { value: 'alerts', label: 'Alerts' },
            { value: 'provisioning', label: 'Provisioning' },
          ] as any}
          value={tab}
          onValueChange={(v) => setTab(v as any)}
          className="mb-4"
        />

        {tab === 'status' ? (
          <Card>
            <CardHeader>
              <CardTitle>Device status</CardTitle>
              <CardDescription>
                Uses <span className="font-mono">marts_edge_telemetry_device_status</span> (offline heuristic prefers last_seen when available).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={totals.alerting ? 'warning' : 'success'}>alerting: {totals.alerting}</Badge>
                <Badge variant={totals.critical ? 'destructive' : 'outline'}>critical: {totals.critical}</Badge>
                <Badge variant={totals.warning ? 'warning' : 'outline'}>warning: {totals.warning}</Badge>
                <Badge variant="outline">offline threshold: {r?.edge_offline_threshold_seconds ?? 600}s</Badge>
              </div>

              {devicesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {devicesQ.isError ? (
                <div className="text-sm text-muted-foreground">
                  Device mart not available yet. Ingest edge telemetry first (seed from Dashboard or run the RPi agent).
                </div>
              ) : null}

              {rows.length ? (
                <DataTable
                  data={rows}
                  columns={cols}
                  height={560}
                  columnMinWidth={220}
                  onRowClick={(row) => nav({ to: '/devices/$deviceId', params: { deviceId: row.device_id } })}
                />
              ) : null}

              <Separator />

              <div className="text-xs text-muted-foreground">
                Tip: Tune the offline threshold via <span className="font-mono">EDGE_OFFLINE_THRESHOLD_SECONDS</span> (recommended) or by editing
                <span className="font-mono">marts_edge_telemetry_device_status</span> to match your sampling cadence.
                <br />
                Tip: Click a device id (or row) to open the device detail view for telemetry + day-2 ops commands.
              </div>
            </CardContent>
          </Card>
        ) : null}

        {tab === 'map' ? (
          <Card>
            <CardHeader>
              <CardTitle>Fleet map</CardTitle>
              <CardDescription>
                Uses <span className="font-mono">marts_edge_telemetry_device_geo_status</span> (device status + last known lat/lon).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">devices w/ location: {(geoQ.data ?? []).length}</Badge>
                <Badge variant="outline">note: no map tiles</Badge>
                <Badge variant="secondary">online</Badge>
                <Badge variant="destructive">offline/revoked</Badge>
                <Badge variant="warning">alerting</Badge>
              </div>

              {geoQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {geoQ.isError ? (
                <div className="text-sm text-muted-foreground">
                  Geo/status mart not available yet. Ingest edge telemetry with lat/lon first.
                </div>
              ) : null}

              {(geoQ.data ?? []).length ? <DeviceGeoScatter rows={geoQ.data ?? []} /> : null}

              <Separator />

              <div className="text-xs text-muted-foreground">
                Tip: provide <span className="font-mono">lat</span>/<span className="font-mono">lon</span> in telemetry to place devices on the map.
                If a device is moving (vehicle trailer/rig), sampling location on every heartbeat is usually enough.
              </div>
            </CardContent>
          </Card>
        ) : null}

        {tab === 'alerts' ? (
          <Card>
            <CardHeader>
              <CardTitle>Active alerts</CardTitle>
              <CardDescription>
                Derived from <span className="font-mono">marts_edge_telemetry_device_alerts</span> (latest per-sensor readings + default thresholds).
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={alertTotals.total ? 'warning' : 'success'}>alerts: {alertTotals.total}</Badge>
                <Badge variant="outline">devices impacted: {alertTotals.devices}</Badge>
                <Badge variant={alertTotals.critical ? 'destructive' : 'outline'}>critical: {alertTotals.critical}</Badge>
                <Badge variant={alertTotals.warning ? 'warning' : 'outline'}>warning: {alertTotals.warning}</Badge>
              </div>

              <div className="grid gap-2 md:grid-cols-2">
                <div>
                  <Label htmlFor="alertFilter">Filter</Label>
                  <Input
                    id="alertFilter"
                    placeholder="device_id, label, sensor, severity…"
                    value={alertFilter}
                    onChange={(e) => setAlertFilter(e.target.value)}
                  />
                </div>
              </div>

              {alertsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
              {alertsQ.isError ? (
                <div className="text-sm text-muted-foreground">
                  Alerts mart not available yet. Ingest edge telemetry first (seed from Dashboard or run the RPi agent).
                </div>
              ) : null}

              {filteredAlerts.length ? (
                <DataTable
                  data={filteredAlerts}
                  columns={alertCols}
                  height={560}
                  columnMinWidth={220}
                  onRowClick={(row) => nav({ to: '/devices/$deviceId', params: { deviceId: row.device_id } })}
                />
              ) : (
                <div className="text-sm text-muted-foreground">No active alerts.</div>
              )}

              <div className="text-xs text-muted-foreground">
                Thresholds are intentionally simple defaults. Tune in <span className="font-mono">eventpulse/loaders/postgres.py</span>
                (<span className="font-mono">marts_edge_telemetry_latest_readings</span>).
              </div>
            </CardContent>
          </Card>
        ) : null}

        {tab === 'provisioning' ? (
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>Quick deploy (Raspberry Pi)</CardTitle>
                <CardDescription>
                  Field ops installer + systemd unit. See <span className="font-mono">docs/FIELD_OPS.md</span>.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-sm text-muted-foreground">
                  Fastest path: enroll-token bootstrap (Pi runs the agent, swaps enroll token for a per-device token).
                </div>

                <div className="grid gap-3 md:grid-cols-2">
                  <div className="space-y-1">
                    <Label>device_id (optional)</Label>
                    <Input value={deployDeviceId} onChange={(e) => setDeployDeviceId(e.target.value)} placeholder="rpi-001" />
                  </div>
                  <div className="space-y-1">
                    <Label>label (optional)</Label>
                    <Input value={deployLabel} onChange={(e) => setDeployLabel(e.target.value)} placeholder="North gate" />
                  </div>
                  <div className="space-y-1 md:col-span-2">
                    <Label>EDGE_ENROLL_TOKEN</Label>
                    <Input
                      type="password"
                      value={deployEnrollToken}
                      onChange={(e) => setDeployEnrollToken(e.target.value)}
                      placeholder="paste bootstrap enroll token"
                    />
                    <div className="text-xs text-muted-foreground">
                      Keep this secret. After the device enrolls successfully, you can remove it from
                      <span className="font-mono">/etc/eventpulse-edge/edge.env</span>.
                    </div>
                  </div>
                  <div className="space-y-1 md:col-span-2">
                    <Label>sensor mode</Label>
                    <Input value={deploySensorMode} onChange={(e) => setDeploySensorMode(e.target.value)} list="sensor-modes" />
                    <datalist id="sensor-modes">
                      <option value="simulated" />
                      <option value="stdin" />
                      <option value="script" />
                    </datalist>
                  </div>
                </div>

                {(() => {
                  const base = apiBaseUrl || 'https://YOUR_CLOUD_RUN_URL'
                  const did = deployDeviceId.trim()
                  const lbl = deployLabel.trim()
                  const enroll = deployEnrollToken.trim() || 'PASTE_EDGE_ENROLL_TOKEN'
                  const smode = deploySensorMode.trim() || 'simulated'
                  const cmd = [
                    'sudo bash field_ops/rpi/install.sh \\',
                    `  --api-base-url "${base}" \\`,
                    did ? `  --device-id "${did}" \\` : null,
                    lbl ? `  --device-label "${lbl}" \\` : null,
                    `  --enroll-token "${enroll}" \\`,
                    `  --sensor-mode "${smode}"`,
                  ]
                    .filter(Boolean)
                    .join('\n')

                  return (
                    <div className="space-y-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant="outline">Pi OS 64-bit recommended</Badge>
                        <CopyButton text={cmd} label="Copy install command" />
                      </div>
                      <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto">{cmd}</pre>
                    </div>
                  )
                })()}

                <div className="text-xs text-muted-foreground">
                  If you disable enrollment, provision devices via internal admin instead.
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Device registry (internal)</CardTitle>
                <CardDescription>
                  Create devices, rotate tokens, and revoke compromised hardware. Requires internal auth.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {needsToken ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline">task auth: token</Badge>
                    {hasToken ? <Badge variant="success">internal unlocked</Badge> : <Badge variant="destructive">internal locked</Badge>}
                    {!hasToken ? (
                      <Link to="/meta" className="no-underline">
                        <Button size="sm" variant="outline">Open Ops (set task token)</Button>
                      </Link>
                    ) : null}
                  </div>
                ) : (
                  <Badge variant="outline">task auth: {r?.task_auth_mode ?? '—'}</Badge>
                )}

                <Separator />

                <div className="space-y-2">
                  <div className="text-sm font-medium">Provision a device</div>
                  <div className="grid gap-3">
                    <div className="grid gap-1">
                      <Label htmlFor="device_id">device_id</Label>
                      <Input id="device_id" value={newDeviceId} onChange={(e) => setNewDeviceId(e.target.value)} placeholder="rpi-001" />
                    </div>
                    <div className="grid gap-1">
                      <Label htmlFor="label">label (optional)</Label>
                      <Input id="label" value={newLabel} onChange={(e) => setNewLabel(e.target.value)} placeholder="North gate" />
                    </div>
                    <div className="grid gap-1">
                      <Label htmlFor="metadata">metadata JSON (optional)</Label>
                      <Textarea
                        id="metadata"
                        value={newMetadata}
                        onChange={(e) => setNewMetadata(e.target.value)}
                        placeholder='{"site":"denver","sensor":"temp"}'
                        rows={3}
                      />
                    </div>
                    <Button onClick={provisionDevice} disabled={!canUseInternal}>Provision device</Button>
                  </div>

                  {provisionMsg ? (
                    <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto whitespace-pre-wrap">{provisionMsg}</pre>
                  ) : null}
                </div>

                <Separator />

                {actionMsg ? (
                  <pre className="text-xs rounded-md border bg-muted/20 p-3 overflow-auto whitespace-pre-wrap">{actionMsg}</pre>
                ) : null}

                {registryQ.isError ? (
                  <div className="text-sm text-muted-foreground">
                    Registry not available (or internal auth is not configured). Error: {(registryQ.error as Error).message}
                  </div>
                ) : null}

                {registryDevices.length ? (
                  <DataTable
                    data={registryDevices}
                    columns={registryCols}
                    height={360}
                    columnMinWidth={220}
                    onRowClick={(row) => nav({ to: '/devices/$deviceId', params: { deviceId: row.device_id } })}
                  />
                ) : (
                  <div className="text-sm text-muted-foreground">
                    {registryQ.isLoading ? 'Loading registry…' : 'No devices provisioned yet.'}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        ) : null}
      </div>
    </Page>
  )
}

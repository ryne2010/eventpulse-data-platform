import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api, getIngestTokenForUi, getTaskTokenForUi, setIngestToken, setTaskToken, type GcsSignedUrlResponse } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Label, Page, Separator } from '../portfolio-ui'

async function sha256Hex(file: File): Promise<string> {
  const buf = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buf)
  const bytes = Array.from(new Uint8Array(digest))
  return bytes.map((b) => b.toString(16).padStart(2, '0')).join('')
}

export function UploadPage() {
  const metaQ = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const dsQ = useQuery({ queryKey: ['datasets', 200], queryFn: () => api.listDatasets(200) })

  const [dataset, setDatasetState] = React.useState('parcels')
  const [file, setFile] = React.useState<File | null>(null)

  const [taskToken, setTaskTokenState] = React.useState(getTaskTokenForUi())
  const [ingestToken, setIngestTokenState] = React.useState(getIngestTokenForUi())

  React.useEffect(() => {
    setTaskTokenState(getTaskTokenForUi())
    setIngestTokenState(getIngestTokenForUi())
  }, [])

  function updateToken(v: string) {
    setTaskTokenState(v)
    setTaskToken(v)
  }

  function updateIngestToken(v: string) {
    setIngestTokenState(v)
    setIngestToken(v)
  }

  const runtime = metaQ.data?.runtime
  const signedUrlsEnabled = Boolean(runtime?.enable_signed_urls)
  const storageBackend = runtime?.storage_backend
  const requireSha = Boolean(runtime?.require_signed_url_sha256)
  const taskAuthMode = runtime?.task_auth_mode ?? 'token'
  const ingestAuthMode = runtime?.ingest_auth_mode ?? 'none'
  const incomingDir = runtime?.incoming_dir
  const needsToken = taskAuthMode === 'token'
  const hasToken = Boolean(taskToken.trim())

  const ingestNeedsToken = ingestAuthMode === 'token'
  const hasIngestToken = Boolean(ingestToken.trim())

  const canUseInternal = !needsToken || hasToken
  const canDirectUpload = !ingestNeedsToken || hasIngestToken

  // Direct upload state
  const [directBusy, setDirectBusy] = React.useState(false)
  const [directResult, setDirectResult] = React.useState<string | null>(null)
  const [directIngestionId, setDirectIngestionId] = React.useState<string | null>(null)

  async function directUpload() {
    if (!file) return
    setDirectBusy(true)
    setDirectResult(null)
    setDirectIngestionId(null)
    try {
      const res = await api.uploadDirect(dataset, file, 'ui')
      setDirectResult(`Uploaded and enqueued. job=${res.job_backend}:${res.job_id}`)
      setDirectIngestionId(res.ingestion_id)
    } catch (e) {
      setDirectResult(`Upload failed: ${(e as Error).message}`)
    } finally {
      setDirectBusy(false)
    }
  }

  // Signed URL upload state
  const [signedBusy, setSignedBusy] = React.useState(false)
  const [signedMsg, setSignedMsg] = React.useState<string | null>(null)
  const [signedIngestionId, setSignedIngestionId] = React.useState<string | null>(null)
  const [signedGcsUri, setSignedGcsUri] = React.useState<string | null>(null)

  async function signedUpload() {
    if (!file) return
    setSignedBusy(true)
    setSignedMsg(null)
    setSignedIngestionId(null)
    setSignedGcsUri(null)

    try {
      const sha = requireSha ? await sha256Hex(file) : undefined
      setSignedMsg(requireSha ? 'Computed SHA-256. Minting signed URL…' : 'Minting signed URL…')

      const signed: GcsSignedUrlResponse = await api.gcsSignedUrl({
        dataset,
        filename: file.name,
        sha256: sha,
        source: 'ui',
      })

      setSignedGcsUri(signed.gcs_uri)
      setSignedMsg('Uploading to GCS…')

      const putRes = await fetch(signed.upload_url, {
        method: 'PUT',
        headers: signed.required_headers,
        body: file,
      })

      if (!putRes.ok) {
        const t = await putRes.text()
        throw new Error(t || `GCS PUT failed: ${putRes.status}`)
      }

      setSignedMsg('Uploaded to GCS. Registering ingestion…')

      // This call is safe even if GCS event ingestion is enabled: it de-dupes on generation.
      const reg = await api.ingestFromGcs(dataset, signed.gcs_uri, 'ui')
      const id = reg?.ingestion_id ?? reg?.id ?? null
      setSignedIngestionId(id)
      setSignedMsg('Registered ingestion and enqueued processing.')

    } catch (e) {
      setSignedMsg(`Signed upload failed: ${(e as Error).message}`)
    } finally {
      setSignedBusy(false)
    }
  }

  // Register an existing GCS object (backfill)
  const [gcsUri, setGcsUri] = React.useState('')
  const [gcsBusy, setGcsBusy] = React.useState(false)
  const [gcsMsg, setGcsMsg] = React.useState<string | null>(null)
  const [gcsIngestionId, setGcsIngestionId] = React.useState<string | null>(null)

  async function registerExistingGcs() {
    if (!gcsUri.trim()) return
    setGcsBusy(true)
    setGcsMsg(null)
    setGcsIngestionId(null)
    try {
      const reg = await api.ingestFromGcs(dataset, gcsUri.trim(), 'ui')
      const id = reg?.ingestion_id ?? reg?.id ?? null
      setGcsIngestionId(id)
      setGcsMsg('Registered ingestion and enqueued processing.')
    } catch (e) {
      setGcsMsg(`Register failed: ${(e as Error).message}`)
    } finally {
      setGcsBusy(false)
    }
  }

  // Ingest from local INCOMING_DIR path (backfill)
  const [pathRel, setPathRel] = React.useState('')
  const [pathBusy, setPathBusy] = React.useState(false)
  const [pathMsg, setPathMsg] = React.useState<string | null>(null)
  const [pathIngestionId, setPathIngestionId] = React.useState<string | null>(null)

  const ingestFromPathEnabled = Boolean(runtime?.enable_ingest_from_path) && canUseInternal
  const incomingEnabled = Boolean(runtime?.enable_incoming_list) && ingestFromPathEnabled
  const incomingQ = useQuery({
    queryKey: ['incoming_list', incomingEnabled],
    queryFn: () => api.incomingList(200),
    enabled: incomingEnabled,
    retry: false,
  })

  async function ingestFromPath() {
    if (!ingestFromPathEnabled) return
    if (!pathRel.trim()) return
    setPathBusy(true)
    setPathMsg(null)
    setPathIngestionId(null)
    try {
      const res = await api.ingestFromPath(dataset, pathRel.trim(), 'ui')
      setPathMsg(`Registered and enqueued from path.`)
      setPathIngestionId(res.ingestion_id)
    } catch (e) {
      setPathMsg(`Ingest from path failed: ${(e as Error).message}`)
    } finally {
      setPathBusy(false)
    }
  }


  return (
    <Page
      title="Upload"
      description="Ingest a file into the event-driven pipeline. For production-scale uploads, use GCS signed URLs."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/ingestions" className="no-underline">
            <Button size="sm" variant="outline">Ingestions</Button>
          </Link>
          <Link to="/datasets" className="no-underline">
            <Button size="sm" variant="outline">Datasets</Button>
          </Link>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle>Settings</CardTitle>
            <CardDescription>Auth + ingestion settings for this browser session.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label>Task auth mode</Label>
              <div className="text-sm text-muted-foreground">{taskAuthMode}</div>
            </div>

            <div className="space-y-1">
              <Label>Task token</Label>
              <Input
                value={taskToken}
                onChange={(e) => updateToken(e.target.value)}
                placeholder={needsToken ? 'Required for internal endpoints' : 'Optional'}
              />
              <div className="text-xs text-muted-foreground">
                Stored in <span className="font-mono">localStorage</span> as <span className="font-mono">eventpulse.taskToken</span>.
              </div>
              {needsToken && !hasToken ? (
                <div className="text-xs text-amber-600">
                  Token mode enabled — signed uploads and GCS ingestion will be disabled until a token is set.
                </div>
              ) : null}
            </div>

            <Separator />

            <div className="space-y-1">
              <Label>Ingest auth mode</Label>
              <div className="text-sm text-muted-foreground">{ingestAuthMode}</div>
              <div className="text-xs text-muted-foreground">
                Applies to <span className="font-mono">/api/ingest/upload</span> (direct uploads).
              </div>
            </div>

            <div className="space-y-1">
              <Label>Ingest token</Label>
              <Input
                value={ingestToken}
                onChange={(e) => updateIngestToken(e.target.value)}
                placeholder={ingestNeedsToken ? 'Required for direct uploads' : 'Optional'}
              />
              <div className="text-xs text-muted-foreground">
                Stored in <span className="font-mono">localStorage</span> as <span className="font-mono">eventpulse.ingestToken</span>.
              </div>
              {ingestNeedsToken && !hasIngestToken ? (
                <div className="text-xs text-amber-600">
                  Token mode enabled — direct uploads will be disabled until an ingest token is set.
                </div>
              ) : null}
            </div>

            <Separator />

            <div className="space-y-1">
              <Label>Dataset</Label>
              <Input list="datasets" value={dataset} onChange={(e) => setDatasetState(e.target.value)} />
              <datalist id="datasets">
                {(dsQ.data?.items ?? []).map((d) => (
                  <option key={d.dataset} value={d.dataset} />
                ))}
              </datalist>
              <div className="text-xs text-muted-foreground">Pick a contract-backed dataset.</div>
            </div>

            <div className="space-y-1">
              <Label>File</Label>
              <Input
                type="file"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <div className="text-xs text-muted-foreground">
                Supported: CSV / Excel. Large files should use signed URLs.
              </div>
            </div>

            {file ? (
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="outline">name: {file.name}</Badge>
                <Badge variant="outline">size: {Math.round(file.size / 1024)} KB</Badge>
              </div>
            ) : null}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Direct upload (simple)</CardTitle>
            <CardDescription>Uploads through the API service directly. Best for local dev and small files.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={directUpload} disabled={!file || directBusy || !canDirectUpload}>
                {directBusy ? 'Uploading…' : 'Upload & ingest'}
              </Button>
              {ingestNeedsToken && !hasIngestToken ? (
                <span className="text-xs text-amber-600">Set an ingest token to enable direct upload.</span>
              ) : null}
              {directIngestionId ? (
                <Link to="/ingestions/$id" params={{ id: directIngestionId }} className="no-underline">
                  <Button variant="outline">Open ingestion</Button>
                </Link>
              ) : null}
              <Badge variant="outline">storage: {storageBackend ?? '—'}</Badge>
            </div>
            {directResult ? <div className="text-sm text-muted-foreground">{directResult}</div> : null}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Signed URL upload (production-friendly)</CardTitle>
            <CardDescription>
              Uploads directly to GCS using a signed URL, then registers the ingestion.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              {storageBackend === 'gcs' ? (
                <Badge variant={signedUrlsEnabled ? 'success' : 'warning'}>
                  signed URLs: {signedUrlsEnabled ? 'enabled' : 'disabled'}
                </Badge>
              ) : (
                <Badge variant="outline">storage: {storageBackend ?? '—'} (needs gcs)</Badge>
              )}
              <Badge variant="outline">sha256 required: {requireSha ? 'yes' : 'no'}</Badge>
              <Badge variant="outline">internal auth: {needsToken ? 'token' : 'iam'}</Badge>
            </div>

            {!signedUrlsEnabled ? (
              <div className="text-sm text-muted-foreground">
                Signed URL upload is disabled. To enable, set <span className="font-mono">ENABLE_SIGNED_URLS=true</span> and run the service as a <strong>private</strong> Cloud Run service.
              </div>
            ) : null}

            {signedUrlsEnabled && !canUseInternal ? (
              <div className="text-sm text-amber-600">
                Internal endpoints require a task token. Set it in the Settings panel to use this flow.
              </div>
            ) : null}

            <Button
              onClick={signedUpload}
              disabled={!file || signedBusy || !signedUrlsEnabled || storageBackend !== 'gcs' || !canUseInternal}
            >
              {signedBusy ? 'Uploading…' : 'Upload to GCS & register'}
            </Button>

            {signedGcsUri ? (
              <div className="text-xs text-muted-foreground">
                GCS URI: <span className="font-mono">{signedGcsUri}</span>
              </div>
            ) : null}

            {signedIngestionId ? (
              <div className="flex items-center gap-2">
                <Link to="/ingestions/$id" params={{ id: signedIngestionId }} className="no-underline">
                  <Button variant="outline">Open ingestion</Button>
                </Link>
                <Link to="/datasets/$dataset" params={{ dataset }} className="text-sm text-muted-foreground hover:text-foreground">
                  View dataset →
                </Link>
              </div>
            ) : null}

            {signedMsg ? <div className="text-sm text-muted-foreground">{signedMsg}</div> : null}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Register existing GCS object (backfill)</CardTitle>
            <CardDescription>
              If a file already exists in your raw bucket, register it for processing without re-uploading.
              This requires internal auth.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!canUseInternal ? (
              <div className="text-sm text-amber-600">
                Set a task token in the Settings panel to enable internal ingestion endpoints.
              </div>
            ) : null}

            <div className="space-y-1">
              <Label>GCS URI</Label>
              <Input value={gcsUri} onChange={(e) => setGcsUri(e.target.value)} placeholder="gs://bucket/path/to/file.xlsx" />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={registerExistingGcs} disabled={!canUseInternal || gcsBusy || !gcsUri.trim()}>
                {gcsBusy ? 'Registering…' : 'Register & ingest'}
              </Button>
              {gcsIngestionId ? (
                <Link to="/ingestions/$id" params={{ id: gcsIngestionId }} className="no-underline">
                  <Button variant="outline">Open ingestion</Button>
                </Link>
              ) : null}
              {gcsMsg ? <Badge variant="outline">{gcsMsg}</Badge> : null}
            </div>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Ingest from INCOMING_DIR path (local backfill)</CardTitle>
            <CardDescription>
              For local dev, you can mount <span className="font-mono">{incomingDir ?? '/data/incoming'}</span> and ingest by relative path.
              Listing is optional and gated.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {!ingestFromPathEnabled ? (
              <div className="text-sm text-amber-600">
                This feature is disabled. Enable <span className="font-mono">ENABLE_INGEST_FROM_PATH=true</span> and set a task token (if required)
                to use it.
              </div>
            ) : null}

            <div className="space-y-1">
              <Label>Relative path</Label>
              <Input value={pathRel} onChange={(e) => setPathRel(e.target.value)} placeholder="parcels.xlsx" />
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={ingestFromPath} disabled={!ingestFromPathEnabled || pathBusy || !pathRel.trim()}>
                {pathBusy ? 'Enqueuing…' : 'Ingest from path'}
              </Button>
              {pathIngestionId ? (
                <Link to="/ingestions/$id" params={{ id: pathIngestionId }} className="no-underline">
                  <Button variant="outline">Open ingestion</Button>
                </Link>
              ) : null}
              {pathMsg ? <Badge variant="outline">{pathMsg}</Badge> : null}
            </div>

            {incomingEnabled ? (
              <div className="space-y-2">
                <Separator />
                <div className="flex items-center justify-between gap-2">
                  <div className="text-sm font-medium">Incoming files</div>
                  <Button size="sm" variant="outline" onClick={() => incomingQ.refetch()} disabled={incomingQ.isFetching}>
                    {incomingQ.isFetching ? 'Refreshing…' : 'Refresh'}
                  </Button>
                </div>
                {incomingQ.error ? (
                  <div className="text-sm text-muted-foreground">Could not list incoming files (check auth / ENABLE_INCOMING_LIST).</div>
                ) : null}
                <div className="max-h-44 overflow-auto rounded border border-border p-2 text-xs">
                  {(incomingQ.data?.items ?? []).length === 0 ? (
                    <div className="text-muted-foreground">No files found.</div>
                  ) : (
                    <div className="space-y-1">
                      {(incomingQ.data?.items ?? []).map((f) => (
                        <button
                          key={f.relative_path}
                          className="flex w-full items-center justify-between rounded px-1 py-1 text-left hover:bg-muted"
                          onClick={() => setPathRel(f.relative_path)}
                        >
                          <span className="font-mono">{f.relative_path}</span>
                          <span className="text-muted-foreground">{Math.round(f.size_bytes / 1024)} KB</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                <div className="text-xs text-muted-foreground">Click a file to populate the path.</div>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">
                To enable listing, set <span className="font-mono">ENABLE_INCOMING_LIST=true</span> and configure internal auth.
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}

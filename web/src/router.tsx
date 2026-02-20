import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { AppShell, PortfolioDevtools } from './portfolio-ui'
import { DashboardPage } from './pages/Dashboard'
import { IngestionsPage } from './pages/Ingestions'
import { IngestionDetailPage } from './pages/IngestionDetail'
import { DatasetsPage } from './pages/Datasets'
import DatasetPage from './pages/Dataset'
import { UploadPage } from './pages/Upload'
import { MetaPage } from './pages/Meta'
import { ProductsPage } from './pages/Products'
import { DevicesPage } from './pages/Devices'
import { DeviceDetailPage } from './pages/DeviceDetail'
import { MediaPage } from './pages/Media'
import { TrendsPage } from './pages/Trends'
import { AuditPage } from './pages/Audit'

const rootRoute = createRootRoute({
  component: () => (
    <AppShell
      appName="EventPulse Data Platform"
      appBadge="Event-driven • Cloud Run"
      nav={[
        { to: '/', label: 'Dashboard' },
        { to: '/ingestions', label: 'Ingestions' },
        { to: '/datasets', label: 'Datasets' },
        { to: '/products', label: 'Products' },
        { to: '/devices', label: 'Devices' },
        { to: '/media', label: 'Media' },
        { to: '/trends', label: 'Trends' },
        { to: '/audit', label: 'Audit' },
        { to: '/upload', label: 'Ingest' },
        { to: '/meta', label: 'Ops' },
      ]}
      docsHref="/docs"
    >
      <Outlet />
      <PortfolioDevtools />
    </AppShell>
  ),
})

const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: DashboardPage,
})

const ingestionsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ingestions',
  component: IngestionsPage,
})

const ingestionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ingestions/$id',
  component: IngestionDetailPage,
})

const datasetsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/datasets',
  component: DatasetsPage,
})

const datasetRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/datasets/$dataset',
  component: DatasetPage,
})

const productsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/products',
  component: ProductsPage,
})

const devicesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/devices',
  component: DevicesPage,
})

const deviceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/devices/$deviceId',
  component: DeviceDetailPage,
})

const mediaRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/media',
  component: MediaPage,
})

const trendsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/trends',
  component: TrendsPage,
})

const auditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/audit',
  component: AuditPage,
})

const uploadRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/upload',
  component: UploadPage,
})

const metaRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/meta',
  component: MetaPage,
})

export const routeTree = rootRoute.addChildren([
  dashboardRoute,
  ingestionsRoute,
  ingestionRoute,
  datasetsRoute,
  datasetRoute,
  productsRoute,
  devicesRoute,
  deviceRoute,
  mediaRoute,
  trendsRoute,
  auditRoute,
  uploadRoute,
  metaRoute,
])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

import { createRootRoute, createRoute, createRouter, Outlet } from '@tanstack/react-router'
import { AppShell, PortfolioDevtools } from './portfolio-ui'
import { IngestionsPage } from './pages/Ingestions'
import { IngestionDetailPage } from './pages/IngestionDetail'
import { DatasetPage } from './pages/Dataset'
import { MetaPage } from './pages/Meta'

const rootRoute = createRootRoute({
  component: () => (
    <AppShell
      appName="EventPulse Data Platform"
      appBadge="Warehouse-ready"
      nav={[
        { to: '/', label: 'Ingestions' },
        { to: '/datasets/parcels', label: 'Curated Sample' },
        { to: '/meta', label: 'Meta' },
      ]}
      docsHref="/docs"
    >
      <Outlet />
      <PortfolioDevtools />
    </AppShell>
  ),
})

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  component: IngestionsPage,
})

const ingestionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/ingestions/$id',
  component: IngestionDetailPage,
})

const datasetRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/datasets/$dataset',
  component: DatasetPage,
})

const metaRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/meta',
  component: MetaPage,
})

export const routeTree = rootRoute.addChildren([indexRoute, ingestionRoute, datasetRoute, metaRoute])

export const router = createRouter({ routeTree })

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

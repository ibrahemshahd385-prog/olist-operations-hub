// Chooses which screen to show from the URL (#/orders, #/orders/new, ...).
import Layout from './components/Layout'
import { match, useHashPath } from './lib/router'
import AnalyticsPage from './pages/AnalyticsPage'
import InvoicePage from './pages/InvoicePage'
import LogisticsPage from './pages/LogisticsPage'
import NewOrderPage from './pages/NewOrderPage'
import OrderDetailPage from './pages/OrderDetailPage'
import OrdersPage from './pages/OrdersPage'
import SellerDetailPage from './pages/SellerDetailPage'
import SellersPage from './pages/SellersPage'

export default function App() {
  const path = useHashPath()
  let page = <OrdersPage />
  let params
  let active = 'orders'

  if (match('/orders/new', path)) page = <NewOrderPage />
  else if ((params = match('/orders/:id', path))) page = <OrderDetailPage key={params.id} orderId={params.id} />
  else if ((params = match('/invoices/:id', path))) page = <InvoicePage key={params.id} invoiceId={params.id} />
  else if (match('/logistics', path)) { page = <LogisticsPage />; active = 'logistics' }
  else if (match('/sellers', path)) { page = <SellersPage />; active = 'sellers' }
  else if ((params = match('/sellers/:id', path))) { page = <SellerDetailPage key={params.id} sellerId={params.id} />; active = 'sellers' }
  else if (match('/analytics', path)) { page = <AnalyticsPage />; active = 'analytics' }

  return <Layout active={active}>{page}</Layout>
}

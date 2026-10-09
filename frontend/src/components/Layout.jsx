// App shell: the module navigation on the left, the current screen on the right.
// Modules 2-4 are listed so the full system map is visible from day one.

const MODULES = [
  { key: 'orders', label: 'Orders & invoices', href: '#/orders', ready: true },
  { key: 'logistics', label: 'Smart logistics', href: '#/logistics', ready: true },
  { key: 'sellers', label: 'Seller performance', href: '#/sellers', ready: true },
  { key: 'analytics', label: 'Analytics & AI', href: '#/analytics', ready: true },
]

export default function Layout({ active, children }) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#/orders">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="28" height="28">
              <rect width="32" height="32" rx="7" fill="var(--blue)" />
              <path d="M8 20h16M8 12h10" stroke="var(--signal)" strokeWidth="3.2" strokeLinecap="round" />
              <circle cx="23" cy="12" r="2.6" fill="#fff" />
            </svg>
          </span>
          <span className="brand-text">
            <strong>Olist Ops</strong>
            <small>Operations hub</small>
          </span>
        </a>
        <nav aria-label="Modules">
          {MODULES.map((m) =>
            m.ready ? (
              <a key={m.key} href={m.href} className={'nav-item' + (active === m.key ? ' is-active' : '')}
                 aria-current={active === m.key ? 'page' : undefined}>
                {m.label}
              </a>
            ) : (
              <span key={m.key} className="nav-item is-locked" aria-disabled="true">
                {m.label}
                <em>{m.note}</em>
              </span>
            ),
          )}
        </nav>
        <p className="sidebar-foot">Built on the public Olist dataset, 2016–2018. Prototype by HVIA.</p>
      </aside>
      <main className="main">{children}</main>
    </div>
  )
}

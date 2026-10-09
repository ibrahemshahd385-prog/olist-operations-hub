// DANFE: the printed summary of an NF-e. It travels with the package and is
// what the carrier and the customer actually see. Labels stay in Portuguese,
// as on the real document. The barcode encodes the 44-digit access key.
import { api } from '../lib/api'
import { accessKeyBlocks, dateTime, shortId } from '../lib/format'
import { useAsync } from '../lib/useAsync'
import Barcode128 from '../components/Barcode128'
import { ErrorNotice, Loading } from '../components/ui'

const cnpj = (c) => (c ? `${c.slice(0, 2)}.${c.slice(2, 5)}.${c.slice(5, 8)}/${c.slice(8, 12)}-${c.slice(12)}` : '')
const nfNumber = (n) => String(n).padStart(9, '0').replace(/(\d{3})(\d{3})(\d{3})/, '$1.$2.$3')
const brNumber = (v) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v)

export default function InvoicePage({ invoiceId }) {
  const { data: inv, error, loading } = useAsync(() => api.invoice(invoiceId), [invoiceId])
  if (error) return <div className="page"><ErrorNotice error={error} /></div>
  if (!inv) return <div className="page">{loading && <Loading />}</div>

  return (
    <div className="page">
      <header className="page-head no-print">
        <div>
          <a className="back" href={`#/orders/${inv.order_id}`}>Order {shortId(inv.order_id)}</a>
          <h1>NF-e nº {inv.number}</h1>
          <p className="lede">
            The DANFE is the printed summary of an electronic invoice and must travel with the package.
            This one is simulated: it follows the real layout and access-key rules but was never sent to SEFAZ.
          </p>
        </div>
        <button className="btn btn-secondary" onClick={() => window.print()}>Print DANFE</button>
      </header>

      <article className={`danfe ${inv.status === 'canceled' ? 'is-canceled' : ''}`}>
        <div className="danfe-watermark" aria-hidden="true">
          {inv.status === 'canceled' ? 'NF-e CANCELADA' : 'SEM VALOR FISCAL'}
        </div>

        <div className="danfe-row danfe-top">
          <div className="box issuer">
            <span className="lbl">Emitente</span>
            <strong>Vendedor {shortId(inv.issuer.seller_id)}</strong>
            <span className="cap">{inv.issuer.city} / {inv.issuer.state}</span>
            <span>CEP {inv.issuer.zip_code_prefix}-000</span>
            <span>CNPJ {cnpj(inv.issuer.cnpj)}</span>
          </div>
          <div className="box title">
            <strong className="danfe-name">DANFE</strong>
            <span>Documento Auxiliar da Nota Fiscal Eletrônica</span>
            <span className="io">1 - Saída</span>
            <strong>Nº {nfNumber(inv.number)}</strong>
            <span>Série {String(inv.series).padStart(3, '0')}</span>
          </div>
          <div className="box keybox">
            <Barcode128 value={inv.access_key} />
            <span className="lbl">Chave de acesso</span>
            <strong className="access-key">{accessKeyBlocks(inv.access_key)}</strong>
            <span className="small">
              Consulta de autenticidade no portal nacional da NF-e, www.nfe.fazenda.gov.br/portal.
              {inv.access_key_valid ? ' Dígito verificador conferido (módulo 11).' : ' Dígito verificador inválido.'}
            </span>
          </div>
        </div>

        <div className="danfe-row">
          <div className="box grow"><span className="lbl">Natureza da operação</span>Venda de mercadoria{inv.interstate ? ' (interestadual)' : ''}</div>
          <div className="box"><span className="lbl">Protocolo de autorização</span>Simulação, sem protocolo SEFAZ</div>
        </div>

        <h3 className="danfe-section">Destinatário / remetente</h3>
        <div className="danfe-row">
          <div className="box grow"><span className="lbl">Cliente</span>{inv.recipient.customer_unique_id}</div>
          <div className="box"><span className="lbl">Município / UF</span><span className="cap">{inv.recipient.city}</span> / {inv.recipient.state}</div>
          <div className="box"><span className="lbl">CEP</span>{inv.recipient.zip_code_prefix}-000</div>
          <div className="box"><span className="lbl">Data de emissão</span>{dateTime(inv.issued_at)}</div>
        </div>

        <h3 className="danfe-section">Cálculo do total</h3>
        <div className="danfe-row">
          <div className="box grow"><span className="lbl">Valor total dos produtos</span>R$ {brNumber(inv.products_total)}</div>
          <div className="box grow"><span className="lbl">Valor do frete</span>R$ {brNumber(inv.freight_total)}</div>
          <div className="box grow strong"><span className="lbl">Valor total da nota</span>R$ {brNumber(inv.total)}</div>
        </div>

        <h3 className="danfe-section">Transportador / volumes</h3>
        <div className="danfe-row">
          <div className="box grow"><span className="lbl">Transportadora</span>Parceiro logístico Olist</div>
          <div className="box"><span className="lbl">Frete por conta</span>0 - Emitente</div>
          <div className="box"><span className="lbl">Quantidade</span>{inv.items_count}</div>
        </div>

        <h3 className="danfe-section">Dados dos produtos</h3>
        <table className="danfe-table">
          <thead>
            <tr><th>Código</th><th>Descrição</th><th className="num">Qtd</th><th className="num">Valor unit.</th>
              <th className="num">Frete</th><th className="num">Valor total</th></tr>
          </thead>
          <tbody>
            {inv.items.map((it) => (
              <tr key={it.product_id + it.unit_price}>
                <td>{shortId(it.product_id)}</td>
                <td className="cap">{it.category.replaceAll('_', ' ')}</td>
                <td className="num">{it.quantity}</td>
                <td className="num">{brNumber(it.unit_price)}</td>
                <td className="num">{brNumber(it.freight)}</td>
                <td className="num">{brNumber(it.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h3 className="danfe-section">Dados adicionais</h3>
        <div className="box">
          Documento emitido em ambiente de simulação, sem valor fiscal. Pedido Olist {inv.order_id}.
          {inv.status === 'canceled' && ` NF-e cancelada em ${dateTime(inv.canceled_at)}.`}
        </div>
      </article>

    </div>
  )
}

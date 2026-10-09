// Code 128 (set C) barcode as SVG — the same symbology printed on every DANFE,
// so the 44-digit access key on our invoice can actually be scanned.
//
// How it works: set C packs two digits into one symbol ("35" -> value 35).
// Barcode = start C + symbols + checksum + stop. Each symbol is 6 alternating
// bar/space widths (in modules); the stop symbol has 7.

const PATTERNS = (
  '212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 221312 231212 112232 122132 ' +
  '122231 113222 123122 123221 223211 221132 221231 213212 223112 312131 311222 321122 321221 312212 ' +
  '322112 322211 212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 231113 231311 ' +
  '112133 112331 132131 113123 113321 133121 313121 211331 231131 213113 213311 213131 311123 311321 ' +
  '331121 312113 312311 332111 314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 ' +
  '112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 111242 121142 121241 114212 ' +
  '124112 124211 411212 421112 421211 212141 214121 412121 111143 111341 131141 114113 114311 411113 ' +
  '411311 113141 114131 311141 411131 211412 211214 211232 2331112'
).split(' ')

const START_C = 105
const STOP = 106

export function code128cValues(digits) {
  if (!/^\d+$/.test(digits) || digits.length % 2) throw new Error('Set C needs an even number of digits')
  const values = [START_C]
  for (let i = 0; i < digits.length; i += 2) values.push(Number(digits.slice(i, i + 2)))
  // checksum: start value + each symbol value x its position, modulo 103
  const sum = values.reduce((acc, v, i) => acc + v * (i === 0 ? 1 : i), 0)
  values.push(sum % 103, STOP)
  return values
}

export default function Barcode128({ value, height = 52, module = 1.6 }) {
  const widths = code128cValues(value).flatMap((v) => PATTERNS[v].split('').map(Number))
  const quiet = 10 // blank margin required on both sides for scanners
  const bars = []
  let x = quiet
  widths.forEach((w, i) => {
    if (i % 2 === 0) bars.push(<rect key={i} x={x * module} y="0" width={w * module} height={height} />)
    x += w
  })
  const total = (x + quiet) * module
  return (
    <svg className="barcode" viewBox={`0 0 ${total} ${height}`} width={total} height={height}
         role="img" aria-label={`Barcode of access key ${value}`} preserveAspectRatio="none">
      <rect width={total} height={height} fill="#fff" />
      <g fill="#000">{bars}</g>
    </svg>
  )
}

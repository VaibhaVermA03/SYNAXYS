// Downloads Geist Pixel *Circle* (SIL OFL 1.1) from the official vercel/geist-font repository into public/fonts/.
//   npm run fonts:install            (also runs automatically before `npm run dev` and `npm run build`)
//   node scripts/install-geist-pixel.mjs --force     re-download
// Never fails the build: if the download is impossible the UI simply uses the monospace fallback.
import { access, mkdir, writeFile } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const REPO = 'vercel/geist-font'
const FONT_DIR = 'fonts/GeistPixel/webfonts' // the directory the official npm package is built from
const REFS = ['main']
const OUT_DIR = resolve(dirname(fileURLToPath(import.meta.url)), '../public/fonts')
const OUT = resolve(OUT_DIR, 'geist-pixel-circle.woff2')
const LICENSE_OUT = resolve(OUT_DIR, 'GEIST-LICENSE.txt')

/** Picks the Circle .woff2 from a GitHub "contents" listing. */
export function pickCircle(listing) {
  if (!Array.isArray(listing)) return null
  return listing.find((f) => f && f.type === 'file' && /\.woff2$/i.test(f.name) && /circle/i.test(f.name) && f.download_url) ?? null
}

/** WOFF2 files start with the ASCII bytes "wOF2" (guards against saving an HTML error page as a font). */
export function isWoff2(buf) {
  return !!buf && buf.length > 4 && buf[0] === 0x77 && buf[1] === 0x4f && buf[2] === 0x46 && buf[3] === 0x32
}

const exists = (p) => access(p).then(() => true, () => false)

async function getJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'synaxys-font-installer' } })
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`)
  return res.json()
}

async function getBuffer(url) {
  const res = await fetch(url, { headers: { 'User-Agent': 'synaxys-font-installer' } })
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${url}`)
  return Buffer.from(await res.arrayBuffer())
}

export async function main(argv = process.argv.slice(2)) {
  const force = argv.includes('--force')
  if (!force && (await exists(OUT))) return 0 // already installed
  try {
    let file = null
    for (const ref of REFS) {
      const listing = await getJson(`https://api.github.com/repos/${REPO}/contents/${FONT_DIR}?ref=${ref}`)
      file = pickCircle(listing)
      if (file) break
    }
    if (!file) throw new Error(`no Circle .woff2 found in ${REPO}/${FONT_DIR}`)
    const buf = await getBuffer(file.download_url)
    if (!isWoff2(buf)) throw new Error('downloaded file is not a valid WOFF2')
    await mkdir(OUT_DIR, { recursive: true })
    await writeFile(OUT, buf)
    try { await writeFile(LICENSE_OUT, await getBuffer(`https://raw.githubusercontent.com/${REPO}/main/LICENSE.txt`)) } catch { /* licence copy is best effort */ }
    console.log(`[fonts] installed ${file.name} -> public/fonts/geist-pixel-circle.woff2`)
  } catch (err) {
    console.warn(`[fonts] could not install Geist Pixel Circle (${err.message}). Headings will use a monospace fallback. Run "npm run fonts:install" when online, then commit public/fonts/.`)
  }
  return 0
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) {
  main().then((code) => process.exit(code))
}

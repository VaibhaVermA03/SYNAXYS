import { describe, expect, it } from 'vitest'
import { isWoff2, pickCircle } from '../../scripts/install-geist-pixel.mjs'

const file = (name, extra = {}) => ({ name, type: 'file', download_url: `https://raw.example/${name}`, ...extra })

describe('Geist Pixel installer helpers', () => {
  it('picks the Circle .woff2 and nothing else', () => {
    const listing = [file('GeistPixel-Square.woff2'), file('GeistPixel-Circle.ttf'), file('GeistPixel-Circle.woff2'), { name: 'circle', type: 'dir' }]
    expect(pickCircle(listing).name).toBe('GeistPixel-Circle.woff2')
    expect(pickCircle([file('geistpixel-CIRCLE.WOFF2')]).name).toBe('geistpixel-CIRCLE.WOFF2')   // case-insensitive
  })
  it('returns null for listings without a usable Circle file or bad input', () => {
    expect(pickCircle([file('GeistPixel-Grid.woff2')])).toBeNull()
    expect(pickCircle([file('GeistPixel-Circle.woff2', { download_url: undefined })])).toBeNull()
    expect(pickCircle(null)).toBeNull()
    expect(pickCircle({ message: 'Not Found' })).toBeNull()
  })
  it('recognises real WOFF2 data and rejects HTML error pages', () => {
    const bytes = (text) => new TextEncoder().encode(text)
    expect(isWoff2(bytes('wOF2....'))).toBe(true)
    expect(isWoff2(bytes('<!DOCTYPE html>'))).toBe(false)
    expect(isWoff2(null)).toBe(false)
  })
})

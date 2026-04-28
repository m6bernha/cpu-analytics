// PNG export helper for AthleteCard. Wraps `html-to-image` behind a dynamic
// import so the dependency lands in the LifterDetail lazy chunk rather than
// the main bundle. Only the `LifterDetail` page imports `exportCard.ts`,
// and it imports it via a regular ESM import; the dynamic `import()` inside
// `exportCardToPng` keeps the html-to-image bytes (~6 KB gzipped) in their
// own split rather than glued to the LifterDetail chunk root.
//
// Used by the Download PNG button mounted alongside AthleteCard. See ADR
// 0001 for the design and bundle reasoning.

export async function exportCardToPng(
  node: HTMLElement | null,
  filename: string,
): Promise<void> {
  if (!node) {
    return
  }
  const { toPng } = await import('html-to-image')
  const dataUrl = await toPng(node, {
    pixelRatio: 2,
    cacheBust: true,
    // Keep the visual identical to the on-screen card; the dark zinc
    // background already lives on the card itself, so no extra fill.
  })
  const a = document.createElement('a')
  a.href = dataUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
}

// Native PDF export for the Scout report (Phase 4 of the Scout plan).
// html-to-image rasterizes the report DOM at 2x, then the tall image is
// sliced into A4 pages via an offscreen canvas and assembled with jsPDF.
// Both libraries load lazily so the chunk only ships on first export.
//
// Page breaks can land mid-row, same as browser print. Acceptable for v1;
// row-aware slicing would need per-element measurement.

export async function exportReportPdf(
  node: HTMLElement,
  filename: string,
): Promise<void> {
  const [{ toPng }, { jsPDF }] = await Promise.all([
    import('html-to-image'),
    import('jspdf'),
  ])

  const dataUrl = await toPng(node, {
    pixelRatio: 2,
    backgroundColor: '#09090b', // zinc-950, matches the app background
  })

  const img = new Image()
  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve()
    img.onerror = () => reject(new Error('report image failed to render'))
    img.src = dataUrl
  })

  const pdf = new jsPDF({ unit: 'pt', format: 'a4' })
  const margin = 24
  const contentW = pdf.internal.pageSize.getWidth() - margin * 2
  const contentH = pdf.internal.pageSize.getHeight() - margin * 2
  const scale = contentW / img.width
  const sliceHpx = Math.floor(contentH / scale)

  const pageCanvas = document.createElement('canvas')
  pageCanvas.width = img.width
  const ctx = pageCanvas.getContext('2d')
  if (!ctx) throw new Error('canvas 2d context unavailable')

  const nPages = Math.max(1, Math.ceil(img.height / sliceHpx))
  for (let p = 0; p < nPages; p++) {
    const srcY = p * sliceHpx
    const thisSliceH = Math.min(sliceHpx, img.height - srcY)
    pageCanvas.height = thisSliceH
    ctx.fillStyle = '#09090b'
    ctx.fillRect(0, 0, pageCanvas.width, thisSliceH)
    ctx.drawImage(img, 0, srcY, img.width, thisSliceH, 0, 0, img.width, thisSliceH)
    if (p > 0) pdf.addPage()
    pdf.addImage(
      pageCanvas.toDataURL('image/png'),
      'PNG',
      margin,
      margin,
      contentW,
      thisSliceH * scale,
    )
  }
  pdf.save(filename)
}

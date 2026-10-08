/** Save the report as PDF through the browser's print dialog; the filename becomes the PDF's default name. */
export function downloadPdf(filename: string) {
  const previous = document.title;
  document.title = filename;
  window.addEventListener('afterprint', () => (document.title = previous), { once: true });
  window.print();
}

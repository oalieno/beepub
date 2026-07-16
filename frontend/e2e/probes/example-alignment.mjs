// Example probe: page-grid alignment of a vertical book across deep flips.
// node e2e/probes/example-alignment.mjs
import path from "node:path";
import { fileURLToPath } from "node:url";
import { adminApi, seedBook, openReader, measureAlignment } from "./lib.mjs";

const FIXTURE = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "fixtures",
  "e2e-vertical-long-book.epub",
);

const { token, api } = await adminApi();
const bookId = await seedBook(api, "直書均勻格線", FIXTURE);
const { browser, page } = await openReader(bookId, {
  device: { width: 742, height: 1000 },
  margin: 32,
  token,
});

for (let i = 1; i <= 12; i++) {
  await page.keyboard.press("ArrowLeft"); // next page (rtl book)
  await page.waitForTimeout(400);
  if (i % 4 === 0) console.log(`p${i}:`, JSON.stringify(await measureAlignment(page)));
}
await browser.close();

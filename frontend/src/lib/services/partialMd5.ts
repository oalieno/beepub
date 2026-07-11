/**
 * KOReader-compatible partial-MD5 document digest — the JS twin of
 * backend/app/services/partial_md5.py. Both must produce the digest
 * KOReader computes on-device: md5 of 1 KiB samples at offsets
 * `1024 << (2*i)` for i = -1..10.
 *
 * The i = -1 step is the LuaJIT BitOp quirk: shift counts are masked to
 * 5 bits, so `1024 << 30` — which overflows int32 to 0 in JS as well —
 * samples the file head. Do not "fix" the offset formula; changing any
 * sample breaks cross-device matching.
 */

import SparkMD5 from "spark-md5";

const STEP = 1024;
const SAMPLE_SIZE = 1024;

export async function computePartialMd5(file: Blob): Promise<string> {
  const spark = new SparkMD5.ArrayBuffer();
  for (let i = -1; i <= 10; i++) {
    const offset = (STEP << ((2 * i) & 31)) >>> 0;
    // Offsets are monotonic after the i = -1 head sample, so running past
    // EOF here matches Python's break-on-empty-read.
    if (offset >= file.size) break;
    const chunk = await file.slice(offset, offset + SAMPLE_SIZE).arrayBuffer();
    if (chunk.byteLength === 0) break;
    spark.append(chunk);
  }
  return spark.end();
}

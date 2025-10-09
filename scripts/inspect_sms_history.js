#!/usr/bin/env node
// Usage: node scripts/inspect_sms_history.js path/to/sms_history.json
// The file should contain a JSON array of history records.

const fs = require("fs");

function classifyRecord(r) {
  const rawStatus = r.status || r.Status || r.status_text || "";
  const status = String(rawStatus || "").trim();
  const statusNorm = status.replace(/\s+/g, "").toLowerCase();

  // target out checks
  if (
    statusNorm === "対象外" ||
    statusNorm === "target_out" ||
    statusNorm === "taishougai" ||
    statusNorm.indexOf("対象外") >= 0
  ) {
    return { kind: "target_out" };
  }

  // explicit success
  if (
    status === "送信済" ||
    status.startsWith("送信済") ||
    (status.indexOf("送信") >= 0 && status.indexOf("済") >= 0)
  ) {
    return { kind: "sent" };
  }

  const resp = r.response;
  if (resp !== undefined && resp !== null) {
    if (typeof resp === "object") {
      const sc =
        resp.status_code ?? resp.status ?? resp.code ?? resp.codeNumber;
      const scNum = Number(sc);
      if (!Number.isNaN(scNum) && scNum >= 200 && scNum < 300)
        return { kind: "sent", code: scNum };
      return { kind: "failed", code: scNum || null, resp };
    } else {
      const scNum = Number(resp);
      if (!Number.isNaN(scNum) && scNum >= 200 && scNum < 300)
        return { kind: "sent", code: scNum };
      if (String(resp).indexOf("200") >= 0)
        return { kind: "sent", note: "contains 200" };
      return { kind: "failed", resp };
    }
  }

  // fallback: treat as failed
  return { kind: "failed" };
}

function run(path) {
  if (!fs.existsSync(path)) {
    console.error("File not found:", path);
    process.exit(2);
  }
  const raw = fs.readFileSync(path, "utf8");
  let arr;
  try {
    arr = JSON.parse(raw);
  } catch (e) {
    console.error("Failed to parse JSON:", e.message);
    process.exit(2);
  }
  if (!Array.isArray(arr)) {
    console.error("JSON must be an array of records");
    process.exit(2);
  }

  let total = 0,
    sent = 0,
    failed = 0,
    targetOut = 0;
  const failedItems = [];

  arr.forEach((r) => {
    total += 1;
    const res = classifyRecord(r);
    if (res.kind === "sent") sent += 1;
    else if (res.kind === "target_out") targetOut += 1;
    else if (res.kind === "failed") {
      failed += 1;
      failedItems.push({ record: r, info: res });
    }
  });

  console.log(
    `total=${total} sent=${sent} failed=${failed} targetOut=${targetOut}`
  );
  console.log("--- failed items (up to 200) ---");
  failedItems.slice(0, 200).forEach((f, i) => {
    console.log(
      `[#${i}] status=${JSON.stringify(
        f.record.status
      )} response=${JSON.stringify(f.record.response)} => info=${JSON.stringify(
        f.info
      )}`
    );
  });
}

if (require.main === module) {
  const p = process.argv[2];
  if (!p) {
    console.error(
      "Usage: node scripts/inspect_sms_history.js path/to/sms_history.json"
    );
    process.exit(2);
  }
  run(p);
}

import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import admin from "../../../lib/firebaseAdmin";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const idToken = body.idToken;
    if (!idToken)
      return NextResponse.json(
        { ok: false, error: "missing idToken" },
        { status: 400 }
      );

    const decoded = await admin.auth().verifyIdToken(idToken);
    return NextResponse.json({ ok: true, decoded });
  } catch (err: any) {
    return NextResponse.json(
      { ok: false, error: err.message || String(err) },
      { status: 500 }
    );
  }
}

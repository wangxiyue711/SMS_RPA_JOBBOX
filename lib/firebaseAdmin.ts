import admin from "firebase-admin";

const projectId = process.env.FIREBASE_PROJECT_ID;
const clientEmail = process.env.FIREBASE_CLIENT_EMAIL;
let privateKey = process.env.FIREBASE_PRIVATE_KEY as string | undefined;

if (privateKey && privateKey.includes("\\n")) {
  // When setting FIREBASE_PRIVATE_KEY in env vars, newlines are often escaped.
  privateKey = privateKey.replace(/\\n/g, "\n");
}

const cert =
  projectId && clientEmail && privateKey
    ? { projectId, clientEmail, privateKey }
    : undefined;

if (!admin.apps.length) {
  if (cert) {
    admin.initializeApp({ credential: admin.credential.cert(cert as any) });
  } else {
    // fallback to default credentials (useful in some hosting environments)
    admin.initializeApp();
  }
}

export default admin;

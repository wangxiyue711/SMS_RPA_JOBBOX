import { getApps, initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

function initFirebaseClient() {
  if (typeof window === "undefined") return;
  try {
    if (!getApps().length) {
      initializeApp(firebaseConfig);
    }
  } catch (err) {
    // swallow client init errors to avoid breaking hydration
    // errors can be logged if needed
    // console.error('initFirebaseClient error', err);
  }
}

// Return the client-side Auth instance or null on server
export function getClientAuth() {
  if (typeof window === "undefined") return null;
  try {
    initFirebaseClient();
    return getAuth();
  } catch (err) {
    // prevent throwing during client mount
    // console.error('getClientAuth error', err);
    return null;
  }
}

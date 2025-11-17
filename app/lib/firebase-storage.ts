"use client";

import { FirebaseApp, FirebaseOptions, getApps, initializeApp } from "firebase/app";
import { FirebaseStorage, getDownloadURL, getStorage, ref } from "firebase/storage";

type ResolvedUrl = string | null;

const firebaseConfig: FirebaseOptions = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
};

let firebaseApp: FirebaseApp | null = null;
let storageInstance: FirebaseStorage | null = null;

const ensureFirebaseApp = (): FirebaseApp | null => {
  if (firebaseApp) {
    return firebaseApp;
  }
  if (getApps().length > 0) {
    firebaseApp = getApps()[0]!;
    return firebaseApp;
  }
  try {
    firebaseApp = initializeApp(firebaseConfig);
    return firebaseApp;
  } catch (error) {
    console.error("Failed to initialize Firebase app for figure resolution:", error);
    return null;
  }
};

const ensureStorage = (): FirebaseStorage | null => {
  if (storageInstance) {
    return storageInstance;
  }
  const app = ensureFirebaseApp();
  if (!app) {
    return null;
  }
  try {
    storageInstance = getStorage(app);
    return storageInstance;
  } catch (error) {
    console.error("Failed to initialize Firebase storage client:", error);
    return null;
  }
};

export const resolveStorageUrl = async (imageUri: string | null | undefined): Promise<ResolvedUrl> => {
  if (!imageUri) {
    return null;
  }
  if (!imageUri.startsWith("gs://")) {
    return imageUri;
  }
  const storage = ensureStorage();
  if (!storage) {
    return null;
  }
  try {
    const objectRef = ref(storage, imageUri);
    const url = await getDownloadURL(objectRef);
    return url;
  } catch (error) {
    console.error("Unable to resolve figure URI", error);
    return null;
  }
};

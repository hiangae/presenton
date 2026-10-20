import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en.json";
import ko from "./locales/ko.json";

const resources = {
  en: { translation: en },
  ko: { translation: ko },
};

export const SUPPORTED_LANGUAGES = [
  { code: "en", label: "English" },
  { code: "ko", label: "한국어" },
] as const;

let initialized = false;

export function initI18n() {
  if (initialized) return i18n;
  initialized = true;

  void i18n
    .use(LanguageDetector)
    .use(initReactI18next)
    .init({
      resources,
      fallbackLng: "en",
      supportedLngs: ["en", "ko"],
      detection: {
        order: ["localStorage", "navigator"],
        lookupLocalStorage: "presenton_language",
        caches: ["localStorage"],
      },
      interpolation: { escapeValue: false },
      react: { useSuspense: false },
    });

  return i18n;
}

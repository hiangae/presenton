"use client";

import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGUAGES } from "@/i18n";

export default function LanguageSwitcher() {
  const { i18n } = useTranslation();
  const current = i18n.language?.split("-")[0] ?? "en";

  return (
    <div className="flex items-center gap-1 rounded-full border border-[#EDEEEF] bg-white p-1">
      {SUPPORTED_LANGUAGES.map((lang) => (
        <button
          key={lang.code}
          type="button"
          onClick={() => void i18n.changeLanguage(lang.code)}
          className={`rounded-full px-3 py-1 text-xs font-medium transition ${
            current === lang.code
              ? "bg-[#7C51F8] text-white"
              : "text-[#6B7280] hover:bg-[#F4F3FF]"
          }`}
        >
          {lang.label}
        </button>
      ))}
    </div>
  );
}

"use client";

import { useTranslation } from "react-i18next";

const UploadHero = () => {
  const { t } = useTranslation();

  return (
    <div className="mb-7 flex flex-col items-center justify-center gap-1.5 px-4 text-center">
      <h1 className="font-syne text-[36px] font-medium leading-normal tracking-[-0.58px] text-[#101323] sm:text-[48px] lg:text-[58px] lg:leading-[70px]">
        {t("upload.hero_title")}
      </h1>
      <p className="max-w-[609px] font-syne text-base leading-[1.4] tracking-[0.2px] text-[#101323CC] sm:text-xl">{t("upload.hero_subtitle")}</p>
    </div>
  );
};

export default UploadHero;

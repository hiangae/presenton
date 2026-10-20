"use client";
import React from 'react'
import { useTranslation } from 'react-i18next'
import { LogOut, Search, Shield, ShieldCheck } from 'lucide-react'
import { IMAGE_PROVIDERS, LLM_PROVIDERS } from '@/utils/providerConstants'
import { useSelector } from 'react-redux'
import { RootState } from '@/store/store'

export type SettingsSection = 'text-provider' | 'image-provider' | 'web-search-provider' | 'privacy' | 'admin' | 'session'

const SettingSideBar = ({ selectedProvider, setSelectedProvider, presentonSelected = false }: { selectedProvider: SettingsSection, setSelectedProvider: (provider: SettingsSection) => void, presentonSelected?: boolean }) => {
    const { t } = useTranslation()
    const { llm_config } = useSelector((state: RootState) => state.userConfig)
    const textProviderIcon = LLM_PROVIDERS[llm_config.LLM as keyof typeof LLM_PROVIDERS]?.icon
    const imageProviderIcon = IMAGE_PROVIDERS[llm_config.IMAGE_PROVIDER as keyof typeof IMAGE_PROVIDERS]?.icon || '/providers/pexel.png'
    return (
        <div className='w-full max-w-[230px] h-screen px-3 pt-[22px] bg-[#F9FAFB] flex flex-col'>
            <p className='text-xs text-black  font-medium border-b mt-[3.15rem]  border-[#E1E1E5] pb-3.5'>{t("settings.filter_by")}</p>
            <div className='mt-6 flex-1'>
                <p className='text-[#3A3A3A] text-xs font-medium pb-2.5'>{t("settings.select_provider")}</p>
                <div className='space-y-2.5'>
                    <button className={` w-full rounded-[6px] px-3 py-4 flex items-center gap-1.5 border  ${selectedProvider === 'text-provider' ? 'bg-[#F4F3FF] border-[#D9D6FE]' : 'bg-white border-[#EDEEEF]'}`} onClick={() => setSelectedProvider('text-provider')}>
                        <div className='relative w-[18px] h-[18px] rounded-full overflow-hidden border border-[#EDEEEF]'>

                            <img src={textProviderIcon} className=' object-cover w-full h-full overflow-hidden' alt='google' />
                        </div>
                        <p className='text-[#191919] text-xs  font-medium' >{t("settings.text_provider")}</p>
                    </button>
                    {!presentonSelected ? (
                        <>
                            <button className={` w-full rounded-[6px] px-3 py-4 flex items-center gap-1.5 border  ${selectedProvider === 'image-provider' ? 'bg-[#F4F3FF] border-[#D9D6FE]' : 'bg-white border-[#EDEEEF]'}`} onClick={() => setSelectedProvider('image-provider')}>
                                <div className='relative w-[18px] h-[18px] rounded-full overflow-hidden border border-[#EDEEEF]'>
                                    <img src={imageProviderIcon} className=' object-cover w-full h-full overflow-hidden' alt='image provider' />
                                </div>
                                <p className='text-[#191919] text-xs  font-medium' >{t("settings.image_provider")}</p>
                            </button>
                            <button className={` w-full rounded-[6px] px-3 py-4 flex items-center gap-1.5 border  ${selectedProvider === 'web-search-provider' ? 'bg-[#F4F3FF] border-[#D9D6FE]' : 'bg-white border-[#EDEEEF]'}`} onClick={() => setSelectedProvider('web-search-provider')}>
                                <div className='relative w-[18px] h-[18px] rounded-full overflow-hidden border border-[#EDEEEF] flex items-center justify-center bg-white'>
                                    <Search className='w-3 h-3 text-[#5146E5]' />
                                </div>
                                <p className='text-[#191919] text-xs font-medium'>{t("settings.web_search_provider")}</p>
                            </button>
                        </>
                    ) : null}
                </div>
            </div>

            <div className='border-t border-[#E1E1E5] py-5 relative z-50'>
                <p className='text-[#3A3A3A] text-xs font-medium pb-2.5'>{t("settings.other")}</p>
                <div className='space-y-2.5'>
                    <button
                        className={`w-full rounded-[6px] p-3 py-4 flex items-center gap-1.5 border ${selectedProvider === 'privacy' ? 'bg-[#F4F3FF] border-[#D9D6FE]' : 'bg-white border-[#EDEEEF]'}`}
                        onClick={() => setSelectedProvider('privacy')}
                    >
                        <div className='relative w-6 h-6 rounded-full overflow-hidden border border-[#EDEEEF] flex items-center justify-center bg-white'>
                            <Shield className='w-3.5 h-3.5 text-[#5146E5]' />
                        </div>
                        <p className='text-[#191919] text-xs font-medium'>{t("settings.usage_analytics")}</p>
                    </button>
                    <button
                        className={`w-full rounded-[6px] p-3 py-4 flex items-center gap-1.5 border ${selectedProvider === 'admin' ? 'bg-[#F4F3FF] border-[#D9D6FE]' : 'bg-white border-[#EDEEEF]'}`}
                        onClick={() => setSelectedProvider('admin')}
                    >
                        <div className='relative w-6 h-6 rounded-full overflow-hidden border border-[#EDEEEF] flex items-center justify-center bg-white'>
                            <ShieldCheck className='w-3.5 h-3.5 text-[#5146E5]' />
                        </div>
                        <p className='text-[#191919] text-xs font-medium'>{t("settings.admin_panel")}</p>
                    </button>
                    <button
                        className={`w-full rounded-[6px] p-3 py-4 flex items-center gap-1.5 border ${selectedProvider === 'session' ? 'bg-[#F4F3FF] border-[#D9D6FE]' : 'bg-white border-[#EDEEEF]'}`}
                        onClick={() => setSelectedProvider('session')}
                    >
                        <div className='relative w-6 h-6 rounded-full overflow-hidden border border-[#EDEEEF] flex items-center justify-center bg-white'>
                            <LogOut className='w-3.5 h-3.5 text-[#5146E5]' />
                        </div>
                        <p className='text-[#191919] text-xs font-medium'>{t("settings.sign_out")}</p>
                    </button>
                </div>
            </div>
        </div>
    )
}

export default SettingSideBar

import React, { useState } from "react";
import {
    Tv,
    Globe,
    Key,
    Languages,
    Sliders,
    Sparkles,
    Check,
    Save,
    Cpu,
    Download,
    Trash2,
} from "lucide-react";
import { Button, Card, Input, Switch } from "../ui/primitives";
import { useLanguage } from "../../contexts/LanguageContext";
import { useToast } from "../ui/Toast";

export interface AnimeSettings {
    defaultSource: string;
    titleLanguage: "korean" | "english" | "original";
    tmdbApiKey: string;
    translationMode: "off" | "api" | "local";
    translationModel: string;
    translationApiKey: string;
    autoSkip: boolean;
    defaultSpeed: number;
    defaultSeekStep: number;
    defaultAspect: "contain" | "cover" | "fill";
}

const STORAGE_KEY = "phrolova_anime_settings";

export const DEFAULT_ANIME_SETTINGS: AnimeSettings = {
    defaultSource: "ohli24",
    titleLanguage: "korean",
    tmdbApiKey: "",
    translationMode: "off",
    translationModel: "gemini-3.8-flash",
    translationApiKey: "",
    autoSkip: true,
    defaultSpeed: 1,
    defaultSeekStep: 10,
    defaultAspect: "contain",
};

export function getStoredAnimeSettings(): AnimeSettings {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) return { ...DEFAULT_ANIME_SETTINGS, ...JSON.parse(raw) };
    } catch {}
    return DEFAULT_ANIME_SETTINGS;
}

export function saveStoredAnimeSettings(settings: AnimeSettings): void {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {}
}

const SOURCES = [
    {
        id: "aniwolf",
        name: "애니울프 (AniWolf)",
        catalog: "최신 방영작 및 역대 분기 신작 VOD 카탈로그",
        video: "CDNDania / MichealCDN 고화질 HLS 스트리밍",
        sub: "영상 자체 한국어 자막 탑재",
    },
    {
        id: "aniweek",
        name: "애니위크 (AniWeek)",
        catalog: "Inertia 실시간 고속 카탈로그 및 요일별 방영표",
        video: "MichealCDN 1080p 고화질 스트리밍",
        sub: "자체 한글 자막 스트림",
    },
    {
        id: "zzapflix",
        name: "짭플릭스 (Zzapflix)",
        catalog: "영화, 드라마, 숏드, 예능, 애니 종합 VOD",
        video: "Artplayer HLS 고화질 스트리밍",
        sub: "자체 한글 자막 및 한국어 오디오",
    },
    {
        id: "reanime",
        name: "RE:Anime",
        catalog: "2만여 작품, 한국어 검색",
        video: "자막 없는 영상",
        sub: "사이트 여러 언어 자막 트랙 (한국어 트랙 자동 적용)",
    },
    {
        id: "ohli24",
        name: "애니24 (Ohli24)",
        catalog: "한국어 목록·검색, 원제·장르·방영일",
        video: "1080p 고화질",
        sub: "영상에 박힌 한국어 자막 (추가 자막 탐색 불필요)",
    },
    {
        id: "linkani",
        name: "링크애니 (Linkani)",
        catalog: "한국어 목록·검색, TOP 인기순",
        video: "1080p 고화질",
        sub: "영상에 박힌 한국어 자막, 자체 한국어 자막 파일",
    },
    {
        id: "moeni",
        name: "모에니 (Moeni)",
        catalog: "최신 신작 HLS 카탈로그",
        video: "동적 복호화 HLS",
        sub: "자체 고화질 한글 자막 스트림",
    },
    {
        id: "miruro",
        name: "Miruro",
        catalog: "한국어 검색, 회차 제목·방영일",
        video: "서버 선택: SUB · RAW · SOFT · DUB",
        sub: "SOFT 서버의 다국어 자막 트랙",
    },
    {
        id: "animenosub",
        name: "Animenosub",
        catalog: "한국어 검색 카탈로그",
        video: "서버 선택: SUB · RAW",
        sub: "한국어 자막 온라인 검색",
    },
    {
        id: "linkkf",
        name: "Linkkf",
        catalog: "한국어 목록 카탈로그",
        video: "사이트 기본 영상",
        sub: "사이트의 한국어 자막",
    },
];

const LOCAL_AI_MODELS = [
    { id: "gemma-4-e4b", name: "Gemma 4 E4B", size: "5.2GB", note: "기본 · 가장 정확하고 빠름", installed: true },
    { id: "aya-8b", name: "Aya Expanse 8B", size: "5.1GB", note: "정확함 · 형/누나를 잘 맞춤 · VRAM 6GB+", installed: false },
    { id: "gemma-4-e2b", name: "Gemma 4 E2B", size: "3.4GB", note: "가볍고 빠름 · 가끔 뜻을 틀림", installed: false },
    { id: "hy-mt2-1.8b", name: "Hy-MT2 1.8B", size: "1.1GB", note: "가장 가볍고 빠름 · 존댓말 섞이고 자주 틀림", installed: false },
];

const S_TXT = {
    modeLabel: "자막 자동 번역 모드",
    off: "끄기",
    api: "번역 API",
    local: "로컬 AI",
    modelLabel: "번역 모델",
    modelNote: "키를 저장하면 쓸 수 있는 모델을 불러와 최신 Flash 모델을 고릅니다.",
    apiKeyLabel: "번역 API 키",
    localAiTitle: "로컬 AI 모델 (llama.cpp)",
    localAiDesc: "인터넷 없이 이 PC에서 번역합니다. 그래픽카드(NVIDIA CUDA, AMD ROCm, Intel SYCL, Vulkan)를 사용하여 초고속 번역합니다.",
    inUse: "사용 중",
    download: (size: string) => `받기 · ${size}`,
    autoSkip: "AniSkip 자동 건너뛰기",
    seekStep: "기본 탐색 간격 (초)",
    seekDesc: "좌우 방향키로 이동할 시간 간격입니다.",
    sec5: "5초",
    sec10: "10초",
    sec15: "15초",
    sec30: "30초",
    aspect: "기본 화면 비율",
    aspectDesc: "플레이어 재생 시 기본으로 적용할 화면 비율 모드입니다.",
    aspectFit: "원본 비율 유지 (Fit)",
    aspectCover: "화면 채우기 (Crop)",
    aspectStretch: "비율 늘리기 (Stretch)",
    save: "설정 저장",
};

export function AnimeTab() {
    const { t } = useLanguage();
    const toast = useToast();
    const [settings, setSettings] = useState<AnimeSettings>(getStoredAnimeSettings);
    const [isSaved, setIsSaved] = useState(false);

    const handleSave = () => {
        saveStoredAnimeSettings(settings);
        setIsSaved(true);
        toast.success("Settings saved.");
        setTimeout(() => setIsSaved(false), 2000);
    };

    return (
        <div className="space-y-6 text-white">
            {/* 1. Content Sources Section */}
            <Card className="p-6">
                <div className="flex items-center gap-2.5 mb-2 text-ink">
                    <Tv className="size-5 text-[#C8A2C8]" />
                    <h2 className="text-base font-bold">{t("settings.animeSourceTitle")}</h2>
                </div>
                <p className="text-xs text-ink-faint mb-5 leading-relaxed">
                    {t("settings.animeSourceDesc")}
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    {SOURCES.map((src) => {
                        const isSelected = settings.defaultSource === src.id;
                        return (
                            <div
                                key={src.id}
                                onClick={() => setSettings({ ...settings, defaultSource: src.id })}
                                className={`p-4 rounded-xl border text-left cursor-pointer transition-all ${
                                    isSelected
                                        ? "border-[#C8A2C8] bg-lilac-faint shadow-md"
                                        : "border-white/10 hover:border-white/20 bg-black/30"
                                }`}
                            >
                                <div className="flex items-center justify-between mb-2">
                                    <span className="text-sm font-bold text-white flex items-center gap-2">
                                        <span>{src.name}</span>
                                    </span>
                                    {isSelected && (
                                        <span className="size-2 rounded-full bg-[#C8A2C8]" />
                                    )}
                                </div>
                                <div className="space-y-1 text-[11px] text-gray-300">
                                    <p className="text-gray-400">· {src.catalog}</p>
                                    <p className="text-[#C8A2C8]">· {src.video}</p>
                                    <p className="text-gray-400">· {src.sub}</p>
                                </div>
                            </div>
                        );
                    })}
                </div>
            </Card>

            {/* 2. Title Display Language */}
            <Card className="p-6">
                <div className="flex items-center gap-2.5 mb-2 text-ink">
                    <Globe className="size-5 text-[#C8A2C8]" />
                    <h2 className="text-base font-bold">{t("settings.animeTitleLangTitle")}</h2>
                </div>
                <p className="text-xs text-ink-faint mb-4 leading-relaxed">
                    {t("settings.animeTitleLangDesc")}
                </p>
                <div className="flex flex-wrap gap-3">
                    {[
                        { id: "korean", label: "한국어 우선 (Korean)" },
                        { id: "english", label: "영어 공식명 (English)" },
                        { id: "original", label: "원어 표기 (Japanese / Original)" },
                    ].map((lang) => (
                        <button
                            key={lang.id}
                            type="button"
                            onClick={() => setSettings({ ...settings, titleLanguage: lang.id as any })}
                            className={`px-4 py-2.5 rounded-xl border text-xs font-semibold transition-all ${
                                settings.titleLanguage === lang.id
                                    ? "border-[#C8A2C8] bg-lilac-faint text-white font-bold shadow-sm"
                                    : "border-white/10 hover:border-white/20 text-gray-300"
                            }`}
                        >
                            {lang.label}
                        </button>
                    ))}
                </div>
            </Card>

            {/* 3. TMDB API Key */}
            <Card className="p-6">
                <div className="flex items-center gap-2.5 mb-2 text-ink">
                    <Key className="size-5 text-[#C8A2C8]" />
                    <h2 className="text-base font-bold">{t("settings.animeTmdbTitle")}</h2>
                </div>
                <p className="text-xs text-ink-faint mb-4 leading-relaxed">
                    {t("settings.animeTmdbDesc")}
                </p>
                <div className="max-w-md">
                    <Input
                        type="password"
                        value={settings.tmdbApiKey}
                        onChange={(e) => setSettings({ ...settings, tmdbApiKey: e.target.value })}
                        placeholder="TMDB API Token (v4) / API Key (v3)"
                        className="w-full text-xs"
                    />
                </div>
            </Card>

            {/* 4. Automated Subtitle Translation (100% Lilac Parity) */}
            <Card className="p-6">
                <div className="flex items-center gap-2.5 mb-2 text-ink">
                    <Languages className="size-5 text-[#C8A2C8]" />
                    <h2 className="text-base font-bold">{t("settings.animeTranslationTitle")}</h2>
                </div>
                <p className="text-xs text-ink-faint mb-4 leading-relaxed">
                    {t("settings.animeTranslationDesc")}
                </p>

                {/* Mode Selector */}
                <div className="mb-6">
                    <label className="text-xs font-semibold text-gray-300 block mb-2">
                        {S_TXT.modeLabel}
                    </label>
                    <div className="inline-flex rounded-xl bg-black/40 border border-white/10 p-1 text-xs">
                        {[
                            { id: "off", label: S_TXT.off },
                            { id: "api", label: S_TXT.api },
                            { id: "local", label: S_TXT.local },
                        ].map((m) => (
                            <button
                                key={m.id}
                                type="button"
                                onClick={() => setSettings({ ...settings, translationMode: m.id as any })}
                                className={`px-4 py-1.5 rounded-lg font-semibold transition-all ${
                                    settings.translationMode === m.id
                                        ? "bg-white text-gray-950 font-bold shadow-md"
                                        : "text-gray-400 hover:text-white"
                                }`}
                            >
                                {m.label}
                            </button>
                        ))}
                    </div>
                </div>

                {/* API Mode Settings */}
                {settings.translationMode === "api" && (
                    <div className="space-y-4 max-w-md p-4 rounded-xl bg-black/30 border border-white/5 mb-6">
                        <div>
                            <label className="text-xs font-semibold text-gray-300 block mb-1.5">
                                {S_TXT.modelLabel}
                            </label>
                            <select
                                value={settings.translationModel}
                                onChange={(e) => setSettings({ ...settings, translationModel: e.target.value })}
                                className="w-full px-3 py-2 rounded-xl bg-black/50 border border-white/10 text-xs text-white focus:border-[#C8A2C8]"
                            >
                                <option value="gemini-3.8-flash">gemini-3.8-flash (Flash)</option>
                                <option value="gpt-4o-mini">gpt-4o-mini (OpenAI)</option>
                                <option value="deepl">DeepL API</option>
                                <option value="claude-3-5-haiku">Claude 3.5 Haiku</option>
                            </select>
                            <p className="text-[10px] text-gray-400 mt-1">
                                {S_TXT.modelNote}
                            </p>
                        </div>

                        <div>
                            <label className="text-xs font-semibold text-gray-300 block mb-1.5">
                                {S_TXT.apiKeyLabel}
                            </label>
                            <Input
                                type="password"
                                value={settings.translationApiKey}
                                onChange={(e) => setSettings({ ...settings, translationApiKey: e.target.value })}
                                placeholder="API Key"
                                className="w-full text-xs"
                            />
                        </div>
                    </div>
                )}

                {/* Local AI Models List */}
                {settings.translationMode === "local" && (
                    <div className="space-y-2 mb-6">
                        <label className="text-xs font-semibold text-gray-300 block mb-1 flex items-center gap-1.5">
                            <Cpu className="size-3.5 text-[#C8A2C8]" />
                            <span>{S_TXT.localAiTitle}</span>
                        </label>
                        <p className="text-[11px] text-gray-400 mb-3">
                            {S_TXT.localAiDesc}
                        </p>
                        <div className="space-y-2">
                            {LOCAL_AI_MODELS.map((model) => (
                                <div
                                    key={model.id}
                                    className="p-3.5 rounded-xl bg-black/30 border border-white/5 flex items-center justify-between"
                                >
                                    <div>
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs font-bold text-white">{model.name}</span>
                                            <span className="text-[10px] text-[#C8A2C8]">{model.size}</span>
                                        </div>
                                        <p className="text-[11px] text-gray-400 mt-0.5">{model.note}</p>
                                    </div>

                                    <div>
                                        {model.installed ? (
                                            <div className="flex items-center gap-2">
                                                <span className="text-xs font-semibold text-[#C8A2C8]">{S_TXT.inUse}</span>
                                                <button
                                                    type="button"
                                                    className="p-1.5 rounded-lg hover:bg-white/10 text-gray-400 hover:text-rose-400 transition-all"
                                                >
                                                    <Trash2 className="size-3.5" />
                                                </button>
                                            </div>
                                        ) : (
                                            <button
                                                type="button"
                                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/15 text-xs font-semibold text-white transition-all"
                                            >
                                                <Download className="size-3" />
                                                <span>{S_TXT.download(model.size)}</span>
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </Card>

            {/* 5. Player Preferences */}
            <Card className="p-6">
                <div className="flex items-center gap-2.5 mb-2 text-ink">
                    <Sliders className="size-5 text-[#C8A2C8]" />
                    <h2 className="text-base font-bold">{t("settings.animePlayerTitle")}</h2>
                </div>
                <div className="space-y-4 text-xs">
                    <div className="flex items-center justify-between pb-3 border-b border-white/5">
                        <div>
                            <span className="font-semibold text-white block">{S_TXT.autoSkip}</span>
                            <span className="text-[11px] text-gray-400">
                                {t("settings.animeAutoSkipDesc")}
                            </span>
                        </div>
                        <Switch
                            checked={settings.autoSkip}
                            onChange={(v) => setSettings({ ...settings, autoSkip: v })}
                            label={S_TXT.autoSkip}
                        />
                    </div>

                    <div className="flex items-center justify-between pb-3 border-b border-white/5">
                        <div>
                            <span className="font-semibold text-white block">{S_TXT.seekStep}</span>
                            <span className="text-[11px] text-gray-400">
                                {S_TXT.seekDesc}
                            </span>
                        </div>
                        <select
                            value={settings.defaultSeekStep}
                            onChange={(e) => setSettings({ ...settings, defaultSeekStep: Number(e.target.value) })}
                            className="px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 text-white"
                        >
                            <option value={5}>{S_TXT.sec5}</option>
                            <option value={10}>{S_TXT.sec10}</option>
                            <option value={15}>{S_TXT.sec15}</option>
                            <option value={30}>{S_TXT.sec30}</option>
                        </select>
                    </div>

                    <div className="flex items-center justify-between">
                        <div>
                            <span className="font-semibold text-white block">{S_TXT.aspect}</span>
                            <span className="text-[11px] text-gray-400">
                                {S_TXT.aspectDesc}
                            </span>
                        </div>
                        <select
                            value={settings.defaultAspect}
                            onChange={(e) => setSettings({ ...settings, defaultAspect: e.target.value as any })}
                            className="px-3 py-1.5 rounded-lg bg-black/40 border border-white/10 text-white"
                        >
                            <option value="contain">{S_TXT.aspectFit}</option>
                            <option value="cover">{S_TXT.aspectCover}</option>
                            <option value="fill">{S_TXT.aspectStretch}</option>
                        </select>
                    </div>
                </div>
            </Card>

            {/* Action Bar */}
            <div className="flex items-center justify-end gap-3 pt-4">
                <Button
                    onClick={handleSave}
                    className="inline-flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[#C8A2C8] text-gray-950 font-bold hover:bg-[#D8B4D8] transition-all"
                >
                    {isSaved ? <Check className="size-4" /> : <Save className="size-4" />}
                    <span>{S_TXT.save}</span>
                </Button>
            </div>
        </div>
    );
}


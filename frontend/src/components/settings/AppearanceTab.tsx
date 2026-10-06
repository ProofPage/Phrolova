import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { ImageIcon, Palette, RotateCcw } from "lucide-react";
import type { Settings as SettingsType } from "../../api/client";
import { THEMES, type ThemeId, useTheme } from "../../contexts/ThemeContext";
import { LANGUAGE_OPTIONS, useLanguage } from "../../contexts/LanguageContext";
import { Button, Card, CardHeader, Field, Input, Select } from "../ui/primitives";
import { useToast } from "../ui/Toast";

interface Props {
    settings: SettingsType | null;
    /** 외관 설정은 브라우저에 즉시 저장되지만 탭 props 형태를 통일한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

export function AppearanceTab({ onDirtyChange }: Props) {
    const { themeId, customColor, pageTitle, setTheme, setCustomColor, setPageTitle, setIconUrl, resetAll } = useTheme();
    const { language, setLanguage, t } = useLanguage();
    const [titleInput, setTitleInput] = useState(pageTitle);
    const toast = useToast();
    const iconInputRef = useRef<HTMLInputElement>(null);
    const colorPickerRef = useRef<HTMLInputElement>(null);
    const dirty = titleInput !== pageTitle;

    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    const handleIconUpload = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        if (file.size > 512 * 1024) {
            toast.error(t("파일 크기는 512KB 이하여야 합니다."));
            return;
        }
        const reader = new FileReader();
        reader.onload = (loadEvent) => setIconUrl(loadEvent.target?.result as string);
        reader.readAsDataURL(file);
    };

    return (
        <Card className="space-y-5">
            <CardHeader icon={Palette} title={t("외관 설정")} />

            <Field label={t("언어")} hint={t("앱에서 사용할 언어를 선택합니다.")}>
                <Select
                    value={language}
                    onChange={(event) => setLanguage(event.target.value as typeof language)}
                    options={LANGUAGE_OPTIONS}
                    aria-label={t("언어")}
                />
            </Field>

            <Field
                label={t("컬러 테마")}
                hint={<>{t("현재:")} <span className="font-medium" style={{ color: "var(--primary)" }}>{themeId === "custom" ? `${t("사용자 지정")} (${customColor})` : t(THEMES.find((theme) => theme.id === themeId)?.label ?? "")}</span></>}
            >
                <div className="flex gap-3 flex-wrap items-center">
                    {THEMES.map((theme) => (
                        <button
                            key={theme.id}
                            onClick={() => setTheme(theme.id as ThemeId)}
                            title={t(theme.label)}
                            aria-label={`${t(theme.label)} ${t("컬러 테마")}`}
                            className={`w-10 h-10 rounded-full border-4 transition-all  ${themeId === theme.id ? "border-ink " : "border-transparent"}`}
                            style={{ backgroundColor: theme.primary }}
                        />
                    ))}
                    <div className="relative">
                        <input ref={colorPickerRef} type="color" className="absolute opacity-0 w-0 h-0" value={customColor} onChange={(event) => setCustomColor(event.target.value)} />
                        <button
                            onClick={() => colorPickerRef.current?.click()}
                            title={`${t("사용자 지정")} ${t("컬러 테마")}`}
                            aria-label={`${t("사용자 지정")} ${t("컬러 테마")}`}
                            className={`w-10 h-10 rounded-full border-4 transition-all  overflow-hidden ${themeId === "custom" ? "border-ink " : "border-transparent"}`}
                            style={{ background: themeId === "custom" ? customColor : "conic-gradient(red, yellow, lime, cyan, blue, magenta, red)" }}
                        />
                    </div>
                </div>
            </Field>

            <Field label={t("페이지 타이틀")} hint={t("브라우저 탭 제목이 변경됩니다 (최대 32자)")}>
                <div className="flex gap-2">
                    <Input type="text" maxLength={32} value={titleInput} onChange={(event) => setTitleInput(event.target.value)} placeholder="Phrolova" className="flex-1" />
                    <Button variant="primary" onClick={() => setPageTitle(titleInput)}>{t("적용")}</Button>
                </div>
            </Field>

            <Field label={t("탭 아이콘 (Favicon)")} hint={t("브라우저 탭 좌측 아이콘이 변경됩니다.")}>
                <input ref={iconInputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={handleIconUpload} />
                <Button icon={ImageIcon} onClick={() => iconInputRef.current?.click()} className="w-full">
                    {t("이미지 업로드 (PNG · JPG · WEBP, 512KB 이하)")}
                </Button>
            </Field>

            <Button
                icon={RotateCcw}
                onClick={() => {
                    resetAll();
                    setTitleInput("Phrolova");
                }}
                className="w-full"
            >
                {t("외관 초기화 (기본값 복원)")}
            </Button>
        </Card>
    );
}

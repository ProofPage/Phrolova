import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";
import type { Settings as SettingsType } from "../../api/client";
import { THEMES, type ThemeId, useTheme } from "../../contexts/ThemeContext";
import { LANGUAGE_OPTIONS, useLanguage } from "../../contexts/LanguageContext";
import { Button, Card, Field, Input, Select } from "../ui/primitives";

interface Props {
    settings: SettingsType | null;
    /** 외관 설정은 브라우저에 즉시 저장되지만 탭 props 형태를 통일한다. */
    onSaved: () => void;
    /** 변경사항 유무를 상위 탭 전환 경고에 알린다. */
    onDirtyChange?: (dirty: boolean) => void;
}

export function AppearanceTab({ onDirtyChange }: Props) {
    const { themeId, customColor, pageTitle, setTheme, setCustomColor, setPageTitle, resetAll } = useTheme();
    const { language, setLanguage, t } = useLanguage();
    const [titleInput, setTitleInput] = useState(pageTitle);
    const colorPickerRef = useRef<HTMLInputElement>(null);
    const dirty = titleInput !== pageTitle;

    useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);

    return (
        <Card className="appearance-settings">

            <Field label={t("settings.language")}>
                <Select
                    value={language}
                    onChange={(event) => setLanguage(event.target.value as typeof language)}
                    options={LANGUAGE_OPTIONS}
                    aria-label={t("settings.language")}
                />
            </Field>

            <Field
                label={t("settings.colorTheme")}
                hint={<>{t("settings.current")} <span className="font-medium" style={{ color: "var(--primary)" }}>{themeId === "custom" ? `${t("settings.custom")} (${customColor})` : t(THEMES.find((theme) => theme.id === themeId)?.label ?? "")}</span></>}
            >
                <div className="flex gap-3 flex-wrap items-center">
                    {THEMES.map((theme) => (
                        <button
                            key={theme.id}
                            onClick={() => setTheme(theme.id as ThemeId)}
                            title={t(theme.label)}
                            aria-label={`${t(theme.label)} ${t("settings.colorTheme")}`}
                            aria-pressed={themeId === theme.id}
                            className={`theme-swatch w-10 h-10 rounded-full border-4 transition-all  ${themeId === theme.id ? "border-ink " : "border-transparent"}`}
                            style={{ backgroundColor: theme.primary }}
                        />
                    ))}
                    <div className="relative">
                        <input ref={colorPickerRef} tabIndex={-1} aria-hidden="true" type="color" className="absolute opacity-0 w-0 h-0" value={customColor} onChange={(event) => setCustomColor(event.target.value)} />
                        <button
                            onClick={() => colorPickerRef.current?.click()}
                            title={`${t("settings.custom")} ${t("settings.colorTheme")}`}
                            aria-label={`${t("settings.custom")} ${t("settings.colorTheme")}`}
                            aria-pressed={themeId === "custom"}
                            className={`theme-swatch w-10 h-10 rounded-full border-4 transition-all  overflow-hidden ${themeId === "custom" ? "border-ink " : "border-transparent"}`}
                            style={{ background: themeId === "custom" ? customColor : "conic-gradient(red, yellow, lime, cyan, blue, magenta, red)" }}
                        />
                    </div>
                </div>
            </Field>

            <Field label={t("settings.pageTitle")} hint={t("settings.changesTheBrowserTabTitleUpTo32Characters")}>
                <div className="flex gap-2">
                    <Input type="text" maxLength={32} value={titleInput} onChange={(event) => setTitleInput(event.target.value)} placeholder="Phrolova" className="flex-1" />
                    <Button variant="primary" onClick={() => setPageTitle(titleInput)}>{t("settings.apply")}</Button>
                </div>
            </Field>

            <div className="appearance-actions">
            <Button
                icon={RotateCcw}
                onClick={() => {
                    resetAll();
                    setTitleInput("Phrolova");
                }}
            >
                {t("settings.resetAppearance")}
            </Button>
            </div>
        </Card>
    );
}

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { SlidersHorizontal, X } from "lucide-react";
import { api, PLATFORM_LABELS, type Channel, type ChannelDownloadOptions, type DownloadCondition, type Platform } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";
import { DOWNLOAD_CONDITIONS } from "./LiveDownloadCondition";
import { useLanguage } from "../../contexts/LanguageContext";

interface Props {
    platform: Platform;
    name: string;
    channel?: Channel;
    onClose: () => void;
    onSave: (options: ChannelDownloadOptions) => Promise<void>;
}

export function ChannelDownloadModal({ platform, name, channel, onClose, onSave }: Props) {
    const { t } = useLanguage();
    const dialog = useRef<HTMLDialogElement>(null);
    const editedTags = useRef(false);
    const [autoRecord, setAutoRecord] = useState(channel?.auto_record ?? true);
    const [condition, setCondition] = useState<DownloadCondition | "inherit">(channel?.download_condition ?? "inherit");
    const [tags, setTags] = useState(channel?.watchalong_tags ?? "같이보기");
    const [initialTags, setInitialTags] = useState(channel?.watchalong_tags ?? "같이보기");
    const [defaultLabel, setDefaultLabel] = useState("확인 중...");
    const [saving, setSaving] = useState(false);
    const dirty = !channel || autoRecord !== channel.auto_record ||
        condition !== (channel.download_condition ?? "inherit") ||
        (condition === "watchalong" && tags !== initialTags);
    const toast = useToast();

    useEffect(() => {
        dialog.current?.showModal();
        let active = true;
        void api.getSettings().then((settings) => {
            if (!active) return;
            const label = DOWNLOAD_CONDITIONS.find((item) => item.value === settings.live_download_condition)?.label;
            setDefaultLabel(label || "모든 방송 녹화");
            if (!channel?.watchalong_tags && !editedTags.current) {
                setTags(settings.watchalong_tags || "같이보기");
                setInitialTags(settings.watchalong_tags || "같이보기");
            }
        }).catch(() => { if (active) setDefaultLabel("확인할 수 없음"); });
        return () => { active = false; };
    }, [channel]);

    const save = async () => {
        setSaving(true);
        try {
            await onSave({
                auto_record: autoRecord,
                download_condition: platform === "chzzk" && condition !== "inherit" ? condition : null,
                watchalong_tags: platform === "chzzk" && condition === "watchalong" ? tags : null,
            });
            onClose();
        } catch (error) {
            toast.error(getErrorMessage(error, "채널 설정 저장에 실패했습니다."));
        } finally {
            setSaving(false);
        }
    };

    return createPortal(
        <dialog ref={dialog} aria-labelledby="channel-download-title" onCancel={(event) => { event.preventDefault(); if (!saving) onClose(); }}
            className="m-auto w-[calc(100%_-_2rem)] max-w-lg max-h-[90dvh] overflow-y-auto rounded-[var(--radius-card)] border border-line bg-surface-2 text-ink p-0 shadow-2xl backdrop:bg-black/70">
            <form onSubmit={(event) => { event.preventDefault(); void save(); }} className="p-5 sm:p-6 space-y-5 max-sm:p-3 max-sm:space-y-3">
                <div className="flex items-start gap-3">
                    <SlidersHorizontal className="w-5 h-5 text-[var(--primary)] shrink-0 mt-1" />
                    <div className="flex-1 min-w-0">
                        <h2 id="channel-download-title" className="font-bold text-lg">{channel ? t("채널 녹화 설정") : t("라이브 채널 추가")}</h2>
                        <p className="text-xs text-ink-muted mt-1 truncate" title={name}>{PLATFORM_LABELS[platform]} · {name}</p>
                    </div>
                    <button type="button" onClick={onClose} disabled={saving} aria-label="설정 닫기" className="channel-settings-close p-1 text-ink-faint hover:text-ink"><X className="w-5 h-5" /></button>
                </div>
                <SettingRow label={t("자동 녹화")} hint={t("방송이 시작되고 녹화 조건에 맞으면 자동으로 저장합니다.")}
                    control={<Switch checked={autoRecord} disabled={saving} onChange={setAutoRecord} label={`${name} ${t("자동 녹화")}`} />} />
                {platform === "chzzk" && <>
                    <Field label={t("녹화 조건")} htmlFor="channel-download-condition" hint={condition === "inherit" ? `${t("현재 기본값")}: ${t(defaultLabel)}` : t("이 채널에만 적용합니다.")}>
                        <Select id="channel-download-condition" value={condition} autoFocus disabled={saving} onChange={(event) => setCondition(event.target.value as typeof condition)}
                            options={[{ value: "inherit", label: t("기본 조건 사용") }, ...DOWNLOAD_CONDITIONS.map((item) => ({ ...item, label: t(item.label) }))]} />
                    </Field>
                    {channel && <div className="text-xs text-ink-muted flex flex-wrap gap-x-2 gap-y-1"><span className="font-medium">{t("현재 방송 태그")}</span><span className="text-ink-faint">{channel.broadcast_tags == null ? t("확인 대기") : channel.broadcast_tags.length ? channel.broadcast_tags.join(" · ") : t("없음")}</span></div>}
                    {channel?.is_watchalong === true && <p className="text-xs text-[var(--primary)]">{t("Chzzk 같이보기 방송")}{channel.watchalong_tag ? ` · ${channel.watchalong_tag}` : ""}</p>}
                    {condition === "watchalong" && <Field label={t("같이보기 태그")} htmlFor="channel-watchalong-tags" hint={t("‘같이보기’는 전체 같이보기를 선택합니다. 특정 콘텐츠 태그는 쉼표로 구분하세요.")}>
                        <Input id="channel-watchalong-tags" value={tags} maxLength={500} disabled={saving} onChange={(event) => { editedTags.current = true; setTags(event.target.value); }} placeholder={t("예: 같이보기")} />
                    </Field>}
                    <p className="text-xs text-ink-faint leading-relaxed">{t("Chzzk의 같이보기 정보와 방송 태그를 확인합니다. 변경 사항은 다음 자동 녹화부터 적용되며, 진행 중인 녹화와 수동 녹화에는 영향을 주지 않습니다.")}</p>
                </>}
                <div className="flex justify-end gap-2 border-t border-line pt-4">
                    <Button type="button" disabled={saving} onClick={onClose}>취소</Button>
                    <Button type="submit" variant="primary" loading={saving} disabled={!dirty || (platform === "chzzk" && condition === "watchalong" && !tags.trim())}>{channel ? "설정 저장" : "채널 추가"}</Button>
                </div>
            </form>
        </dialog>, document.body,
    );
}

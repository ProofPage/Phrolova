import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { SlidersHorizontal, X } from "lucide-react";
import { api, PLATFORM_LABELS, type Channel, type ChannelDownloadOptions, type DownloadCondition, type Platform } from "../../api/client";
import { getErrorMessage } from "../../utils/error";
import { useToast } from "../ui/Toast";
import { Button, Field, Input, Select, SettingRow, Switch } from "../ui/primitives";
import { DOWNLOAD_CONDITIONS } from "./LiveDownloadCondition";

interface Props {
    platform: Platform;
    name: string;
    channel?: Channel;
    onClose: () => void;
    onSave: (options: ChannelDownloadOptions) => Promise<void>;
}

export function ChannelDownloadModal({ platform, name, channel, onClose, onSave }: Props) {
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
        (condition !== "inherit" && tags !== initialTags);
    const toast = useToast();

    useEffect(() => {
        dialog.current?.showModal();
        let active = true;
        void api.getSettings().then((settings) => {
            if (!active) return;
            const label = DOWNLOAD_CONDITIONS.find((item) => item.value === settings.live_download_condition)?.label;
            setDefaultLabel(label || "모든 라이브 다운로드");
            if (!channel?.watchalong_tags && !editedTags.current) {
                setTags(settings.watchalong_tags);
                setInitialTags(settings.watchalong_tags);
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
                watchalong_tags: platform === "chzzk" && condition !== "inherit" ? tags : null,
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
            <form onSubmit={(event) => { event.preventDefault(); void save(); }} className="p-5 sm:p-6 space-y-5">
                <div className="flex items-start gap-3">
                    <SlidersHorizontal className="w-5 h-5 text-[var(--primary)] shrink-0 mt-1" />
                    <div className="flex-1 min-w-0">
                        <h2 id="channel-download-title" className="font-bold text-lg">{channel ? "채널 다운로드 설정" : "라이브 채널 추가"}</h2>
                        <p className="text-xs text-ink-muted mt-1 truncate" title={name}>{PLATFORM_LABELS[platform]} · {name}</p>
                    </div>
                    <button type="button" onClick={onClose} disabled={saving} aria-label="설정 닫기" className="p-1 text-ink-faint hover:text-ink"><X className="w-5 h-5" /></button>
                </div>
                <SettingRow label="자동 다운로드" hint="조건에 맞는 방송을 자동으로 저장합니다."
                    control={<Switch checked={autoRecord} disabled={saving} onChange={setAutoRecord} label="자동 다운로드" />} />
                {platform === "chzzk" && <>
                    <Field label="다운로드 조건" htmlFor="channel-download-condition" hint={condition === "inherit" ? `현재 기본값: ${defaultLabel}` : "이 스트리머에만 적용합니다."}>
                        <Select id="channel-download-condition" value={condition} autoFocus disabled={saving} onChange={(event) => setCondition(event.target.value as typeof condition)}
                            options={[{ value: "inherit", label: "기본 조건 사용" }, ...DOWNLOAD_CONDITIONS]} />
                    </Field>
                    {channel && <div className="text-xs text-ink-muted flex flex-wrap gap-x-2 gap-y-1"><span className="font-medium">현재 방송 태그</span><span className="text-ink-faint">{channel.broadcast_tags == null ? "확인 대기" : channel.broadcast_tags.length ? channel.broadcast_tags.join(" · ") : "없음"}</span></div>}
                    {condition !== "inherit" && <Field label="같이보기 태그" htmlFor="channel-watchalong-tags" hint="여러 태그는 쉼표로 구분합니다. 하나만 일치해도 같이보기로 판단합니다.">
                        <Input id="channel-watchalong-tags" value={tags} maxLength={500} disabled={saving} onChange={(event) => { editedTags.current = true; setTags(event.target.value); }} placeholder="예: 같이보기" />
                    </Field>}
                    <p className="text-xs text-ink-faint leading-relaxed">다음 자동 시작부터 적용됩니다. 진행 중인 녹화는 계속되며, 수동 시작은 언제든 사용할 수 있습니다.</p>
                </>}
                <div className="flex justify-end gap-2 border-t border-line pt-4">
                    <Button type="button" disabled={saving} onClick={onClose}>취소</Button>
                    <Button type="submit" variant="primary" loading={saving} disabled={!dirty || (platform === "chzzk" && condition !== "inherit" && !tags.trim())}>{channel ? "설정 저장" : "채널 추가"}</Button>
                </div>
            </form>
        </dialog>, document.body,
    );
}
